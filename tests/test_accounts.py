import json
import os
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from brain_games.accounts import (
    AccountStore,
    AccountValidationError,
    DuplicateAccountError,
    get_default_path,
    normalize_username,
)


class AccountStoreTest(unittest.TestCase):

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.path = Path(self.temporary_directory.name) / 'accounts.json'
        self.accounts = AccountStore(self.path)

    def test_default_path_uses_environment_data_directory(self):
        data_directory = Path(self.temporary_directory.name) / 'custom'
        with mock.patch.dict(
                os.environ,
                {'BRAIN_GAMES_DATA_DIR': str(data_directory)},
        ):
            self.assertEqual(
                get_default_path(),
                data_directory / 'accounts.json',
            )

    def test_username_is_trimmed_lowercased_and_validated(self):
        self.assertEqual(
            normalize_username(' Ada_Lovelace-1 '),
            'ada_lovelace-1',
        )

        invalid_usernames = (
            '',
            'ab',
            'a' * 25,
            'has spaces',
            'not@allowed',
            None,
        )
        for username in invalid_usernames:
            with self.subTest(username=username):
                with self.assertRaises(AccountValidationError):
                    normalize_username(username)

    def test_create_persists_and_authenticates_without_exposing_hash(self):
        created = self.accounts.create(' Ada-1 ', 'correct horse')

        self.assertEqual(created['username'], 'ada-1')
        self.assertEqual(
            set(created),
            {'account_id', 'username', 'created_at'},
        )
        self.assertRegex(created['account_id'], r'^[0-9a-f]{32}$')
        created_at = datetime.fromisoformat(created['created_at'])
        self.assertEqual(created_at.utcoffset(), timezone.utc.utcoffset(None))

        reloaded = AccountStore(self.path)
        self.assertEqual(reloaded.get('ADA-1'), created)
        self.assertEqual(
            reloaded.authenticate(' Ada-1 ', 'correct horse'),
            created,
        )
        self.assertNotIn('password_hash', reloaded.get('ada-1'))

        payload = json.loads(self.path.read_text(encoding='utf-8'))
        stored = payload['accounts'][0]
        self.assertEqual(payload['version'], 2)
        self.assertEqual(stored['account_id'], created['account_id'])
        self.assertIn('password_hash', stored)
        self.assertNotEqual(stored['password_hash'], 'correct horse')

    def test_duplicate_usernames_are_case_insensitive(self):
        self.accounts.create('Grace', 'first password')

        with self.assertRaises(DuplicateAccountError):
            self.accounts.create('  GRACE  ', 'second password')

        self.assertIsNotNone(
            self.accounts.authenticate('grace', 'first password'),
        )
        self.assertIsNone(
            self.accounts.authenticate('grace', 'second password'),
        )

    def test_bad_or_unknown_credentials_return_none(self):
        self.accounts.create('Turing', 'enigma-code')

        self.assertIsNone(self.accounts.authenticate('Turing', 'wrong-pass'))
        self.assertIsNone(self.accounts.authenticate('Unknown', 'wrong-pass'))
        self.assertIsNone(self.accounts.authenticate('x', 'wrong-pass'))
        self.assertIsNone(self.accounts.authenticate('Turing', None))

    def test_invalid_new_account_inputs_are_rejected(self):
        invalid_accounts = (
            ('ab', 'long enough'),
            ('bad name', 'long enough'),
            ('Valid_Name', 'short'),
            ('Valid_Name', None),
        )
        for username, password in invalid_accounts:
            with self.subTest(username=username, password=password):
                with self.assertRaises(AccountValidationError):
                    self.accounts.create(username, password)

        self.assertFalse(self.path.exists())

    def test_get_returns_none_for_unknown_and_rejects_invalid_username(self):
        self.assertIsNone(self.accounts.get('Nobody'))
        with self.assertRaises(AccountValidationError):
            self.accounts.get('no spaces allowed')

    def test_get_by_id_uses_opaque_identity_and_rejects_invalid_ids(self):
        created = self.accounts.create('Owner', 'correct horse')

        self.assertEqual(
            created,
            self.accounts.get_by_id(created['account_id']),
        )
        self.assertIsNone(self.accounts.get_by_id('owner'))
        self.assertIsNone(self.accounts.get_by_id(None))

    @unittest.skipUnless(os.name == 'posix', 'POSIX file modes only')
    def test_account_file_is_owner_readable_and_writable_only(self):
        self.accounts.create('Private_User', 'safe-password')

        mode = stat.S_IMODE(self.path.stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_concurrent_creates_do_not_lose_accounts(self):
        usernames = ['user-{}'.format(index) for index in range(4)]

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(
                lambda username: self.accounts.create(
                    username,
                    'password-{}'.format(username),
                ),
                usernames,
            ))

        reloaded = AccountStore(self.path)
        self.assertEqual(
            [reloaded.get(username)['username'] for username in usernames],
            usernames,
        )


if __name__ == '__main__':
    unittest.main()
