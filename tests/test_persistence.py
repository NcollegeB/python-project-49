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
from brain_games.persistence import scores_table
from brain_games.persistence import serialize_run_state
from brain_games.web_engine import RunStore
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

    def test_missing_run_is_consistent_across_instances(self):
        with self.assertRaises(UnknownRunError):
            self.first.quit('missing')
        with self.assertRaises(UnknownRunError):
            self.second.quit('missing')


class RunSnapshotTest(unittest.TestCase):

    def test_snapshot_is_json_safe_and_restores_private_state(self):
        store = RunStore(random_factory=lambda: random.Random(8))
        run = store.create('verbal-memory', 'Ada')
        state = store._runs[run['run_id']]
        snapshot = serialize_run_state(state)

        encoded = json.dumps(snapshot)
        restored = deserialize_run_state(
            json.loads(encoded),
            random.Random(9),
        )

        self.assertEqual(state.run_id, restored.run_id)
        self.assertEqual(state.round, restored.round)
        self.assertEqual(state.seen_words, restored.seen_words)
        self.assertEqual(state.game_bag, restored.game_bag)

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
