import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from brain_games.accounts import AccountStore
from brain_games.app import create_app
from brain_games.leaderboard import Leaderboard
from brain_games.web_engine import RunStore


CSRF_PATTERN = re.compile(
    r'name="csrf_token"[^>]*value="([^"]+)"'
    r'|value="([^"]+)"[^>]*name="csrf_token"',
)


def csrf_token(response):
    match = CSRF_PATTERN.search(response.get_data(as_text=True))
    if match is None:
        raise AssertionError('response did not contain a CSRF token')
    return match.group(1) or match.group(2)


class AuthAndStatisticsTest(unittest.TestCase):

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        directory = Path(self.temporary_directory.name)
        self.accounts = AccountStore(directory / 'accounts.json')
        leaderboard = Leaderboard(directory / 'leaderboard.json')
        self.store = RunStore(leaderboard=leaderboard)
        self.application = create_app(
            {
                'TESTING': True,
                'SECRET_KEY': 'test-only-secret',
            },
            run_store=self.store,
            account_store=self.accounts,
        )
        self.client = self.application.test_client()

    def register(self, username='Ada', password='correct-horse'):
        token = csrf_token(self.client.get('/register'))
        return self.client.post('/register', data={
            'csrf_token': token,
            'username': username,
            'password': password,
            'confirm_password': password,
        })

    def test_static_benchmark_api_is_complete_and_score_aware(self):
        catalog = self.client.get('/api/benchmarks')
        scored = self.client.get('/api/benchmarks/gcd?score=1')
        invalid = self.client.get('/api/benchmarks/gcd?score=one')
        negative = self.client.get('/api/benchmarks/gcd?score=-1')
        unknown = self.client.get('/api/benchmarks/missing?score=1')

        benchmarks = catalog.get_json()['benchmarks']
        self.assertEqual(11, len(benchmarks))
        self.assertEqual('even', benchmarks[0]['slug'])
        self.assertIn(
            'not measured population',
            benchmarks[0]['disclaimer'],
        )
        self.assertEqual(13, scored.get_json()['percentile'])
        self.assertEqual(13, scored.get_json()['rank_out_of_100'])
        self.assertEqual(400, invalid.status_code)
        self.assertEqual(400, negative.status_code)
        self.assertEqual(404, unknown.status_code)

    def test_register_signs_in_and_server_owns_score_identity(self):
        response = self.register('Ada_1')

        self.assertEqual(302, response.status_code)
        self.assertTrue(response.headers['Location'].endswith('/stats'))
        cookie = response.headers['Set-Cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Lax', cookie)
        self.assertEqual({
            'authenticated': True,
            'user': self.accounts.get('ada_1'),
        }, self.client.get('/api/me').get_json())

        run_response = self.client.post('/api/runs', json={
            'game': 'even',
            'player': 'SomeoneElse',
        })
        run = run_response.get_json()
        self.assertEqual(201, run_response.status_code)
        self.assertEqual('ada_1', run['player'])
        self.client.post('/api/runs/{}/quit'.format(run['run_id']))
        account = self.accounts.get('ada_1')
        stored = self.store.leaders(
            player='account:{}'.format(account['account_id']),
            limit=100,
        )

        stats = self.client.get('/stats').get_data(as_text=True)
        self.assertEqual(1, len(stored))
        self.assertEqual(0, stored[0]['score'])
        self.assertIn('ada_1', stats)
        self.assertIn('Even or Odd', stats)
        self.assertIn('BrainHacker benchmark', stats)
        self.assertIn('1st percentile', stats)

    def test_registered_username_cannot_be_used_anonymously(self):
        self.accounts.create('Reserved_User', 'correct-horse')

        response = self.client.post('/api/runs', json={
            'game': 'even',
            'player': 'RESERVED_USER',
        })

        self.assertEqual(403, response.status_code)
        self.assertEqual('reserved_player', response.get_json()['error'])

    def test_account_never_inherits_a_pre_registration_anonymous_score(self):
        self.store._leaderboard.record('Future_User', 'even', 999)
        self.store._leaderboard.record(
            'account:Future_User',
            'prime',
            998,
        )
        registered = self.register('Future_User')

        self.assertEqual(302, registered.status_code)
        stats = self.client.get('/stats').get_data(as_text=True)
        filtered = self.client.get(
            '/api/leaderboard?player=future_user&limit=100',
        ).get_json()['entries']
        public = self.client.get(
            '/api/leaderboard?limit=100',
        ).get_json()['entries']

        self.assertNotIn('999', stats)
        self.assertNotIn('998', stats)
        self.assertEqual([], filtered)
        self.assertEqual([], public)

        anonymous_client = self.application.test_client()
        reserved = anonymous_client.post('/api/runs', json={
            'game': 'even',
            'player': 'ACCOUNT:future_user',
        })
        self.assertEqual(403, reserved.status_code)

    def test_public_leaderboard_batches_account_name_resolution(self):
        ada = self.accounts.create('Ada_1', 'correct-horse')
        self.accounts.create('Grace', 'correct-horse')
        self.store._leaderboard.record(
            'account:{}'.format(ada['account_id']),
            'even',
            10,
        )
        self.store._leaderboard.record('GRACE', 'even', 9)
        self.store._leaderboard.record('Visitor', 'even', 8)

        with mock.patch.object(
                self.accounts,
                'lookup_many',
                wraps=self.accounts.lookup_many,
        ) as lookup_many:
            response = self.client.get('/api/leaderboard?limit=100')

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, lookup_many.call_count)
        self.assertEqual(
            ['ada_1', 'Visitor'],
            [
                entry['player']
                for entry in response.get_json()['entries']
            ],
        )

    def test_login_logout_and_invalid_credentials(self):
        self.accounts.create('Grace', 'correct-horse')
        token = csrf_token(self.client.get('/login'))
        rejected = self.client.post('/login', data={
            'csrf_token': token,
            'username': 'Grace',
            'password': 'wrong-password',
        })
        accepted = self.client.post('/login', data={
            'csrf_token': token,
            'username': 'GRACE',
            'password': 'correct-horse',
        })

        self.assertEqual(401, rejected.status_code)
        self.assertIn('do not match', rejected.get_data(as_text=True))
        self.assertEqual(302, accepted.status_code)
        self.assertTrue(self.client.get('/api/me').get_json()['authenticated'])

        logout_token = csrf_token(self.client.get('/stats'))
        logged_out = self.client.post('/logout', data={
            'csrf_token': logout_token,
        })
        self.assertEqual(302, logged_out.status_code)
        self.assertFalse(
            self.client.get('/api/me').get_json()['authenticated'],
        )

    def test_auth_forms_require_csrf_and_validate_registration(self):
        expired = self.client.post('/register', data={
            'username': 'Ada',
            'password': 'correct-horse',
            'confirm_password': 'correct-horse',
        })
        token = csrf_token(self.client.get('/register'))
        invalid = self.client.post('/register', data={
            'csrf_token': token,
            'username': 'bad name',
            'password': 'short',
            'confirm_password': 'short',
        })
        mismatch = self.client.post('/register', data={
            'csrf_token': token,
            'username': 'Valid_User',
            'password': 'correct-horse',
            'confirm_password': 'different-horse',
        })

        self.assertEqual(400, expired.status_code)
        self.assertEqual(400, invalid.status_code)
        self.assertEqual(400, mismatch.status_code)
        self.assertIn(
            'confirmation does not match',
            mismatch.get_data(as_text=True),
        )
        self.assertIsNone(self.accounts.get('Ada'))

    def test_anonymous_stats_use_only_the_fixed_reference_table(self):
        response = self.client.get('/stats')
        document = response.get_data(as_text=True)

        self.assertEqual(200, response.status_code)
        self.assertIn('BrainHacker benchmark', document)
        self.assertIn('not measured population data', document)
        self.assertIn('27.0', document)
        self.assertEqual('no-store', response.headers['Cache-Control'])

    def test_paper_test_branding_replaces_the_old_visual_system(self):
        document = self.client.get('/').get_data(as_text=True)
        stylesheet_path = Path(__file__).parents[1].joinpath(
            'brain_games',
            'static',
            'main.css',
        )
        stylesheet = stylesheet_path.read_text(encoding='utf-8')

        self.assertIn('BrainHacker', document)
        self.assertIn('Short games.', document)
        self.assertIn('resultAverage', document)
        self.assertIn('resultPercentile', document)
        self.assertIn('resultRank', document)
        self.assertNotIn('Night Arcade', document)
        self.assertNotIn('effectsCanvas', document)
        self.assertNotIn('gradient', stylesheet)

    def test_theme_control_is_shared_by_every_page(self):
        for path in ('/', '/stats', '/login', '/register'):
            with self.subTest(path=path):
                response = self.client.get(path)
                document = response.get_data(as_text=True)

                self.assertEqual(200, response.status_code)
                self.assertIn('/static/theme.js', document)
                self.assertIn('id="themeSelect"', document)
                self.assertIn('value="light"', document)
                self.assertIn('value="dark"', document)
                self.assertIn('value="grey"', document)
                self.assertIn('value="high-contrast"', document)

        stylesheet_path = Path(__file__).parents[1].joinpath(
            'brain_games',
            'static',
            'main.css',
        )
        stylesheet = stylesheet_path.read_text(encoding='utf-8')
        self.assertIn(':root[data-theme="dark"]', stylesheet)
        self.assertIn(':root[data-theme="grey"]', stylesheet)
        self.assertIn(':root[data-theme="high-contrast"]', stylesheet)

    def test_secure_cookie_mode_requires_a_persistent_secret(self):
        environment = {
            'BRAIN_GAMES_SECURE_COOKIES': '1',
            'BRAIN_GAMES_SECRET_KEY': '',
        }
        with mock.patch.dict('os.environ', environment, clear=True):
            with self.assertRaisesRegex(
                    RuntimeError,
                    'BRAIN_GAMES_SECRET_KEY',
            ):
                create_app()


if __name__ == '__main__':
    unittest.main()
