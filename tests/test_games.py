import unittest

from brain_games.games import brain_calc
from brain_games.games import brain_even
from brain_games.games import brain_gcd
from brain_games.games import brain_prime
from brain_games.games import brain_progression


GAMES = (
    brain_calc,
    brain_even,
    brain_gcd,
    brain_prime,
    brain_progression,
)


class GameContractTest(unittest.TestCase):

    def test_every_game_has_metadata_and_generates_an_answer(self):
        for game in GAMES:
            with self.subTest(game=game.SLUG):
                question, answer = game.get_question_and_answer()
                self.assertTrue(game.NAME)
                self.assertTrue(game.RULES)
                self.assertTrue(str(question))
                self.assertTrue(str(answer))


if __name__ == '__main__':
    unittest.main()
