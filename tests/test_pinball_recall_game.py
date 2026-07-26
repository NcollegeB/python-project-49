from collections import Counter
import json
import random
import unittest

from brain_games.games import brain_pinball_recall as pinball


def _nested_keys(value):
    if isinstance(value, dict):
        keys = set(value)
        for nested in value.values():
            keys.update(_nested_keys(nested))
        return keys
    if isinstance(value, (list, tuple)):
        keys = set()
        for nested in value:
            keys.update(_nested_keys(nested))
        return keys
    return set()


class PinballRecallMetadataTest(unittest.TestCase):

    def test_metadata_and_difficulty_are_declared(self):
        self.assertEqual('Pinball Recall', pinball.NAME)
        self.assertEqual('pinball-recall', pinball.SLUG)
        self.assertEqual('Memory', pinball.CATEGORY)
        self.assertTrue(pinball.RULES)
        self.assertEqual((4, 4, 5, 6, 7), pinball.LEVEL_GRID_SIZES)
        self.assertEqual((2, 3, 4, 5, 6), pinball.LEVEL_PATH_BOUNCES)
        self.assertEqual(
            sorted(pinball.LEVEL_PREVIEW_MS),
            list(pinball.LEVEL_PREVIEW_MS),
        )

    def test_perimeter_ports_are_canonical_and_complete(self):
        ports = pinball.perimeter_ports(4)

        self.assertEqual(16, len(ports))
        self.assertEqual(16, len(set(ports)))
        self.assertEqual(('N1', 'N2', 'N3', 'N4'), ports[:4])
        self.assertEqual(('W1', 'W2', 'W3', 'W4'), ports[-4:])
        self.assertEqual('E3', pinball.canonical_port_label('e', 3, 4))

    def test_invalid_levels_and_ports_are_rejected(self):
        for invalid_level in (0, 6, -1, 1.0, True):
            with self.subTest(level=invalid_level):
                with self.assertRaises(ValueError):
                    pinball.generate_round(
                        random.Random(1),
                        invalid_level,
                    )
        for invalid_port in ('', 'Q1', 'N0', 'N5', 'N01'):
            with self.subTest(port=invalid_port):
                with self.assertRaises(ValueError):
                    pinball.simulate_path(4, [], invalid_port)


class PinballRecallSimulationTest(unittest.TestCase):

    def test_reflection_table_matches_slash_mirrors(self):
        expected = {
            ('up', '/'): 'right',
            ('right', '/'): 'up',
            ('down', '/'): 'left',
            ('left', '/'): 'down',
            ('up', '\\'): 'left',
            ('left', '\\'): 'up',
            ('down', '\\'): 'right',
            ('right', '\\'): 'down',
        }
        for inputs, output in expected.items():
            with self.subTest(inputs=inputs):
                self.assertEqual(
                    output,
                    pinball.reflect_direction(*inputs),
                )

    def test_known_board_has_exact_path_and_exit(self):
        bumpers = [
            {'cell': [1, 1], 'orientation': '\\'},
            {'cell': [3, 1], 'orientation': '/'},
            {'cell': [0, 3], 'orientation': '\\'},
        ]

        simulation = pinball.simulate_path(4, bumpers, 'W2')

        self.assertEqual('W4', simulation['exit'])
        self.assertEqual(2, simulation['bounces'])
        self.assertFalse(simulation['looped'])
        self.assertEqual(
            [[1, 0], [1, 1], [2, 1], [3, 1], [3, 0]],
            simulation['path'],
        )
        self.assertEqual(
            simulation,
            pinball.validate_board(
                4,
                bumpers,
                'W2',
                expected_exit='w4',
                exact_bounces=2,
            ),
        )

    def test_validation_rejects_wrong_claims_and_malformed_bumpers(self):
        board = [{'cell': [0, 0], 'orientation': '/'}]
        with self.assertRaises(ValueError):
            pinball.validate_board(
                4,
                board,
                'W1',
                expected_exit='S4',
            )
        with self.assertRaises(ValueError):
            pinball.validate_board(
                4,
                board,
                'W1',
                exact_bounces=2,
            )
        malformed_boards = (
            [{'cell': [4, 0], 'orientation': '/'}],
            [{'cell': [0, 0], 'orientation': '|'}],
            [
                {'cell': [0, 0], 'orientation': '/'},
                {'cell': [0, 0], 'orientation': '\\'},
            ],
        )
        for malformed in malformed_boards:
            with self.subTest(board=malformed):
                with self.assertRaises(ValueError):
                    pinball.simulate_path(4, malformed, 'N1')


