"""Secure, file-backed account storage for the BrainHacker web app."""

import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Union

from werkzeug.security import check_password_hash, generate_password_hash

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None


DATA_DIR_ENV = 'BRAIN_GAMES_DATA_DIR'
ACCOUNTS_FILENAME = 'accounts.json'
SCHEMA_VERSION = 2
USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9_-]{3,24}$')
ACCOUNT_ID_PATTERN = re.compile(r'^[0-9a-f]{32}$')
MINIMUM_PASSWORD_LENGTH = 8
_DUMMY_PASSWORD_HASH = generate_password_hash(
    'brainhacker-invalid-login-placeholder',
)

_THREAD_LOCKS = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class AccountError(Exception):
    """Base class for account-store failures."""


class AccountValidationError(AccountError, ValueError):
    """Raised when account data does not meet the public constraints."""


class DuplicateAccountError(AccountError):
    """Raised when a username is already registered."""


def get_default_path() -> Path:
    """Return the account path, honoring the data-directory override."""
    configured_directory = os.getenv(DATA_DIR_ENV)
    if configured_directory:
        data_directory = Path(configured_directory).expanduser()
    else:
        data_directory = Path.home() / '.brain_games'
    return data_directory / ACCOUNTS_FILENAME


def normalize_username(username: str) -> str:
    """Validate and return the canonical, case-insensitive username."""
    if not isinstance(username, str):
        raise AccountValidationError('username must be a string')

    normalized = username.strip()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise AccountValidationError(
            'username must be 3-24 letters, numbers, underscores, or hyphens',
        )
    return normalized.casefold()


def _validate_new_password(password: str) -> str:
    if not isinstance(password, str):
        raise AccountValidationError('password must be a string')
    if len(password) < MINIMUM_PASSWORD_LENGTH:
        raise AccountValidationError(
            'password must be at least {} characters'.format(
                MINIMUM_PASSWORD_LENGTH,
            ),
        )
    return password


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _legacy_account_id(username: str, password_hash: str) -> str:
    """Give pre-v2 accounts an owner ID that could not be preclaimed."""
    identity = '\0'.join((
        'brainhacker-account-v2',
        username,
        password_hash,
    ))
    return hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32]


def _valid_account_id(account_id: object) -> bool:
    if not isinstance(account_id, str):
        return False
    return ACCOUNT_ID_PATTERN.fullmatch(account_id) is not None


def _lookup_keys(usernames=(), account_ids=()):
    """Return valid canonical keys for a batch account lookup."""
    if isinstance(usernames, str):
        usernames = (usernames,)
    if isinstance(account_ids, str):
        account_ids = (account_ids,)

    canonical_usernames = set()
    for username in usernames or ():
        try:
            canonical_usernames.add(normalize_username(username))
        except AccountValidationError:
            continue
    valid_account_ids = {
        account_id
        for account_id in account_ids or ()
        if _valid_account_id(account_id)
    }
    return canonical_usernames, valid_account_ids


def _stored_text(value: Dict[str, object], field: str) -> Optional[str]:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate:
        return None
    return candidate


def _stored_username(value: Dict[str, object]) -> Optional[str]:
    try:
        return normalize_username(value.get('username'))
    except AccountValidationError:
        return None


def _stored_account_id(
        value: Dict[str, object],
        username: str,
        password_hash: str,
) -> Optional[str]:
    account_id = value.get('account_id')
    if account_id is None:
        return _legacy_account_id(username, password_hash)
    if _valid_account_id(account_id):
        return account_id
    return None


def _thread_lock(path: Path) -> threading.RLock:
    key = str(path.resolve(strict=False))
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _THREAD_LOCKS[key] = lock
        return lock


