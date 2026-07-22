from collections import Counter
import unittest
from unittest.mock import patch

from brain_games.games import brain_direction_focus
from brain_games.games import brain_number_memory
from brain_games.games import brain_symbol_match
from brain_games.games import brain_verbal_memory
from brain_games.games import brain_word_scramble


NEW_GAMES = (
    brain_number_memory,
    brain_verbal_memory,
    brain_direction_focus,
    brain_symbol_match,
    brain_word_scramble,
)


class NewGameContractTest(unittest.TestCase):

    def test_every_new_game_has_metadata_and_generates_an_answer(self):
        for game in NEW_GAMES:
            with self.subTest(game=game.SLUG):
                if hasattr(game, 'start_session'):
                    game.start_session()
                question, answer = game.get_question_and_answer()

                self.assertTrue(game.NAME)
                self.assertTrue(game.SLUG)
                self.assertTrue(game.CATEGORY)
                self.assertTrue(game.RULES)
                self.assertTrue(str(question))
                self.assertTrue(str(answer))


class NumberMemoryTest(unittest.TestCase):

    def setUp(self):
        brain_number_memory.start_session()

    def test_question_is_answer_and_exposes_preview_metadata(self):
        question, answer = brain_number_memory.get_question_and_answer()

        self.assertEqual(question, answer)
        self.assertEqual(1, len(answer))
        self.assertGreater(brain_number_memory.PREVIEW_SECONDS, 0)
        self.assertTrue(brain_number_memory.HIDDEN_QUESTION)

    def test_difficulty_adapts_and_session_reset_restores_it(self):
        brain_number_memory.record_result(True)
        self.assertEqual(2, brain_number_memory.current_digit_count())

        question, _answer = brain_number_memory.get_question_and_answer()
        self.assertEqual(2, len(question))

        brain_number_memory.record_result(False)
        self.assertEqual(1, brain_number_memory.current_digit_count())
        brain_number_memory.record_result(False)
        self.assertEqual(1, brain_number_memory.current_digit_count())

        brain_number_memory.record_result(True)
        brain_number_memory.start_session()
        self.assertEqual(1, brain_number_memory.current_digit_count())


class VerbalMemoryTest(unittest.TestCase):

    def setUp(self):
        brain_verbal_memory.start_session()

    def test_first_word_is_new_then_can_be_seen(self):
        with patch.object(
                brain_verbal_memory.random,
                'choice',
                return_value=brain_verbal_memory.WORDS[0]):
            first_question, first_answer = (
                brain_verbal_memory.get_question_and_answer()
            )

        self.assertEqual('no', first_answer)
        self.assertIn(brain_verbal_memory.WORDS[0], first_question)

        with patch.object(
                brain_verbal_memory.random,
                'choice',
                side_effect=(True, brain_verbal_memory.WORDS[0])):
            second_question, second_answer = (
                brain_verbal_memory.get_question_and_answer()
            )

        self.assertEqual('yes', second_answer)
        self.assertIn(brain_verbal_memory.WORDS[0], second_question)
        self.assertEqual(1, brain_verbal_memory.seen_word_count())

        brain_verbal_memory.start_session()
        self.assertEqual(0, brain_verbal_memory.seen_word_count())

    def test_short_yes_no_aliases_are_declared(self):
        self.assertEqual('yes', brain_verbal_memory.ANSWER_ALIASES['y'])
        self.assertEqual('no', brain_verbal_memory.ANSWER_ALIASES['n'])

    def test_new_words_remain_available_after_the_base_pool_is_used(self):
        displayed_words = []
        with patch.object(
                brain_verbal_memory.random,
                'choice',
                return_value=False):
            for _turn in range(len(brain_verbal_memory.WORDS) + 6):
                question, answer = (
                    brain_verbal_memory.get_question_and_answer()
                )
                displayed_words.append(question.split('"')[1])
                self.assertEqual('no', answer)

        self.assertEqual(len(displayed_words), len(set(displayed_words)))
        self.assertTrue(any('-' in word for word in displayed_words))


class DirectionFocusTest(unittest.TestCase):

    def test_question_has_one_target_among_arrow_distractors(self):
        question, answer = brain_direction_focus.get_question_and_answer()
        target_arrow = brain_direction_focus.DIRECTIONS[answer]
        arrow_row = question.split(': ', 1)[1]
        arrows = arrow_row.split()

        self.assertEqual(brain_direction_focus.ARROW_COUNT, len(arrows))
        self.assertEqual(1, arrows.count(target_arrow))
        self.assertEqual(2, len(set(arrows)))

    def test_short_direction_aliases_are_declared(self):
        aliases = brain_direction_focus.ANSWER_ALIASES
        self.assertEqual('up', aliases['u'])
        self.assertEqual('down', aliases['d'])
        self.assertEqual('left', aliases['l'])
        self.assertEqual('right', aliases['r'])
        self.assertEqual('up', aliases['^'])
        self.assertEqual('down', aliases['v'])
        self.assertEqual('left', aliases['<'])
        self.assertEqual('right', aliases['>'])


class SymbolMatchTest(unittest.TestCase):

    def test_generator_answer_matches_displayed_pair(self):
        for _attempt in range(25):
            question, answer = brain_symbol_match.get_question_and_answer()
            pair = question.split('Symbols: ', 1)[1].split('. Same?', 1)[0]
            left_symbol, right_symbol = pair.split('  |  ')

            expected = 'yes' if left_symbol == right_symbol else 'no'
            self.assertEqual(expected, answer)

    def test_short_yes_no_aliases_are_declared(self):
        self.assertEqual('yes', brain_symbol_match.ANSWER_ALIASES['y'])
        self.assertEqual('no', brain_symbol_match.ANSWER_ALIASES['n'])


class WordScrambleTest(unittest.TestCase):

    def test_scramble_uses_same_letters_in_a_different_order(self):
        for _attempt in range(50):
            question, answer = brain_word_scramble.get_question_and_answer()
            scrambled = question.split(': ', 1)[1]

            self.assertEqual(Counter(answer), Counter(scrambled))
            self.assertNotEqual(answer, scrambled)
            self.assertIn(answer, brain_word_scramble.WORDS)

    def test_unscrambleable_input_is_rejected(self):
        with self.assertRaises(ValueError):
            brain_word_scramble.scramble_word('aaaa')


if __name__ == '__main__':
    unittest.main()
