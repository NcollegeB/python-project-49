from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from brain_games import cli
from brain_games.leaderboard import Leaderboard


class MenuGame:
    NAME = 'Menu Test Game'
    SLUG = 'menu-test'
    RULES = 'Always answer yes.'

    @staticmethod
    def get_question_and_answer():
        return 'Ready?', 'yes'


def answer_reader(answers):
    iterator = iter(answers)
    return lambda _prompt='': next(iterator)


class CliTest(unittest.TestCase):

    def test_menu_launches_game_returns_and_quits(self):
        responses = ['Nathan', '1', 'yes', 'no', 'no', 'no', '', '7']
        output = StringIO()
        with TemporaryDirectory() as directory:
            board = Leaderboard(Path(directory) / 'scores.json')
            with patch.object(cli, 'GAMES', (('1', MenuGame),)):
                cli.main(
                    input_func=answer_reader(responses),
                    output=output,
                    leaderboard=board,
                    clear=False,
                )

            leaders = board.top(game='menu-test')
            self.assertEqual(1, leaders[0]['score'])

        text = output.getvalue()
        self.assertIn('BRAIN GAMES ARCADE', text)
        self.assertIn('Menu Test Game', text)
        self.assertIn('THANKS FOR PLAYING', text)

    def test_invalid_choice_and_leaderboard_are_available(self):
        responses = ['Ada', 'wrong', '6', '', 'q']
        output = StringIO()
        with TemporaryDirectory() as directory:
            board = Leaderboard(Path(directory) / 'scores.json')
            cli.main(
                input_func=answer_reader(responses),
                output=output,
                leaderboard=board,
                clear=False,
            )

        text = output.getvalue()
        self.assertIn("Choose 1-7, or enter 'q' to quit.", text)
        self.assertIn('ALL-GAME LEADERBOARD', text)


if __name__ == '__main__':
    unittest.main()
