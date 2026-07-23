"""Durable SQLAlchemy Core storage for the BrainHacker web application."""

import copy
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import CheckConstraint
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import JSON
from sqlalchemy import MetaData
from sqlalchemy import PrimaryKeyConstraint
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import Text
from sqlalchemy import create_engine
from sqlalchemy import delete
from sqlalchemy import insert
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool
from werkzeug.security import check_password_hash
from werkzeug.security import generate_password_hash

from brain_games.accounts import _DUMMY_PASSWORD_HASH
from brain_games.accounts import _lookup_keys
from brain_games.accounts import _validate_new_password
from brain_games.accounts import _valid_account_id
from brain_games.accounts import AccountError
from brain_games.accounts import DuplicateAccountError
from brain_games.accounts import normalize_username
from brain_games.difficulty import CORRECT_PER_LEVEL
from brain_games.difficulty import max_level_for
from brain_games.leaderboard import Leaderboard
from brain_games.web_engine import _RunState
from brain_games.web_engine import MAX_LIVES
from brain_games.web_engine import MAX_PLAYER_LENGTH
from brain_games.web_engine import RunStore
from brain_games.web_engine import SCORE_GAME_PREFIX
from brain_games.web_engine import TIMING_MODES
from brain_games.web_engine import UnknownRunError


RUN_STATE_VERSION = 3
DEFAULT_RUN_TTL = timedelta(hours=24)
SCHEMA_LOCK_ID = 1878774371
PLAYER_KEY_LENGTH = MAX_PLAYER_LENGTH * 3

metadata = MetaData()

accounts_table = Table(
    'brainhacker_accounts',
    metadata,
    Column('account_id', String(32), primary_key=True),
    Column('username', String(24), nullable=False, unique=True),
    Column('password_hash', Text, nullable=False),
    Column('created_at', DateTime(timezone=True), nullable=False),
)

scores_table = Table(
    'brainhacker_scores',
    metadata,
    Column('player', String(64), nullable=False),
    Column('player_key', String(PLAYER_KEY_LENGTH), nullable=False),
    Column('game', String(32), nullable=False),
    Column('game_key', String(32), nullable=False),
    Column('score', Integer, nullable=False),
    Column('played_at', DateTime(timezone=True), nullable=False),
    CheckConstraint('score >= 0', name='brainhacker_score_nonnegative'),
    PrimaryKeyConstraint(
        'player_key',
        'game_key',
        name='brainhacker_scores_primary',
    ),
)

Index(
    'brainhacker_scores_rank',
    scores_table.c.game_key,
    scores_table.c.score.desc(),
    scores_table.c.player_key,
)
Index(
    'brainhacker_scores_player',
    scores_table.c.player_key,
    scores_table.c.score.desc(),
)

run_state_type = JSON().with_variant(JSONB(), 'postgresql')
runs_table = Table(
    'brainhacker_runs',
    metadata,
    Column('run_id', String(32), primary_key=True),
    Column('state', run_state_type, nullable=False),
    Column('updated_at', DateTime(timezone=True), nullable=False),
    Column('expires_at', DateTime(timezone=True), nullable=False),
)
Index('brainhacker_runs_expiry', runs_table.c.expires_at)


def _utc_now():
    return datetime.now(timezone.utc)


def _iso_timestamp(value):
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _public_account(row):
    return {
        'account_id': row['account_id'],
        'username': row['username'],
        'created_at': _iso_timestamp(row['created_at']),
    }


def _public_score(row):
    return {
        'player': row['player'],
        'game': row['game'],
        'score': row['score'],
        'played_at': _iso_timestamp(row['played_at']),
    }


def create_database_engine(database_url):
    """Return a short-lived-connection engine suitable for functions."""
    if not isinstance(database_url, str) or not database_url.strip():
        raise ValueError('database_url must be a non-empty string')
    return create_engine(
        database_url,
        poolclass=NullPool,
    )


def ensure_schema(engine):
    """Create the small application schema under a Postgres advisory lock."""
    with engine.begin() as connection:
        if connection.dialect.name == 'postgresql':
            connection.execute(
                text('SELECT pg_advisory_xact_lock(:lock_id)'),
                {'lock_id': SCHEMA_LOCK_ID},
            )
        metadata.create_all(connection)


