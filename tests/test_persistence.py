import json
import os
import random
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from brain_games.accounts import DuplicateAccountError
from brain_games.app import create_app
from brain_games.persistence import deserialize_run_state
from brain_games.persistence import ensure_schema
from brain_games.persistence import PostgresAccountStore
from brain_games.persistence import PostgresLeaderboard
from brain_games.persistence import PostgresRunStore
from brain_games.persistence import RUN_STATE_VERSION
from brain_games.persistence import scores_table
from brain_games.persistence import serialize_run_state
from brain_games.web_engine import RunStore
from brain_games.web_engine import SCORE_GAME_PREFIX
from brain_games.web_engine import StaleRoundError
from brain_games.web_engine import UnknownRunError


class DatabasePersistenceTest(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        path = Path(self.directory.name) / 'brainhacker.db'
        self.engine = create_engine(
            'sqlite+pysqlite:///{}'.format(path),
        )
        self.addCleanup(self.engine.dispose)
        ensure_schema(self.engine)
        self.accounts = PostgresAccountStore(self.engine)
        self.leaderboard = PostgresLeaderboard(self.engine)

        def random_factory():
            return random.Random(4)

        self.first = PostgresRunStore(
            self.engine,
            self.leaderboard,
            random_factory=random_factory,
        )
        self.second = PostgresRunStore(
            self.engine,
            self.leaderboard,
            random_factory=random_factory,
        )

    def test_account_contract_persists_hash_and_opaque_identity(self):
        created = self.accounts.create(' Ada_1 ', 'correct horse')

        self.assertEqual('ada_1', created['username'])
        self.assertRegex(created['account_id'], r'^[0-9a-f]{32}$')
        self.assertEqual(
            created,
            self.accounts.authenticate('ADA_1', 'correct horse'),
        )
        self.assertEqual(
            created,
            self.accounts.get_by_id(created['account_id']),
        )
        self.assertIsNone(
            self.accounts.authenticate('ada_1', 'wrong password'),
        )
        with self.assertRaises(DuplicateAccountError):
            self.accounts.create('ADA_1', 'different password')

    def test_account_batch_lookup_uses_one_database_statement(self):
        ada = self.accounts.create('Ada_1', 'correct horse')
        grace = self.accounts.create('Grace', 'correct horse')
        statements = []

        def record_statement(*_arguments):
            statements.append(True)

        event.listen(
            self.engine,
            'before_cursor_execute',
            record_statement,
        )
        try:
            resolved = self.accounts.lookup_many(
                usernames=('ADA_1', 'missing', 'not a username'),
                account_ids=(grace['account_id'], 'invalid'),
            )
        finally:
            event.remove(
                self.engine,
                'before_cursor_execute',
                record_statement,
            )

        self.assertEqual(1, len(statements))
        self.assertEqual({'ada_1': ada}, resolved['by_username'])
        self.assertEqual(
            {grace['account_id']: grace},
            resolved['by_id'],
        )

    def test_leaderboard_upsert_retains_best_case_insensitively(self):
        first = self.leaderboard.record(' Ada ', ' Even ', 7)
        lower = self.leaderboard.record('ADA', 'EVEN', 2)
        higher = self.leaderboard.record('ada', 'even', 11)

        self.assertEqual(7, first['score'])
        self.assertEqual(first, lower)
        self.assertEqual(11, higher['score'])
        self.assertEqual(
            [higher],
            self.leaderboard.top(game='EVEN', player='ADA'),
        )

    def test_leaderboard_can_isolate_a_literal_version_prefix(self):
        current = self.leaderboard.record('Ada', 'r2:even', 7)
        second_current = self.leaderboard.record('Lin', 'R2:prime', 6)
        self.leaderboard.record('Grace', 'even', 99)
        self.leaderboard.record('Mina', 'r2%:gcd', 98)
        self.leaderboard.record('Noor', 'r2_:calc', 97)

        entries = self.leaderboard.top(game_prefix=' R2: ')

        self.assertEqual([current, second_current], entries)
        self.assertEqual(
            [current],
            self.leaderboard.top(game='r2:EVEN', game_prefix='r2:'),
        )
        self.assertEqual(
            ['r2%:gcd'],
            [
                entry['game']
                for entry in self.leaderboard.top(game_prefix='r2%:')
            ],
        )
        self.assertEqual(
            ['r2_:calc'],
            [
                entry['game']
                for entry in self.leaderboard.top(game_prefix='r2_:')
            ],
        )
        with self.assertRaises(TypeError):
            self.leaderboard.top(game_prefix=2)

    def test_player_key_allows_maximum_expanding_casefold(self):
        player = 'ß' * 64
        entry = self.leaderboard.record(player, 'even', 7)
        ddl = str(CreateTable(scores_table).compile(
            dialect=postgresql.dialect(),
        ))

        self.assertEqual([entry], self.leaderboard.top(player=player))
        self.assertIn('player_key VARCHAR(192) NOT NULL', ddl)
        self.assertIn(
            'PRIMARY KEY (player_key, game_key)',
            ddl,
        )

    def test_run_continues_across_store_instances_and_rejects_stale(self):
        started = self.first.create('even', 'Ada')
        game_round = started['round']
        number = int(game_round['data']['number'])
        answer = 'yes' if number % 2 == 0 else 'no'

        continued = self.second.answer(
            started['run_id'],
            game_round['round_id'],
            answer,
        )

        self.assertEqual(1, continued['score'])
        self.assertNotEqual(
            game_round['round_id'],
            continued['round']['round_id'],
        )
        with self.assertRaises(StaleRoundError):
            self.first.answer(
                started['run_id'],
                game_round['round_id'],
                answer,
            )

    def test_cross_instance_round_sequence_preserves_random_state(self):
        control = RunStore(random_factory=lambda: random.Random(4))
        control_run = control.create('calc', 'Ada')
        database_run = self.first.create('calc', 'Ada')
        self.assertEqual(
            control_run['round']['prompt'],
            database_run['round']['prompt'],
        )

        control_next = control.answer(
            control_run['run_id'],
            control_run['round']['round_id'],
            control._runs[control_run['run_id']].round['expected_answer'],
        )
        with self.engine.begin() as connection:
            database_state = self.first._locked_state(
                connection,
                database_run['run_id'],
            )
        database_next = self.second.answer(
            database_run['run_id'],
            database_run['round']['round_id'],
            database_state.round['expected_answer'],
        )

        self.assertEqual(
            control_next['round']['prompt'],
            database_next['round']['prompt'],
        )

    def test_cross_instance_quit_is_idempotent_and_records_once(self):
        started = self.first.create('prime', 'Grace')

        first_quit = self.second.quit(started['run_id'])
        second_quit = self.first.quit(started['run_id'])
        leaders = self.leaderboard.top(player='grace')

        self.assertEqual(first_quit, second_quit)
        self.assertTrue(first_quit['ended'])
        self.assertTrue(first_quit['quit_early'])
        self.assertEqual(1, len(leaders))
        self.assertEqual(0, leaders[0]['score'])

    def test_three_misses_survive_instance_changes_and_record_once(self):
        latest = self.first.create('calc', 'Lin')
        stores = (self.second, self.first, self.second)
        for store in stores:
            latest = store.answer(
                latest['run_id'],
                latest['round']['round_id'],
                'definitely-wrong',
            )

        ended_again = self.first.quit(latest['run_id'])
        leaders = self.leaderboard.top(player='lin')

        self.assertTrue(latest['ended'])
        self.assertEqual(latest['run_id'], ended_again['run_id'])
        self.assertEqual(latest['score'], ended_again['score'])
        self.assertTrue(ended_again['ended'])
        self.assertFalse(ended_again['quit_early'])
        self.assertEqual(1, len(leaders))
        self.assertEqual(0, leaders[0]['score'])

    def test_unranked_run_persists_but_never_records_a_score(self):
        started = self.first.create(
            'even',
            'Practice',
            ranked=False,
            timing_mode='self-paced',
        )
        restored = self.second.quit(started['run_id'])

        self.assertFalse(started['ranked'])
        self.assertFalse(restored['ranked'])
        self.assertEqual('self-paced', restored['timing_mode'])
        self.assertEqual(0, started['round']['time_limit_ms'])
        self.assertEqual([], self.leaderboard.top(player='practice'))
        self.assertEqual([], self.first.leaders(player='practice'))

    def test_ranked_database_score_uses_current_ruleset_privately(self):
        started = self.first.create('prime', 'Current')
        self.second.quit(started['run_id'])

        raw = self.leaderboard.top(player='current')
        public = self.first.leaders(player='current')

        self.assertEqual(
            '{}prime'.format(SCORE_GAME_PREFIX),
            raw[0]['game'],
        )
        self.assertEqual('prime', public[0]['game'])

    def test_missing_run_is_consistent_across_instances(self):
        with self.assertRaises(UnknownRunError):
            self.first.quit('missing')
        with self.assertRaises(UnknownRunError):
            self.second.quit('missing')


class RunSnapshotTest(unittest.TestCase):

    def test_snapshot_is_json_safe_and_restores_private_state(self):
        store = RunStore(random_factory=lambda: random.Random(8))
        run = store.create(
            'verbal-memory',
            'Ada',
            ranked=False,
            timing_mode='relaxed',
        )
        state = store._runs[run['run_id']]
        state.level = 4
        state.level_progress = 2
        state.truth_bags = {'prime:4': [True, False]}
        snapshot = serialize_run_state(state)
        expected_next_random = state.rng.random()

        encoded = json.dumps(snapshot)
        restored = deserialize_run_state(
            json.loads(encoded),
            random.Random(9),
        )

        self.assertEqual(state.run_id, restored.run_id)
        self.assertEqual(state.round, restored.round)
        self.assertEqual(state.ranked, restored.ranked)
        self.assertEqual(state.timing_mode, restored.timing_mode)
        self.assertEqual(state.level, restored.level)
        self.assertEqual(state.level_progress, restored.level_progress)
        self.assertEqual(state.seen_words, restored.seen_words)
        self.assertEqual(state.word_history, restored.word_history)
        self.assertEqual(state.game_bag, restored.game_bag)
        self.assertEqual(state.truth_bags, restored.truth_bags)
        self.assertEqual(expected_next_random, restored.rng.random())

    def test_snapshot_version_and_progress_are_strictly_validated(self):
        store = RunStore(random_factory=lambda: random.Random(8))
        run = store.create('even', 'Ada')
        snapshot = serialize_run_state(store._runs[run['run_id']])
        self.assertEqual(RUN_STATE_VERSION, snapshot['version'])

        for field, invalid in (
                ('version', RUN_STATE_VERSION - 1),
                ('level', 6),
                ('level_progress', 3),
                ('ranked', 'yes'),
                ('timing_mode', 'turbo'),
                ('truth_bags', {'even:1': [1]}),
        ):
            with self.subTest(field=field):
                malformed = dict(snapshot)
                malformed[field] = invalid
                with self.assertRaises(ValueError):
                    deserialize_run_state(malformed, random.Random(9))

    def test_snapshot_accepts_level_eight_only_for_eligible_games(self):
        store = RunStore(random_factory=lambda: random.Random(8))

        for slug in ('direction-focus', 'symbol-match', 'culmination'):
            with self.subTest(game=slug):
                run = store.create(slug, 'Ada')
                state = store._runs[run['run_id']]
                state.level = 8
                snapshot = serialize_run_state(state)

                restored = deserialize_run_state(
                    snapshot,
                    random.Random(9),
                )

                self.assertEqual(8, restored.level)

        run = store.create('even', 'Ada')
        state = store._runs[run['run_id']]
        state.level = 6

        with self.assertRaises(ValueError):
            deserialize_run_state(
                serialize_run_state(state),
                random.Random(9),
            )

    def test_postgres_query_locks_the_run_row(self):
        statement = PostgresRunStore.locked_state_statement(
            'a' * 32,
            datetime(2026, 7, 22, tzinfo=timezone.utc),
        )

        compiled = str(statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={'literal_binds': True},
        ))

        self.assertIn('FOR UPDATE', compiled)
        self.assertIn('brainhacker_runs.run_id', compiled)