class PinballRecallGenerationTest(unittest.TestCase):

    def test_generated_rounds_have_exact_paths_across_many_seeds(self):
        for level in range(1, 6):
            grid_size = pinball.LEVEL_GRID_SIZES[level - 1]
            required_bounces = pinball.LEVEL_PATH_BOUNCES[level - 1]
            distractor_count = (
                pinball.LEVEL_DISTRACTOR_COUNTS[level - 1]
            )
            for seed in range(120):
                with self.subTest(level=level, seed=seed):
                    generated = pinball.generate_round(
                        random.Random(seed),
                        level,
                    )
                    data = generated['data']
                    simulation = pinball.validate_board(
                        data['grid_size'],
                        data['bumpers'],
                        data['entry_port'],
                        expected_exit=generated['expected_answer'],
                        exact_bounces=required_bounces,
                    )
                    path_cells = {
                        tuple(cell) for cell in simulation['path']
                    }
                    bumper_cells = [
                        tuple(bumper['cell'])
                        for bumper in data['bumpers']
                    ]
                    path_bumpers = [
                        cell for cell in bumper_cells
                        if cell in path_cells
                    ]

                    self.assertEqual(grid_size, data['grid_size'])
                    self.assertFalse(simulation['looped'])
                    self.assertEqual(
                        len(simulation['path']),
                        len(path_cells),
                    )
                    self.assertEqual(
                        required_bounces,
                        len(path_bumpers),
                    )
                    self.assertEqual(
                        distractor_count,
                        len(bumper_cells) - len(path_bumpers),
                    )
                    self.assertEqual(
                        required_bounces + distractor_count,
                        len(bumper_cells),
                    )
                    self.assertEqual(
                        len(bumper_cells),
                        len(set(bumper_cells)),
                    )
                    self.assertNotEqual(
                        data['entry_port'],
                        generated['expected_answer'],
                    )

    def test_round_contract_is_json_safe_and_keeps_review_private(self):
        for level in range(1, 6):
            generated = pinball.generate_round(
                random.Random(700 + level),
                level,
            )
            data = generated['data']
            public_round = {
                key: value
                for key, value in generated.items()
                if key not in ('expected_answer', 'review')
            }

            self.assertEqual('pinball-recall', generated['kind'])
            self.assertEqual(
                'pinball_recall',
                data['render_mode'],
            )
            self.assertEqual(
                pinball.RECALL_MODE,
                data['recall_mode'],
            )
            self.assertGreater(generated['preview_ms'], 0)
            self.assertTrue(generated['hidden_prompt'])
            self.assertTrue(data['instruction'])
            self.assertTrue(data['accessible_instruction'])
            self.assertEqual(
                list(pinball.perimeter_ports(data['grid_size'])),
                data['perimeter_ports'],
            )
            self.assertEqual(
                data['perimeter_ports'],
                generated['choices'],
            )
            self.assertEqual(
                {'exit', 'path'},
                set(generated['review']),
            )
            self.assertEqual(
                generated['expected_answer'],
                generated['review']['exit'],
            )
            self.assertNotIn(
                'expected_answer',
                _nested_keys(public_round),
            )
            self.assertNotIn('exit', _nested_keys(public_round))
            self.assertNotIn('path', _nested_keys(public_round))
            self.assertNotIn('is_target', _nested_keys(public_round))
            self.assertEqual(
                1,
                Counter(data['perimeter_ports'])[
                    generated['expected_answer']
                ],
            )
            json.dumps(generated)
            json.dumps(public_round)

    def test_seeded_generation_is_repeatable_and_varied(self):
        for level in range(1, 6):
            first = pinball.generate_round(
                random.Random(91827),
                level,
            )
            second = pinball.generate_round(
                random.Random(91827),
                level,
            )
            self.assertEqual(first, second)

            signatures = set()
            entries = set()
            exits = set()
            for seed in range(50):
                generated = pinball.generate_round(
                    random.Random(seed),
                    level,
                )
                data = generated['data']
                signature = (
                    data['entry_port'],
                    generated['expected_answer'],
                    tuple(sorted(
                        (
                            tuple(bumper['cell']),
                            bumper['orientation'],
                        )
                        for bumper in data['bumpers']
                    )),
                )
                signatures.add(signature)
                entries.add(data['entry_port'])
                exits.add(generated['expected_answer'])

            self.assertGreaterEqual(len(signatures), 45)
            self.assertGreaterEqual(len(entries), 8)
            self.assertGreaterEqual(len(exits), 8)

    def test_terminal_fallback_displays_a_board_and_valid_answer(self):
        question, answer = pinball.get_question_and_answer()

        self.assertIn('Entry:', question)
        self.assertIn('Exit port?', question)
        self.assertTrue(
            answer in pinball.perimeter_ports(
                pinball.LEVEL_GRID_SIZES[0],
            )
        )


if __name__ == '__main__':
    unittest.main()