class PostgresAccountStore:
    """AccountStore-compatible records persisted with SQLAlchemy Core."""

    def __init__(self, engine):
        self.engine = engine

    def create(self, username, password):
        """Create an account and return its non-sensitive public fields."""
        canonical_username = normalize_username(username)
        password = _validate_new_password(password)
        account = {
            'account_id': secrets.token_hex(16),
            'username': canonical_username,
            'password_hash': generate_password_hash(password),
            'created_at': _utc_now(),
        }
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(accounts_table).values(**account))
        except IntegrityError as error:
            if self._username_exists(canonical_username):
                raise DuplicateAccountError(
                    'username is already registered',
                ) from error
            raise AccountError('could not create account') from error
        return _public_account(account)

    def authenticate(self, username, password):
        """Return public account data for valid credentials."""
        try:
            canonical_username = normalize_username(username)
        except ValueError:
            return None
        if not isinstance(password, str):
            return None

        account = self._account_by(
            accounts_table.c.username == canonical_username,
        )
        password_hash = (
            account['password_hash']
            if account is not None
            else _DUMMY_PASSWORD_HASH
        )
        password_matches = check_password_hash(password_hash, password)
        if account is None or not password_matches:
            return None
        return _public_account(account)

    def get(self, username):
        """Return a public account by canonical username."""
        canonical_username = normalize_username(username)
        account = self._account_by(
            accounts_table.c.username == canonical_username,
        )
        return _public_account(account) if account is not None else None

    def get_by_id(self, account_id):
        """Return a public account by its opaque identifier."""
        if not _valid_account_id(account_id):
            return None
        account = self._account_by(
            accounts_table.c.account_id == account_id,
        )
        return _public_account(account) if account is not None else None

    def lookup_many(self, usernames=(), account_ids=()):
        """Resolve username and ID sets with one database query."""
        username_keys, id_keys = _lookup_keys(usernames, account_ids)
        if not username_keys and not id_keys:
            return {'by_username': {}, 'by_id': {}}

        conditions = []
        if username_keys:
            conditions.append(accounts_table.c.username.in_(username_keys))
        if id_keys:
            conditions.append(accounts_table.c.account_id.in_(id_keys))
        statement = select(accounts_table).where(or_(*conditions))
        with self.engine.connect() as connection:
            rows = list(connection.execute(statement).mappings())

        public_accounts = [
            (row, _public_account(row))
            for row in rows
        ]
        return {
            'by_username': {
                row['username']: public
                for row, public in public_accounts
                if row['username'] in username_keys
            },
            'by_id': {
                row['account_id']: public
                for row, public in public_accounts
                if row['account_id'] in id_keys
            },
        }

    def _account_by(self, condition):
        statement = select(accounts_table).where(condition)
        with self.engine.connect() as connection:
            return connection.execute(statement).mappings().first()

    def _username_exists(self, username):
        return self._account_by(
            accounts_table.c.username == username,
        ) is not None


def _dialect_insert(connection, table):
    dialect = connection.dialect.name
    if dialect == 'postgresql':
        return postgres_insert(table)
    if dialect == 'sqlite':
        return sqlite_insert(table)
    raise RuntimeError('unsupported database dialect: {}'.format(dialect))


