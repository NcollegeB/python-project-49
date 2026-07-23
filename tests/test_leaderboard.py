import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from brain_games.leaderboard import Leaderboard, get_default_path


class LeaderboardTest(unittest.TestCase):

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.path = Path(self.temporary_directory.name) / 'scores.json'
        self.leaderboard = Leaderboard(self.path)

    def test_default_path_uses_environment_data_directory(self):
        data_directory = Path(self.temporary_directory.name) / 'custom'
        with mock.patch.dict(
                os.environ,
                {'BRAIN_GAMES_DATA_DIR': str(data_directory)},
        ):
            self.assertEqual(
                get_default_path(),
                data_directory / 'leaderboard.json',
            )

    def test_missing_and_corrupt_files_are_treated_as_empty(self):
        self.assertEqual(self.leaderboard.top(), [])

        self.path.write_text('{not valid JSON', encoding='utf-8')
        self.assertEqual(self.leaderboard.top(), [])

        self.leaderboard.record('Ada', 'Calculator', 4)
        self.assertEqual(self.leaderboard.top()[0]['score'], 4)

    def test_record_keeps_best_case_insensitive_player_and_game(self):
        first = self.leaderboard.record(' Ada ', ' Calculator ', 7)
        lower = self.leaderboard.record('ada', 'calculator', 3)
        higher = self.leaderboard.record('ADA', 'CALCULATOR', 12)

        self.assertEqual(first['score'], 7)
        self.assertEqual(lower, first)
        self.assertEqual(higher['score'], 12)
        self.assertEqual(self.leaderboard.top(), [higher])

        reloaded = Leaderboard(self.path)
        self.assertEqual(reloaded.top(), [higher])

    def test_top_filters_case_insensitively_and_has_deterministic_ties(self):
        self.leaderboard.record('Zoe', 'Prime', 5)
        self.leaderboard.record('Ada', 'Even', 5)
        self.leaderboard.record('Bob', 'prime', 8)
        self.leaderboard.record('Cal', 'GCD', 10)

        top_three = self.leaderboard.top(limit=3)
        self.assertEqual(
            [(entry['player'], entry['score']) for entry in top_three],
            [('Cal', 10), ('Bob', 8), ('Ada', 5)],
        )
        prime_scores = self.leaderboard.top(game='PRIME')
        self.assertEqual(
            [entry['player'] for entry in prime_scores],
            ['Bob', 'Zoe'],
        )
        ada_scores = self.leaderboard.top(player='ADA')
        self.assertEqual(['Ada'], [
            entry['player'] for entry in ada_scores
        ])
        self.assertEqual(self.leaderboard.top(limit=0), [])

    def test_top_can_isolate_a_versioned_game_prefix(self):
        current = self.leaderboard.record('Ada', 'r2:even', 7)
        self.leaderboard.record('Grace', 'even', 99)
        self.leaderboard.record('Lin', 'r1:prime', 98)
        second_current = self.leaderboard.record('Mina', 'R2:prime', 6)

        entries = self.leaderboard.top(game_prefix=' R2: ')

        self.assertEqual([current, second_current], entries)
        self.assertEqual(
            [current],
            self.leaderboard.top(game='r2:EVEN', game_prefix='r2:'),
        )
        with self.assertRaises(TypeError):
            self.leaderboard.top(game_prefix=2)

    def test_record_writes_with_atomic_replace_and_utc_timestamp(self):
        with mock.patch(
                'brain_games.leaderboard.os.replace',
                wraps=os.replace,
        ) as replace:
            entry = self.leaderboard.record('Grace', 'Progression', 9)

        replace.assert_called_once()
        source, destination = replace.call_args.args
        self.assertEqual(Path(source).parent, self.path.parent)
        self.assertEqual(Path(destination), self.path)
        self.assertFalse(Path(source).exists())

        played_at = datetime.fromisoformat(entry['played_at'])
        self.assertEqual(played_at.utcoffset(), timezone.utc.utcoffset(None))
        payload = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(payload['version'], 1)
        self.assertEqual(payload['entries'], [entry])

    def test_invalid_records_are_rejected(self):
        invalid_records = (
            ('', 'Even', 1),
            ('Ada', '', 1),
            ('Ada', 'Even', -1),
            ('Ada', 'Even', True),
        )
        for record in invalid_records:
            with self.subTest(record=record):
                with self.assertRaises(ValueError):
                    self.leaderboard.record(*record)


if __name__ == '__main__':
    unittest.main()
