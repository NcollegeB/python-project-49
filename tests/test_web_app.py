import importlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from brain_games import app as app_module
from brain_games.app import create_app
from brain_games.leaderboard import Leaderboard
from brain_games.web_engine import RunStore


FORBIDDEN_ANSWER_KEYS = {
    'answer',
    'correct_answer',
    'expected_answer',
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

    def test_catalog_has_all_games_without_private_answers(self):
        response = self.client.get('/api/games')
        payload = response.get_json()
        games = payload['games']

        self.assertEqual(200, response.status_code)
        self.assertEqual(11, len(games))
        self.assertEqual(11, len({game['slug'] for game in games}))
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
            (oversized, 413, 'request_too_large'),
        )
        for response, status, error_code in expected:
            with self.subTest(error=error_code):
                self.assertEqual(status, response.status_code)
                self.assertTrue(response.is_json)
                self.assertEqual(error_code, response.get_json()['error'])


if __name__ == '__main__':
    unittest.main()
