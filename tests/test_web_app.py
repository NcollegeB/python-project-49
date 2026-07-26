import importlib
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from brain_games import app as app_module
from brain_games.app import CSP
from brain_games.app import create_app
from brain_games.games.catalog import CORE_GAMES
from brain_games.leaderboard import Leaderboard
from brain_games.web_engine import RunStore


FORBIDDEN_ANSWER_KEYS = {
    'answer',
    'correct_answer',
    'expected_answer',
    'is_prime',
    'matches',
    'mismatch_index',
    'mismatch_kind',
    'target_index',
}


def nested_keys(value):
    """Return every dictionary key in a JSON-compatible value."""
    if isinstance(value, dict):
        keys = set(value)
        for child in value.values():
            keys.update(nested_keys(child))
        return keys
    if isinstance(value, list):
        keys = set()
        for child in value:
            keys.update(nested_keys(child))
        return keys
    return set()


class WebAppTest(unittest.TestCase):

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        leaderboard = Leaderboard(
            Path(self.directory.name) / 'leaderboard.json',
        )
        self.store = RunStore(leaderboard=leaderboard)
        application = create_app(
            {'TESTING': True},
            run_store=self.store,
        )
        self.client = application.test_client()

    def create_even_run(self, player='Ada'):
        response = self.client.post('/api/runs', json={
            'game': 'even',
            'player': player,
        })
        self.assertEqual(201, response.status_code)
        return response.get_json()

    @staticmethod
    def even_alias(round_payload):
        number = int(round_payload['data']['number'])
        return 'y' if number % 2 == 0 else 'n'

    def test_module_import_and_health_need_no_environment(self):
        with patch.dict(os.environ, {}, clear=True):
            reloaded = importlib.reload(app_module)

        self.assertIsNotNone(reloaded.app)
        response = self.client.get('/healthz')
        self.assertEqual(200, response.status_code)
        self.assertEqual({'status': 'ok'}, response.get_json())

    def test_index_and_play_route_use_only_local_assets(self):
        response = self.client.get('/')
        play_response = self.client.get('/play/even')
        unknown_response = self.client.get('/play/not-a-game')
        document = response.get_data(as_text=True)

        self.assertEqual(200, response.status_code)
        self.assertEqual(200, play_response.status_code)
        self.assertEqual(404, unknown_response.status_code)
        self.assertIn('/static/main.css', document)
        self.assertIn('/static/app.js', document)
        self.assertIn('/static/theme.js', document)
        self.assertIn('id="themeSelect"', document)
        self.assertIn('href="/player"', document)
        self.assertIn('value="dark"', document)
        self.assertIn('value="grey"', document)
        self.assertIn('value="high-contrast"', document)
        self.assertNotIn('http://', document)
        self.assertNotIn('https://', document)
        self.assertEqual('DENY', response.headers['X-Frame-Options'])
        self.assertIn("default-src 'self'", response.headers[
            'Content-Security-Policy'
        ])
        self.assertNotIn("'unsafe-inline'", response.headers[
            'Content-Security-Policy'
        ])

    def test_adsense_side_rails_are_opt_in_and_game_page_only(self):
        publisher_id = 'ca-pub-1234567890123456'
        application = create_app(
            {
                'ADSENSE_CLIENT': publisher_id,
                'TESTING': True,
            },
            run_store=self.store,
        )
        client = application.test_client()

        game_page = client.get('/')
        game_document = game_page.get_data(as_text=True)
        direct_game = client.get('/play/even')
        privacy_page = client.get('/privacy')
        privacy_document = privacy_page.get_data(as_text=True)
        ads_txt = client.get('/ads.txt')

        self.assertIn(
            'pagead2.googlesyndication.com/pagead/js/adsbygoogle.js'
            '?client={}'.format(publisher_id),
            game_document,
        )
        self.assertEqual(1, game_document.count('adsbygoogle.js'))
        self.assertIn('google-side-rail-overlap="false"', game_document)
        script_nonces = re.findall(
            r'<script\b[^>]*\bnonce="([^"]+)"',
            game_document,
        )
        self.assertEqual(
            len(re.findall(r'<script\b', game_document)),
            len(script_nonces),
        )
        self.assertGreaterEqual(len(script_nonces), 4)
        self.assertEqual(1, len(set(script_nonces)))
        nonce = script_nonces[0]
        self.assertIn(
            "'nonce-{}'".format(nonce),
            game_page.headers['Content-Security-Policy'],
        )
        self.assertIn("'strict-dynamic'", game_page.headers[
            'Content-Security-Policy'
        ])
        self.assertIn("'unsafe-eval'", game_page.headers[
            'Content-Security-Policy'
        ])
        self.assertEqual(
            'strict-origin-when-cross-origin',
            game_page.headers['Referrer-Policy'],
        )
        self.assertIn('adsbygoogle.js', direct_game.get_data(as_text=True))
        self.assertIn("'strict-dynamic'", direct_game.headers[
            'Content-Security-Policy'
        ])
        self.assertIn('How BrainHacker uses data', privacy_document)
        self.assertIn('Google-certified vendors', privacy_document)
        self.assertIn('adssettings.google.com', privacy_document)
        self.assertIn('optout.aboutads.info', privacy_document)
        self.assertEqual(200, privacy_page.status_code)
        for path in (
            '/login',
            '/register',
            '/stats',
            '/player',
            '/privacy',
            '/api/games',
            '/healthz',
            '/play/not-a-game',
        ):
            response = client.get(path)
            self.assertNotIn(
                'adsbygoogle.js',
                response.get_data(as_text=True),
                path,
            )
            self.assertEqual(
                CSP,
                response.headers['Content-Security-Policy'],
                path,
            )
            self.assertEqual(
                'no-referrer',
                response.headers['Referrer-Policy'],
                path,
            )
        self.assertEqual(200, ads_txt.status_code)
        self.assertEqual(
            'google.com, pub-1234567890123456, DIRECT, '
            'f08c47fec0942fa0\n',
            ads_txt.get_data(as_text=True),
        )

    def test_invalid_adsense_client_is_rejected(self):
        with self.assertRaisesRegex(
            RuntimeError,
            'ca-pub- followed by 16 digits',
        ):
            create_app(
                {
                    'ADSENSE_CLIENT': 'publisher-id',
                    'TESTING': True,
                },
                run_store=self.store,
            )

    def test_ads_txt_is_absent_when_ads_are_disabled(self):
        self.assertEqual(404, self.client.get('/ads.txt').status_code)

    def test_catalog_has_all_games_without_private_answers(self):
        response = self.client.get('/api/games')
        payload = response.get_json()
        games = payload['games']
        expected_count = len(CORE_GAMES) + 1

        self.assertEqual(200, response.status_code)
        self.assertEqual(expected_count, len(games))
        self.assertEqual(
            expected_count,
            len({game['slug'] for game in games}),
        )
        self.assertIn('culmination', {game['slug'] for game in games})
        self.assertFalse(FORBIDDEN_ANSWER_KEYS & nested_keys(payload))
        self.assertEqual('no-store', response.headers['Cache-Control'])

    def test_run_lifecycle_accepts_short_alias_and_rejects_stale_round(self):
        started = self.create_even_run()
        first_round = started['round']

        self.assertEqual(3, started['lives'])
        self.assertEqual(0, started['score'])
        self.assertFalse(started['ended'])
        self.assertFalse(FORBIDDEN_ANSWER_KEYS & nested_keys(started))

        response = self.client.post(
            '/api/runs/{}/answers'.format(started['run_id']),
            json={
                'round_id': first_round['round_id'],
                'answer': self.even_alias(first_round),
            },
        )
        answered = response.get_json()

        self.assertEqual(200, response.status_code)
        self.assertTrue(answered['result']['correct'])
        self.assertEqual(1, answered['score'])
        self.assertEqual(3, answered['lives'])
        self.assertTrue(answered['result']['review']['explanation'])
        self.assertNotIn('review', answered['round'])
        self.assertNotEqual(
            first_round['round_id'],
            answered['round']['round_id'],
        )
        self.assertFalse(
            FORBIDDEN_ANSWER_KEYS & nested_keys(answered['round'])
        )

        stale = self.client.post(
            '/api/runs/{}/answers'.format(started['run_id']),
            json={
                'round_id': first_round['round_id'],
                'answer': self.even_alias(first_round),
            },
        )
        self.assertEqual(409, stale.status_code)
        self.assertEqual('stale_round', stale.get_json()['error'])

    def test_invalid_answer_does_not_advance_the_run(self):
        started = self.create_even_run()
        first_round = started['round']
        answer_url = '/api/runs/{}/answers'.format(started['run_id'])

        invalid = self.client.post(answer_url, json={
            'round_id': first_round['round_id'],
            'answer': 'perhaps',
        })
        valid = self.client.post(answer_url, json={
            'round_id': first_round['round_id'],
            'answer': self.even_alias(first_round),
        })

        self.assertEqual(400, invalid.status_code)
        self.assertEqual('invalid_answer', invalid.get_json()['error'])
        self.assertEqual(200, valid.status_code)
        self.assertTrue(valid.get_json()['result']['correct'])

    def test_quit_records_score_and_exposes_filtered_leaderboard(self):
        started = self.create_even_run(player='Grace')
        first_round = started['round']
        answer_url = '/api/runs/{}/answers'.format(started['run_id'])
        self.client.post(answer_url, json={
            'round_id': first_round['round_id'],
            'answer': self.even_alias(first_round),
        })

        response = self.client.post(
            '/api/runs/{}/quit'.format(started['run_id']),
        )
        quit_payload = response.get_json()
        leaders = self.client.get(
            '/api/leaderboard?game=even&limit=5',
        ).get_json()['entries']
        player_leaders = self.client.get(
            '/api/leaderboard?player=grace&limit=100',
        ).get_json()['entries']

        self.assertEqual(200, response.status_code)
        self.assertTrue(quit_payload['ended'])
        self.assertTrue(quit_payload['quit_early'])
        self.assertIsNone(quit_payload['round'])
        self.assertEqual(1, quit_payload['score'])
        self.assertEqual(1, len(leaders))
        self.assertEqual('Grace', leaders[0]['player'])
        self.assertEqual('even', leaders[0]['game'])
        self.assertEqual(1, leaders[0]['score'])
        self.assertEqual(leaders, player_leaders)

        ended = self.client.post(answer_url, json={
            'round_id': first_round['round_id'],
            'answer': self.even_alias(first_round),
        })
        self.assertEqual(409, ended.status_code)
        self.assertEqual('run_ended', ended.get_json()['error'])

    def test_timing_modes_keep_self_paced_runs_out_of_rankings(self):
        standard = self.client.post('/api/runs', json={
            'game': 'even',
            'player': 'Standard',
            'timing_mode': 'standard',
        }).get_json()
        self_paced = self.client.post('/api/runs', json={
            'game': 'even',
            'player': 'SelfPaced',
            'timing_mode': 'self-paced',
        }).get_json()

        self.assertTrue(standard['ranked'])
        self.assertFalse(self_paced['ranked'])
        self.assertEqual('standard', standard['timing_mode'])
        self.assertEqual('self-paced', self_paced['timing_mode'])
        self.assertEqual(0, self_paced['round']['time_limit_ms'])

        for run in (standard, self_paced):
            self.client.post(
                '/api/runs/{}/quit'.format(run['run_id']),
            )

        entries = self.client.get(
            '/api/leaderboard?game=even&limit=10',
        ).get_json()['entries']
        self.assertEqual(['Standard'], [
            entry['player'] for entry in entries
        ])

    def test_start_level_creates_an_unranked_practice_run(self):
        response = self.client.post('/api/runs', json={
            'game': 'direction-focus',
            'player': 'Practice',
            'timing_mode': 'standard',
            'start_level': 9,
        })
        practice = response.get_json()

        self.assertEqual(201, response.status_code)
        self.assertEqual(9, practice['level'])
        self.assertEqual(9, practice['round']['level'])
        self.assertEqual(9, practice['round']['source_level'])
        self.assertEqual('Spatial', practice['round']['difficulty_label'])
        self.assertFalse(practice['ranked'])

        self.client.post(
            '/api/runs/{}/quit'.format(practice['run_id']),
        )
        entries = self.client.get(
            '/api/leaderboard?game=direction-focus&limit=10',
        ).get_json()['entries']
        self.assertEqual([], entries)

    def test_start_level_request_validation_is_game_specific(self):
        cases = (
            ('even', None),
            ('even', True),
            ('even', '2'),
            ('even', 0),
            ('even', 6),
            ('direction-focus', 11),
        )

        for game, start_level in cases:
            with self.subTest(game=game, start_level=start_level):
                response = self.client.post('/api/runs', json={
                    'game': game,
                    'player': 'Practice',
                    'start_level': start_level,
                })
                self.assertEqual(400, response.status_code)
                self.assertEqual(
                    'invalid_request',
                    response.get_json()['error'],
                )

    def test_leaderboard_hides_scores_from_the_previous_ruleset(self):
        self.store._leaderboard.record('Legacy', 'even', 999)

        entries = self.client.get(
            '/api/leaderboard?game=even&limit=10',
        ).get_json()['entries']

        self.assertEqual([], entries)

    def test_unknown_resources_and_bad_requests_are_controlled_json(self):
        unknown_game = self.client.post('/api/runs', json={
            'game': 'not-a-game',
            'player': 'Ada',
        })
        unknown_run = self.client.post('/api/runs/missing/quit')
        missing_field = self.client.post('/api/runs', json={
            'game': 'even',
        })
        bad_json = self.client.post(
            '/api/runs',
            data='not JSON',
            content_type='application/json',
        )
        bad_limit = self.client.get('/api/leaderboard?limit=all')
        bad_player = self.client.get('/api/leaderboard?player=')
        bad_timing = self.client.post('/api/runs', json={
            'game': 'even',
            'player': 'Ada',
            'timing_mode': 'slowest',
        })
        malformed_timing = self.client.post('/api/runs', json={
            'game': 'even',
            'player': 'Ada',
            'timing_mode': [],
        })
        removed_timing = self.client.post('/api/runs', json={
            'game': 'even',
            'player': 'Ada',
            'timing_mode': 'relaxed',
        })
        oversized = self.client.post(
            '/api/runs',
            data='x' * (17 * 1024),
            content_type='application/json',
        )

        expected = (
            (unknown_game, 404, 'unknown_game'),
            (unknown_run, 404, 'unknown_run'),
            (missing_field, 400, 'invalid_request'),
            (bad_json, 400, 'invalid_request'),
            (bad_limit, 400, 'invalid_request'),
            (bad_player, 400, 'invalid_request'),
            (bad_timing, 400, 'invalid_request'),
            (malformed_timing, 400, 'invalid_request'),
            (removed_timing, 400, 'invalid_request'),
            (oversized, 413, 'request_too_large'),
        )
        for response, status, error_code in expected:
            with self.subTest(error=error_code):
                self.assertEqual(status, response.status_code)
                self.assertTrue(response.is_json)
                self.assertEqual(error_code, response.get_json()['error'])


if __name__ == '__main__':
    unittest.main()