class PostgresLeaderboard:
    """Leaderboard-compatible high scores stored in Postgres."""

    def __init__(self, engine):
        self.engine = engine

    def record(self, player, game, score):
        """Atomically retain and return one player's best score."""
        with self.engine.begin() as connection:
            return self.record_in_transaction(
                connection,
                player,
                game,
                score,
            )

    def record_in_transaction(self, connection, player, game, score):
        """Record a best score using an existing database transaction."""
        entry = Leaderboard._new_entry(player, game, score)
        values = {
            'player': entry['player'],
            'player_key': entry['player'].casefold(),
            'game': entry['game'],
            'game_key': entry['game'].casefold(),
            'score': entry['score'],
            'played_at': _utc_now(),
        }
        statement = _dialect_insert(connection, scores_table)
        statement = statement.values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=(
                scores_table.c.player_key,
                scores_table.c.game_key,
            ),
            set_={
                'player': statement.excluded.player,
                'game': statement.excluded.game,
                'score': statement.excluded.score,
                'played_at': statement.excluded.played_at,
            },
            where=statement.excluded.score > scores_table.c.score,
        )
        connection.execute(statement)
        retained = self._score_by_key(
            connection,
            values['player_key'],
            values['game_key'],
        )
        return _public_score(retained)

    def top(self, limit=10, game=None, player=None, game_prefix=None):
        """Return ranked high scores with optional game/player filters."""
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError('limit must be an integer')
        if limit <= 0:
            return []

        statement = select(scores_table)
        if game is not None:
            statement = statement.where(
                scores_table.c.game_key == self._filter_key('game', game),
            )
        if game_prefix is not None:
            prefix = self._filter_key('game prefix', game_prefix)
            statement = statement.where(
                scores_table.c.game_key.like(
                    '{}%'.format(self._escape_like(prefix)),
                    escape='\\',
                ),
            )
        if player is not None:
            statement = statement.where(
                scores_table.c.player_key == self._filter_key(
                    'player',
                    player,
                ),
            )
        statement = statement.order_by(
            scores_table.c.score.desc(),
            scores_table.c.player_key,
            scores_table.c.game_key,
            scores_table.c.player,
            scores_table.c.game,
            scores_table.c.played_at,
        ).limit(limit)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings()
            return [_public_score(row) for row in rows]

    @staticmethod
    def _filter_key(field, value):
        if not isinstance(value, str):
            raise TypeError('{} must be a string or None'.format(field))
        key = value.strip().casefold()
        if not key:
            return key
        return key

    @staticmethod
    def _escape_like(value):
        return (
            value
            .replace('\\', '\\\\')
            .replace('%', '\\%')
            .replace('_', '\\_')
        )

    @staticmethod
    def _score_by_key(connection, player_key, game_key):
        statement = select(scores_table).where(
            scores_table.c.player_key == player_key,
            scores_table.c.game_key == game_key,
        )
        return connection.execute(statement).mappings().one()


def serialize_run_state(state):
    """Return a JSON-safe snapshot of a private browser run."""
    return {
        'version': RUN_STATE_VERSION,
        'run_id': state.run_id,
        'game_slug': state.game_slug,
        'player': state.player,
        'ranked': state.ranked,
        'timing_mode': state.timing_mode,
        'score': state.score,
        'lives': state.lives,
        'level': state.level,
        'level_progress': state.level_progress,
        'ended': state.ended,
        'quit_early': state.quit_early,
        'recorded': state.recorded,
        'round': copy.deepcopy(state.round),
        'digit_count': state.digit_count,
        'seen_words': sorted(state.seen_words),
        'word_history': list(state.word_history),
        'new_word_index': state.new_word_index,
        'game_bag': list(state.game_bag),
        'last_source_slug': state.last_source_slug,
        'cycle_position': state.cycle_position,
        'truth_bags': copy.deepcopy(state.truth_bags),
        'rng_state': _serializable_rng_state(state.rng),
    }


def _serializable_rng_state(rng):
    getter = getattr(rng, 'getstate', None)
    if not callable(getter):
        return None
    try:
        return copy.deepcopy(getter())
    except (TypeError, ValueError):
        return None


