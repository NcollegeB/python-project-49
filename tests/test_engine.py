from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from brain_games.engine import play_game
from brain_games.engine import run
from brain_games.leaderboard import Leaderboard


class SequenceGame:
    NAME = 'Sequence Test'
    SLUG = 'sequence-test'
    RULES = 'Say yes.'
    ANSWER_ALIASES = {'y': 'yes', 'n': 'no'}
    questions_asked = 0

    @classmethod
    def reset(cls):
        cls.questions_asked = 0

    @classmethod
    def get_question_and_answer(cls):
        cls.questions_asked += 1
        return 'Question {}'.format(cls.questions_asked), 'yes'


class AliasSequenceGame:
    NAME = 'Alias Sequence Test'
    SLUG = 'alias-sequence-test'
    RULES = 'Use a short answer.'
    ANSWER_ALIASES = {
        'y': 'yes',
        'n': 'no',
        'u': 'up',
        'd': 'down',
        'l': 'left',
        'r': 'right',
    }
    expected_answers = ('yes', 'no', 'up', 'down', 'left', 'right')
    questions_asked = 0

    @classmethod
    def reset(cls):
        cls.questions_asked = 0

    @classmethod
    def get_question_and_answer(cls):
        index = cls.questions_asked % len(cls.expected_answers)
        cls.questions_asked += 1
        return 'Alias question', cls.expected_answers[index]


class PlainYesGame:
    NAME = 'Plain Yes Test'
    SLUG = 'plain-yes-test'
    RULES = 'Say yes.'

    @staticmethod
    def get_question_and_answer():
        return 'Ready?', 'yes'


class PreviewGame:
    NAME = 'Preview Test'
    SLUG = 'preview-test'
    RULES = 'Remember the number.'
    PREVIEW_SECONDS = 0.25
    HIDDEN_QUESTION = 'What was hidden?'

    @staticmethod
    def get_question_and_answer():
        return '7391', '7391'


class HookGame:
    NAME = 'Hook Test'
    SLUG = 'hook-test'
    RULES = 'Say yes.'
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
        return 'Ready?', 'yes'


def answer_reader(answers):
    iterator = iter(answers)
    return lambda _prompt='': next(iterator)


class EngineTest(unittest.TestCase):

    def setUp(self):
        SequenceGame.reset()
        AliasSequenceGame.reset()
        HookGame.reset()

    def test_play_continues_past_three_correct_until_three_misses(self):
        output = StringIO()
        answers = ['yes', 'yes', 'yes', 'yes', 'no', 'no', 'no']

        result = play_game(
            SequenceGame,
            'Ada',
            input_func=answer_reader(answers),
            output=output,
            clear=False,
        )

        self.assertEqual(4, result.score)
        self.assertEqual(0, result.lives)
        self.assertFalse(result.quit_early)
        self.assertEqual(7, SequenceGame.questions_asked)
        self.assertIn('Final score: 4', output.getvalue())

    def test_short_aliases_are_case_insensitive(self):
        result = play_game(
            SequenceGame,
            'Grace',
            input_func=answer_reader(['y', 'YES', ' yes ', 'q']),
            output=StringIO(),
            clear=False,
        )

        self.assertEqual(3, result.score)
        self.assertEqual(3, result.lives)
        self.assertTrue(result.quit_early)

    def test_all_short_aliases_are_normalized(self):
        result = play_game(
            AliasSequenceGame,
            'Ari',
            input_func=answer_reader([
                ' Y ',
                'n',
                'U',
                'd',
                'l',
                'R',
                'q',
            ]),
            output=StringIO(),
            clear=False,
        )

        self.assertEqual(6, result.score)
        self.assertEqual(3, result.lives)
        self.assertTrue(result.quit_early)

    def test_aliases_are_scoped_to_their_game(self):
        result = play_game(
            PlainYesGame,
            'Sam',
            input_func=answer_reader(['y', 'q']),
            output=StringIO(),
            clear=False,
        )

        self.assertEqual(0, result.score)
        self.assertEqual(2, result.lives)

    def test_preview_renders_then_hides_before_input(self):
        output = StringIO()
        waits = []

        play_game(
            PreviewGame,
            'Mina',
            input_func=answer_reader(['q']),
            output=output,
            clear=False,
            sleep_func=waits.append,
        )

        rendered = output.getvalue()
        self.assertEqual([0.25], waits)
        self.assertIn('Question: 7391', rendered)
        self.assertIn('Question: What was hidden?', rendered)
        self.assertLess(
            rendered.index('Question: 7391'),
            rendered.index('Question: What was hidden?'),
        )

    def test_optional_session_hooks_receive_answer_results(self):
        result = play_game(
            HookGame,
            'Lee',
            input_func=answer_reader(['yes', 'no', 'q']),
            output=StringIO(),
            clear=False,
        )

        self.assertEqual(1, HookGame.starts)
        self.assertEqual([True, False], HookGame.results)
        self.assertEqual(1, result.score)
        self.assertEqual(2, result.lives)

    def test_non_preview_game_does_not_sleep(self):
        def fail_if_called(_seconds):
            self.fail('A game without a preview should not sleep.')

        play_game(
            PlainYesGame,
            'Kai',
            input_func=answer_reader(['q']),
            output=StringIO(),
            clear=False,
            sleep_func=fail_if_called,
        )

    def test_run_persists_the_score(self):
        with TemporaryDirectory() as directory:
            board = Leaderboard(Path(directory) / 'scores.json')
            result = run(
                SequenceGame,
                player_name='Lin',
                leaderboard=board,
                input_func=answer_reader(['yes', 'no', 'no', 'no']),
                output=StringIO(),
                clear=False,
            )

            leaders = board.top(game='sequence-test')
            self.assertEqual(1, result.score)
            self.assertEqual(1, len(leaders))
            self.assertEqual('Lin', leaders[0]['player'])
            self.assertEqual(1, leaders[0]['score'])


if __name__ == '__main__':
    unittest.main()
