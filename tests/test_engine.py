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
    questions_asked = 0

    @classmethod
    def reset(cls):
        cls.questions_asked = 0

    @classmethod
    def get_question_and_answer(cls):
        cls.questions_asked += 1
        return 'Question {}'.format(cls.questions_asked), 'yes'


def answer_reader(answers):
    iterator = iter(answers)
    return lambda _prompt='': next(iterator)


class EngineTest(unittest.TestCase):

    def setUp(self):
        SequenceGame.reset()

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

    def test_quit_returns_current_score_and_remaining_lives(self):
        result = play_game(
            SequenceGame,
            'Grace',
            input_func=answer_reader(['YES', ' yes ', 'q']),
            output=StringIO(),
            clear=False,
        )

        self.assertEqual(2, result.score)
        self.assertEqual(3, result.lives)
        self.assertTrue(result.quit_early)

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
