from io import StringIO
import unittest

from brain_games.ui import clear_screen
from brain_games.ui import render_game
from brain_games.ui import render_leaderboard
from brain_games.ui import render_panel


class TerminalUiTest(unittest.TestCase):

    def test_game_panel_contains_live_score_and_three_lives(self):
        output = StringIO()

        render_game(
            'Calculator',
            'Solve it.',
            '2 + 2',
            score=7,
            lives=2,
            feedback='Correct!',
            output=output,
        )

        text = output.getvalue()
        self.assertIn('Score: 7', text)
        self.assertIn('Lives: 2/3', text)
        self.assertIn('♥♥♡', text)

    def test_non_terminal_output_is_not_cleared(self):
        output = StringIO()

        self.assertFalse(clear_screen(output))
        self.assertEqual('', output.getvalue())

    def test_panels_sanitise_control_characters(self):
        output = StringIO()
        render_panel('Title\033[31m', ['hello\nworld'], output)
        self.assertNotIn('\033', output.getvalue())
        self.assertIn('hello world', output.getvalue())

    def test_empty_leaderboard_has_a_helpful_message(self):
        output = StringIO()
        render_leaderboard([], output=output)
        self.assertIn('No scores yet.', output.getvalue())

    def test_leaderboard_uses_polished_game_names(self):
        output = StringIO()
        render_leaderboard(
            [
                {'player': 'Ada', 'game': 'calc', 'score': 9},
                {'player': 'Grace', 'game': 'gcd', 'score': 7},
                {'player': 'Lin', 'game': 'culmination', 'score': 11},
            ],
            output=output,
        )
        self.assertIn('Calculator', output.getvalue())
        self.assertIn('GCD', output.getvalue())
        self.assertIn('Culmination', output.getvalue())


if __name__ == '__main__':
    unittest.main()
