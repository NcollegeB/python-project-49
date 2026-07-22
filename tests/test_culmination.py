from contextlib import ExitStack
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from brain_games import cli
from brain_games.engine import play_game
from brain_games.engine import run
from brain_games.games import brain_culmination
from brain_games.games import brain_number_memory
from brain_games.games import brain_verbal_memory
from brain_games.games.catalog import CORE_GAMES
from brain_games.leaderboard import Leaderboard


class PreviewAliasRound:
    NAME = 'Preview Alias Round'
    RULES = 'Remember the secret, then answer yes/y.'
    PREVIEW_SECONDS = 0.125
    HIDDEN_QUESTION = 'What was the secret?'
    ANSWER_ALIASES = {'y': 'yes', 'n': 'no'}
    starts = 0
    results = []

    @classmethod
    def reset(cls):
        cls.starts = 0
        cls.results = []

    @classmethod
    def start_session(cls):
        cls.starts += 1

    @classmethod
    def record_result(cls, is_correct):
        cls.results.append(is_correct)

    @staticmethod
    def get_question_and_answer():
        return 'secret question', 'yes'


class PlainRound:
    NAME = 'Plain Round'
    RULES = 'Answer the plain question.'

    @staticmethod
    def get_question_and_answer():
        return 'plain question', 'yes'


def answer_reader(answers):
    iterator = iter(answers)
    return lambda _prompt='': next(iterator)


class CulminationTest(unittest.TestCase):

    def setUp(self):
        PreviewAliasRound.reset()
        brain_culmination.start_session()

    def test_catalog_matches_the_ten_standalone_menu_games(self):
        menu_games = tuple(game for _number, game in cli.GAMES[:-1])

        self.assertEqual('Culmination Test', brain_culmination.NAME)
        self.assertEqual('culmination', brain_culmination.SLUG)
        self.assertEqual('Mixed', brain_culmination.CATEGORY)
        self.assertTrue(brain_culmination.RULES)
        self.assertEqual(10, len(CORE_GAMES))
        self.assertEqual(10, len({game.SLUG for game in CORE_GAMES}))
        self.assertEqual(CORE_GAMES, brain_culmination.SOURCE_GAMES)
        self.assertEqual(CORE_GAMES, menu_games)
        self.assertIs(brain_culmination, cli.GAMES[-1][1])

    def test_shuffled_bag_uses_every_game_before_repeating(self):
        active_games = []
        with patch.object(
                brain_culmination.random,
                'shuffle',
                side_effect=lambda _games: None):
            for _turn in range(len(CORE_GAMES) + 1):
                brain_culmination.get_question_and_answer()
                active_games.append(brain_culmination.get_active_game())

        self.assertEqual(list(CORE_GAMES), active_games[:10])
        self.assertEqual(CORE_GAMES[0], active_games[10])

    def test_new_bag_never_repeats_the_previous_round(self):
        shuffle_calls = 0

        def force_boundary_repeat(games):
            nonlocal shuffle_calls
            shuffle_calls += 1
            if shuffle_calls == 2:
                previous_game = brain_culmination.get_active_game()
                previous_index = games.index(previous_game)
                games[0], games[previous_index] = (
                    games[previous_index],
                    games[0],
                )

        with patch.object(
                brain_culmination.random,
                'shuffle',
                side_effect=force_boundary_repeat):
            for _turn in range(len(CORE_GAMES)):
                brain_culmination.get_question_and_answer()
            previous_game = brain_culmination.get_active_game()
            brain_culmination.get_question_and_answer()

        self.assertIsNot(previous_game, brain_culmination.get_active_game())

    def test_session_start_resets_stateful_source_games(self):
        brain_number_memory.start_session()
        brain_number_memory.record_result(True)
        brain_verbal_memory.start_session()
        brain_verbal_memory.get_question_and_answer()

        brain_culmination.start_session()

        self.assertEqual(1, brain_number_memory.current_digit_count())
        self.assertEqual(0, brain_verbal_memory.seen_word_count())
        self.assertIsNone(brain_culmination.get_active_game())

    def test_active_round_controls_alias_preview_rules_and_result_hook(self):
        output = StringIO()
        waits = []

        with patch.object(
                brain_culmination,
                'SOURCE_GAMES',
                (PreviewAliasRound, PlainRound)), patch.object(
                    brain_culmination.random,
                    'shuffle',
                    side_effect=lambda _games: None):
            result = play_game(
                brain_culmination,
                'Ada',
                input_func=answer_reader([' Y ', 'q']),
                output=output,
                clear=False,
                sleep_func=waits.append,
            )

        rendered = output.getvalue()
        self.assertEqual(1, PreviewAliasRound.starts)
        self.assertEqual([True], PreviewAliasRound.results)
        self.assertEqual([0.125], waits)
        self.assertEqual(1, result.score)
        self.assertEqual(3, result.lives)
        self.assertEqual('culmination', result.game)
        self.assertIn('Culmination Test · Preview Alias Round', rendered)
        self.assertIn(PreviewAliasRound.RULES, rendered)
        self.assertIn('Question: secret question', rendered)
        self.assertIn('Question: What was the secret?', rendered)
        self.assertIn('Culmination Test · Plain Round', rendered)
        self.assertIn('Question: plain question', rendered)
        self.assertIn('Preview Alias Round: Correct!', rendered)

    def test_run_shares_score_and_lives_and_saves_one_mixed_result(self):
        output = StringIO()
        waits = []
        answers = (['yes'] * len(CORE_GAMES)) + ['no', 'no', 'no']

        with TemporaryDirectory() as directory, ExitStack() as stack:
            board = Leaderboard(Path(directory) / 'scores.json')
            for game in CORE_GAMES:
                stack.enter_context(patch.object(
                    game,
                    'get_question_and_answer',
                    return_value=('fixed question', 'yes'),
                ))
            stack.enter_context(patch.object(
                brain_culmination.random,
                'shuffle',
                side_effect=lambda _games: None,
            ))

            result = run(
                brain_culmination,
                player_name='Grace',
                leaderboard=board,
                input_func=answer_reader(answers),
                output=output,
                clear=False,
                sleep_func=waits.append,
            )
            leaders = board.top()

        self.assertEqual(len(CORE_GAMES), result.score)
        self.assertEqual(0, result.lives)
        self.assertEqual('culmination', result.game)
        self.assertEqual(1, len(leaders))
        self.assertEqual('culmination', leaders[0]['game'])
        self.assertEqual(len(CORE_GAMES), leaders[0]['score'])
        self.assertEqual([brain_number_memory.PREVIEW_SECONDS], waits)
        self.assertIn('CULMINATION TEST LEADERS', output.getvalue())


if __name__ == '__main__':
    unittest.main()