@contextmanager
def _account_lock(path: Path):
    """Serialize account writes across threads and processes where possible."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + '.lock')
    with _thread_lock(path):
        with lock_path.open('a', encoding='utf-8') as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _public_account(account: Dict[str, str]) -> Dict[str, str]:
    return {
        'account_id': account['account_id'],
        'username': account['username'],
        'created_at': account['created_at'],
    }


def _normalize_stored_account(value: object) -> Optional[Dict[str, str]]:
    if not isinstance(value, dict):
        return None

    username = _stored_username(value)
    if username is None:
        return None

    password_hash = _stored_text(value, 'password_hash')
    created_at = _stored_text(value, 'created_at')
    if password_hash is None:
        return None
    if created_at is None:
        return None
    account_id = _stored_account_id(value, username, password_hash)
    if account_id is None:
        return None

    return {
        'account_id': account_id,
        'username': username,
        'password_hash': password_hash,
        'created_at': created_at,
    }


def _read_raw_accounts(path: Path):
    try:
        with path.open(encoding='utf-8') as accounts_file:
            payload = json.load(accounts_file)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []

    if not isinstance(payload, dict):
        return []
    raw_accounts = payload.get('accounts')
    return raw_accounts if isinstance(raw_accounts, list) else []


class AccountStore:
    """Create and authenticate accounts stored in an atomic JSON file."""

    def __init__(self, path: Optional[Union[str, os.PathLike]] = None):
        self.path = Path(path).expanduser() if path else get_default_path()

    def create(self, username: str, password: str) -> Dict[str, str]:
        """Create an account and return its non-sensitive public record."""
        canonical_username = normalize_username(username)
        password = _validate_new_password(password)
        password_hash = generate_password_hash(password)

        with _account_lock(self.path):
            accounts = self._load_accounts()
            if canonical_username in accounts:
                raise DuplicateAccountError('username is already registered')

            existing_ids = {
                stored_account['account_id']
                for stored_account in accounts.values()
            }
            account_id = secrets.token_hex(16)
            while account_id in existing_ids:
                account_id = secrets.token_hex(16)

            account = {
                'account_id': account_id,
                'username': canonical_username,
                'password_hash': password_hash,
                'created_at': _utc_timestamp(),
            }
            accounts[canonical_username] = account
            self._write_accounts(accounts)

        return _public_account(account)

    def authenticate(
            self,
            username: str,
            password: str,
    ) -> Optional[Dict[str, str]]:
        """Return the public account for valid credentials, otherwise None."""
        try:
            canonical_username = normalize_username(username)
        except AccountValidationError:
            return None
        if not isinstance(password, str):
            return None

        account = self._load_accounts().get(canonical_username)
        password_hash = (
            account['password_hash']
            if account is not None
            else _DUMMY_PASSWORD_HASH
        )
        password_matches = check_password_hash(password_hash, password)
        if account is None or not password_matches:
            return None
        return _public_account(account)

    def get(self, username: str) -> Optional[Dict[str, str]]:
        """Return a public account by username, or None when it is absent."""
        canonical_username = normalize_username(username)
        account = self._load_accounts().get(canonical_username)
        if account is None:
            return None
        return _public_account(account)

    def get_by_id(self, account_id: str) -> Optional[Dict[str, str]]:
        """Return a public account by its opaque owner ID, or None."""
        if not _valid_account_id(account_id):
            return None
        for account in self._load_accounts().values():
            if account['account_id'] == account_id:
                return _public_account(account)
        return None

    def lookup_many(self, usernames=(), account_ids=()):
        """Resolve username and ID sets from one account-file read."""
        username_keys, id_keys = _lookup_keys(usernames, account_ids)
        if not username_keys and not id_keys:
            return {'by_username': {}, 'by_id': {}}

        accounts = self._load_accounts()
        public_accounts = {
            username: _public_account(account)
            for username, account in accounts.items()
            if username in username_keys or account['account_id'] in id_keys
        }
        return {
            'by_username': {
                username: public_accounts[username]
                for username in username_keys
                if username in public_accounts
            },
            'by_id': {
                account['account_id']: public_accounts[username]
                for username, account in accounts.items()
                if all((
                    account['account_id'] in id_keys,
                    username in public_accounts,
                ))
            },
        }

    def _load_accounts(self) -> Dict[str, Dict[str, str]]:
        accounts = {}
        for value in _read_raw_accounts(self.path):
            account = _normalize_stored_account(value)
            if account is not None:
                accounts.setdefault(account['username'], account)
        return accounts

    def _write_accounts(
            self,
            accounts: Dict[str, Dict[str, str]],
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix='.{}.'.format(self.path.name),
            suffix='.tmp',
        )
        temporary_path = Path(temporary_name)
        try:
            if hasattr(os, 'fchmod'):
                os.fchmod(file_descriptor, 0o600)
            with os.fdopen(file_descriptor, 'w', encoding='utf-8') as output:
                json.dump(
                    {
                        'version': SCHEMA_VERSION,
                        'accounts': [
                            accounts[username]
                            for username in sorted(accounts)
                        ],
                    },
                    output,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                output.write('\n')
                output.flush()
                os.fsync(output.fileno())
            os.replace(str(temporary_path), str(self.path))
        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
