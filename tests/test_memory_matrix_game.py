import json
import random
import unittest

from brain_games.games import brain_memory_matrix


class MemoryMatrixGameTest(unittest.TestCase):

    def test_metadata_and_terminal_fallback(self):
        self.assertEqual('Memory Matrix', brain_memory_matrix.NAME)
        self.assertEqual('memory-matrix', brain_memory_matrix.SLUG)
        self.assertEqual('Memory', brain_memory_matrix.CATEGORY)
        self.assertIn('one at a time', brain_memory_matrix.RULES)
        self.assertEqual(3, brain_memory_matrix.MAX_TILE_MISSES)

        question, answer = brain_memory_matrix.get_question_and_answer()
        self.assertIn('Memorize', question)
        self.assertEqual(
            sorted(int(index) for index in answer.split(',')),
            [int(index) for index in answer.split(',')],
        )

    def test_level_scaling_and_round_contract(self):
        previous_grid_size = 0
        previous_required_count = 0
        for level in range(1, 6):
            with self.subTest(level=level):
                generated = brain_memory_matrix.generate_round(
                    random.Random(100 + level),
                    level,
                )
                data = generated['data']

                self.assertEqual('memory-matrix', generated['kind'])
                self.assertEqual('memory_matrix', data['render_mode'])
                self.assertEqual('select_tiles', data['recall_mode'])
                self.assertEqual(
                    'instant_tiles',
                    data['interaction_mode'],
                )
                self.assertEqual(3, data['max_misses'])
                self.assertGreater(generated['preview_ms'], 0)
                self.assertIn('Two misses', generated['hidden_prompt'])
                self.assertGreater(data['grid_size'], previous_grid_size)
                self.assertGreater(
                    data['required_count'],
                    previous_required_count,
                )
                self.assertLess(
                    data['required_count'],
                    data['grid_size'] ** 2,
                )
                previous_grid_size = data['grid_size']
                previous_required_count = data['required_count']

    def test_patterns_are_unique_exact_and_nontrivial(self):
        for level in range(1, 6):
            for seed in range(40):
                with self.subTest(level=level, seed=seed):
                    generated = brain_memory_matrix.generate_round(
                        random.Random(seed),
                        level,
                    )
                    data = generated['data']
                    indices = data['highlighted_indices']
                    grid_size = data['grid_size']

                    self.assertEqual(data['required_count'], len(indices))
                    self.assertEqual(len(indices), len(set(indices)))
                    self.assertEqual(indices, sorted(indices))
                    self.assertTrue(all(
                        0 <= index < grid_size ** 2
                        for index in indices
                    ))
                    self.assertGreater(len({
                        index // grid_size
                        for index in indices
                    }), 1)
                    self.assertGreater(len({
                        index % grid_size
                        for index in indices
                    }), 1)
                    gaps = [
                        second - first
                        for first, second in zip(indices, indices[1:])
                    ]
                    self.assertGreater(len(set(gaps)), 1)

                    expected = ','.join(str(index) for index in indices)
                    self.assertEqual(expected, generated['expected_answer'])
                    self.assertEqual(
                        indices,
                        generated['review']['target_indices'],
                    )

    def test_generation_is_seeded_but_varied(self):
        first = brain_memory_matrix.generate_round(random.Random(42), 5)
        second = brain_memory_matrix.generate_round(random.Random(42), 5)
        self.assertEqual(first, second)

        patterns = {
            tuple(brain_memory_matrix.generate_round(
                random.Random(seed),
                3,
            )['data']['highlighted_indices'])
            for seed in range(30)
        }
        self.assertGreaterEqual(len(patterns), 25)

    def test_public_data_has_only_the_required_preview_pattern(self):
        generated = brain_memory_matrix.generate_round(
            random.Random(9),
            3,
        )
        data = generated['data']
        forbidden_answer_keys = {
            'answer',
            'expected_answer',
            'solution',
            'target_indices',
            'review',
        }
        self.assertTrue(forbidden_answer_keys.isdisjoint(data))
        self.assertIn('highlighted_indices', data)
        json.dumps(generated)

    def test_invalid_levels_are_rejected(self):
        for level in (0, 6, -1, True, 1.0, 1.5, '3', None):
            with self.subTest(level=level):
                with self.assertRaises(ValueError):
                    brain_memory_matrix.generate_round(
                        random.Random(1),
                        level,
                    )


if __name__ == '__main__':
    unittest.main()