class DatabaseSelectionTest(unittest.TestCase):

    def test_vercel_requires_persistent_secret(self):
        environment = {
            'VERCEL': '1',
            'DATABASE_URL': 'postgresql://example.invalid/database',
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(
                    RuntimeError,
                    'BRAIN_GAMES_SECRET_KEY',
            ):
                create_app()

    def test_vercel_requires_database(self):
        environment = {
            'VERCEL': '1',
            'BRAIN_GAMES_SECRET_KEY': 'persistent-test-secret',
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'DATABASE_URL'):
                create_app()

    def test_database_url_selects_durable_stores_and_secure_cookie(self):
        run_store = object()
        account_store = object()
        environment = {
            'VERCEL': '1',
            'DATABASE_URL': 'postgresql://example.invalid/database',
            'BRAIN_GAMES_SECRET_KEY': 'persistent-test-secret',
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch(
                    'brain_games.app.build_database_stores',
                    return_value=(run_store, account_store),
            ) as builder:
                application = create_app()

        builder.assert_called_once_with(environment['DATABASE_URL'])
        self.assertIs(
            run_store,
            application.extensions['brain_games_run_store'],
        )
        self.assertIs(
            account_store,
            application.extensions['brain_games_account_store'],
        )
        self.assertTrue(application.config['SESSION_COOKIE_SECURE'])


if __name__ == '__main__':
    unittest.main()