def _nested_tuple(value):
    if isinstance(value, list):
        return tuple(_nested_tuple(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_nested_tuple(item) for item in value)
    return value


def _restore_rng_state(rng, rng_state):
    if rng_state is None:
        return
    setter = getattr(rng, 'setstate', None)
    if not callable(setter):
        return
    try:
        setter(_nested_tuple(rng_state))
    except (TypeError, ValueError) as error:
        raise ValueError('invalid random state') from error


def _snapshot_fields_are_typed(payload):
    expected_types = {
        'run_id': str,
        'game_slug': str,
        'player': str,
        'ranked': bool,
        'timing_mode': str,
        'score': int,
        'lives': int,
        'level': int,
        'level_progress': int,
        'ended': bool,
        'quit_early': bool,
        'recorded': bool,
        'digit_count': int,
        'seen_words': list,
        'word_history': list,
        'new_word_index': int,
        'game_bag': list,
        'truth_bags': dict,
    }
    return all(
        isinstance(payload.get(field), expected)
        for field, expected in expected_types.items()
    )


def _snapshot_integers_are_valid(payload):
    integer_fields = (
        'score',
        'lives',
        'level',
        'level_progress',
        'digit_count',
        'new_word_index',
    )
    if any(isinstance(payload[field], bool) for field in integer_fields):
        return False
    if payload['score'] < 0 or payload['new_word_index'] < 0:
        return False
    if not 0 <= payload['lives'] <= MAX_LIVES:
        return False
    if not 1 <= payload['level'] <= max_level_for(payload['game_slug']):
        return False
    return 0 <= payload['level_progress'] < CORRECT_PER_LEVEL


def _snapshot_lists_are_valid(payload):
    word_lists = (
        payload['seen_words'],
        payload['word_history'],
        payload['game_bag'],
    )
    if any(
            not all(isinstance(item, str) for item in values)
            for values in word_lists
    ):
        return False
    return True


def _snapshot_truth_bags_are_valid(payload):
    for key, values in payload['truth_bags'].items():
        if not isinstance(key, str) or not isinstance(values, list):
            return False
        if not all(isinstance(value, bool) for value in values):
            return False
    return True


def _snapshot_misc_fields_are_valid(payload):
    if payload['timing_mode'] not in TIMING_MODES:
        return False
    if payload['ranked'] and payload['timing_mode'] != 'standard':
        return False
    if not isinstance(payload.get('rng_state'), (list, tuple, type(None))):
        return False
    round_value = payload.get('round')
    valid_round = round_value is None
    if not valid_round:
        valid_round = isinstance(round_value, dict)
    return valid_round


def _valid_run_snapshot(payload):
    if not isinstance(payload, dict):
        return False
    if payload.get('version') != RUN_STATE_VERSION:
        return False
    if not _snapshot_fields_are_typed(payload):
        return False
    return all((
        _snapshot_misc_fields_are_valid(payload),
        _snapshot_integers_are_valid(payload),
        _snapshot_lists_are_valid(payload),
        _snapshot_truth_bags_are_valid(payload),
    ))


def deserialize_run_state(payload, rng):
    """Restore a private run snapshot, including supported RNG state."""
    if not _valid_run_snapshot(payload):
        raise ValueError('invalid run snapshot')
    _restore_rng_state(rng, payload['rng_state'])
    state = _RunState(
        payload['run_id'],
        payload['game_slug'],
        payload['player'],
        rng,
        payload['ranked'],
        payload['timing_mode'],
    )
    state.score = payload['score']
    state.lives = payload['lives']
    state.level = payload['level']
    state.level_progress = payload['level_progress']
    state.ended = payload['ended']
    state.quit_early = payload['quit_early']
    state.recorded = payload['recorded']
    state.round = copy.deepcopy(payload.get('round'))
    state.digit_count = payload['digit_count']
    state.seen_words = set(payload['seen_words'])
    state.word_history = list(payload['word_history'])
    state.new_word_index = payload['new_word_index']
    state.game_bag = list(payload['game_bag'])
    state.last_source_slug = payload.get('last_source_slug')
    state.cycle_position = payload.get('cycle_position')
    state.truth_bags = copy.deepcopy(payload['truth_bags'])
    return state


class PostgresRunStore(RunStore):
    """RunStore whose private states survive function instances."""

    def __init__(
            self,
            engine,
            leaderboard,
            random_factory=None,
            run_ttl=DEFAULT_RUN_TTL,
    ):
        super().__init__(
            leaderboard=leaderboard,
            random_factory=random_factory,
        )
        if not isinstance(run_ttl, timedelta) or run_ttl.total_seconds() <= 0:
            raise ValueError('run_ttl must be a positive timedelta')
        self.engine = engine
        self._run_ttl = run_ttl

    def create(
            self,
            game_slug,
            player,
            ranked=True,
            timing_mode='standard',
    ):
        """Create and persist a new browser run."""
        slug, clean_player = self._validated_run_owner(game_slug, player)
        if not isinstance(ranked, bool):
            raise TypeError('ranked must be a boolean')
        if not isinstance(timing_mode, str):
            raise TypeError('timing_mode must be a string')
        clean_timing_mode = timing_mode.strip().casefold()
        if clean_timing_mode not in TIMING_MODES:
            raise ValueError('timing_mode is not supported')
        ranked = ranked and clean_timing_mode == 'standard'
        state = _RunState(
            secrets.token_hex(16),
            slug,
            clean_player,
            self._new_rng(),
            ranked,
            clean_timing_mode,
        )
        state.round = self._make_round(state)
        now = _utc_now()
        with self.engine.begin() as connection:
            connection.execute(
                delete(runs_table).where(runs_table.c.expires_at <= now),
            )
            connection.execute(insert(runs_table).values(
                run_id=state.run_id,
                state=serialize_run_state(state),
                updated_at=now,
                expires_at=now + self._run_ttl,
            ))
        return self._public_run(state)

    def answer(self, run_id, round_id, answer):
        """Lock, grade, and persist one active round transactionally."""
        with self.engine.begin() as connection:
            state = self._locked_state(connection, run_id)
            payload = self._answer_state(state, round_id, answer)
            if state.ended:
                self._record_final_score_in_transaction(connection, state)
            self._save_state(connection, state)
            return payload

    def quit(self, run_id):
        """Lock, end, and persist a run transactionally and idempotently."""
        with self.engine.begin() as connection:
            state = self._locked_state(connection, run_id)
            payload = self._quit_state(state)
            if not state.recorded:
                self._record_final_score_in_transaction(connection, state)
            self._save_state(connection, state)
            return payload

    def _locked_state(self, connection, run_id):
        now = _utc_now()
        statement = select(runs_table.c.state).where(
            runs_table.c.run_id == run_id,
            runs_table.c.expires_at > now,
        ).with_for_update()
        payload = connection.execute(statement).scalar_one_or_none()
        if payload is None:
            raise UnknownRunError(run_id)
        try:
            return deserialize_run_state(payload, self._new_rng())
        except (KeyError, TypeError, ValueError) as error:
            raise UnknownRunError(run_id) from error

    def _save_state(self, connection, state):
        now = _utc_now()
        statement = update(runs_table).where(
            runs_table.c.run_id == state.run_id,
        ).values(
            state=serialize_run_state(state),
            updated_at=now,
            expires_at=now + self._run_ttl,
        )
        result = connection.execute(statement)
        if result.rowcount != 1:
            raise UnknownRunError(state.run_id)

    def _record_final_score_in_transaction(self, connection, state):
        if state.recorded:
            return
        if not state.ranked:
            state.recorded = True
            return
        same_engine = isinstance(
            self._leaderboard,
            PostgresLeaderboard,
        )
        if same_engine:
            same_engine = self._leaderboard.engine is self.engine
        if same_engine:
            self._leaderboard.record_in_transaction(
                connection,
                state.player,
                '{}{}'.format(SCORE_GAME_PREFIX, state.game_slug),
                state.score,
            )
        else:
            self._leaderboard.record(
                state.player,
                '{}{}'.format(SCORE_GAME_PREFIX, state.game_slug),
                state.score,
            )
        state.recorded = True

    @staticmethod
    def locked_state_statement(run_id, now=None):
        """Expose the row-locking query for dialect-level verification."""
        now = now or _utc_now()
        return select(runs_table.c.state).where(
            runs_table.c.run_id == run_id,
            runs_table.c.expires_at > now,
        ).with_for_update()


def build_database_stores(database_url):
    """Build one durable run store and account store for the web app."""
    engine = create_database_engine(database_url)
    ensure_schema(engine)
    leaderboard = PostgresLeaderboard(engine)
    return (
        PostgresRunStore(engine, leaderboard),
        PostgresAccountStore(engine),
    )
