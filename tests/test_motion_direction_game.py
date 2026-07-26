from collections import Counter
import random
import unittest

from brain_games.games import brain_motion_direction


class MotionDirectionGameTest(unittest.TestCase):

    def test_metadata_and_aliases_are_limited_to_two_dimensions(self):
        game = brain_motion_direction
        self.assertEqual('Direction Focus', game.NAME)
        self.assertEqual('direction-focus', game.SLUG)
        self.assertEqual('Attention', game.CATEGORY)
        self.assertEqual(
            {'up', 'right', 'down', 'left'},
            set(game.ANSWER_ALIASES.values()),
        )
        for removed_alias in (
                't', 'a', 'in', 'out', 'forward', 'back', '⊙', '⊗'):
            self.assertNotIn(removed_alias, game.ANSWER_ALIASES)
        self.assertNotIn('toward', game.RULES.casefold())
        self.assertNotIn('away', game.RULES.casefold())

    def test_every_level_has_the_complete_web_round_contract(self):
        expected_choices = ['up', 'right', 'down', 'left']
        for level in range(1, 11):
            with self.subTest(level=level):
                game_round = brain_motion_direction.generate_round(
                    random.Random(level),
                    level,
                )
                data = game_round['data']
                self.assertEqual('motion-direction', game_round['kind'])
                self.assertIn(
                    game_round['expected_answer'],
                    expected_choices,
                )
                self.assertEqual(expected_choices, game_round['choices'])
                self.assertEqual(
                    brain_motion_direction.ANSWER_ALIASES,
                    game_round['aliases'],
                )
                self.assertEqual(
                    'motion_direction_2d',
                    data['render_mode'],
                )
                self.assertEqual(data['item_count'], len(data['items']))
                self.assertEqual(level, data['level_config']['level'])
                self.assertTrue(data['task_mode'])
                self.assertEqual(
                    game_round['prompt'],
                    data['instruction'],
                )
                self.assertEqual(
                    data['instruction'],
                    data['accessible_instruction'],
                )
                self.assertEqual(
                    'static_trails',
                    data['reduced_motion']['mode'],
                )

    def test_level_progression_introduces_motion_conflict_and_density(self):
        expected = {
            1: ('single_congruent', 1, 1, 'congruent'),
            2: ('single_incongruent', 1, 1, 'incongruent'),
            3: ('mixed_facing_group', 3, 3, 'mixed'),
            4: ('multi_arrow_flow', 6, 6, 'mixed'),
            5: ('marked_group_intro', 8, 2, 'decoupled'),
            6: ('marked_group_distractors', 12, 3, 'decoupled'),
            7: ('balanced_motion_field', 16, 4, 'decoupled'),
            8: ('dense_balanced_field', 16, 4, 'decoupled'),
            9: ('rapid_balanced_field', 20, 5, 'decoupled'),
            10: ('extreme_balanced_field', 24, 6, 'decoupled'),
        }
        prior_duration = None
        for level, contract in expected.items():
            game_round = brain_motion_direction.generate_round(
                random.Random(40 + level),
                level,
            )
            data = game_round['data']
            level_config = data['level_config']
            observed = (
                data['task_mode'],
                data['item_count'],
                level_config['target_count'],
                level_config['facing_mode'],
            )
            self.assertEqual(contract, observed)
            duration = data['items'][0]['animation']['duration_ms']
            if prior_duration is not None:
                self.assertLessEqual(duration, prior_duration)
            prior_duration = duration

    def test_early_facing_rules_teach_motion_over_arrowheads(self):
        first = brain_motion_direction.generate_round(
            random.Random(2),
            1,
        )
        first_item = first['data']['items'][0]
        self.assertEqual(
            first_item['motion_direction'],
            first_item['facing_direction'],
        )

        second = brain_motion_direction.generate_round(
            random.Random(3),
            2,
        )
        second_item = second['data']['items'][0]
        self.assertNotEqual(
            second_item['motion_direction'],
            second_item['facing_direction'],
        )

        for level in (3, 4):
            game_round = brain_motion_direction.generate_round(
                random.Random(10 + level),
                level,
            )
            self.assertGreater(
                len({
                    item['facing_direction']
                    for item in game_round['data']['items']
                }),
                1,
            )

    def test_marked_groups_and_review_identify_the_same_items(self):
        forbidden = {
            'answer',
            'correct',
            'expected_answer',
            'is_target',
            '_review_target',
            'target_direction',
        }
        for level in range(1, 11):
            for seed in range(8):
                game_round = brain_motion_direction.generate_round(
                    random.Random((level * 100) + seed),
                    level,
                )
                data = game_round['data']
                items = data['items']
                target_items = [
                    item
                    for item in items
                    if item['visual_role'] == 'target'
                ]
                distractors = [
                    item
                    for item in items
                    if item['visual_role'] == 'distractor'
                ]
                self.assertEqual(
                    data['level_config']['target_count'],
                    len(target_items),
                )
                self.assertEqual(
                    data['level_config']['distractor_count'],
                    len(distractors),
                )
                self.assertEqual(
                    {'tracked'},
                    {item['group_id'] for item in target_items},
                )
                expected_answer = game_round['expected_answer']
                self.assertTrue(all(
                    item['motion_direction'] == expected_answer
                    for item in target_items
                ))
                self.assertEqual(
                    {item['item_id'] for item in target_items},
                    set(game_round['review']['target_item_ids']),
                )
                self.assertEqual(
                    'tracked',
                    game_round['review']['target_group_id'],
                )
                self.assertTrue(all(
                    not forbidden.intersection(item)
                    for item in items
                ))

    def test_balanced_fields_defeat_majority_and_vector_mean_shortcuts(self):
        for level in range(5, 11):
            for seed in range(40):
                game_round = brain_motion_direction.generate_round(
                    random.Random((level * 1000) + seed),
                    level,
                )
                items = game_round['data']['items']
                motion_counts = Counter(
                    item['motion_direction']
                    for item in items
                )
                facing_counts = Counter(
                    item['facing_direction']
                    for item in items
                )
                self.assertEqual(1, len(set(motion_counts.values())))
                self.assertEqual(1, len(set(facing_counts.values())))
                self.assertEqual(
                    [0, 0],
                    [
                        sum(
                            item['motion_vector'][axis]
                            for item in items
                        )
                        for axis in range(2)
                    ],
                )
                self.assertTrue(
                    game_round['data']['motion_balance']['is_exact'],
                )
                answer = game_round['expected_answer']
                self.assertTrue(all(
                    item['motion_direction'] != answer
                    for item in items
                    if item['visual_role'] == 'distractor'
                ))

    def test_positions_paths_and_animation_stay_in_the_unit_field(self):
        vectors = brain_motion_direction.MOTION_VECTORS
        for level in range(1, 11):
            for seed in range(12):
                game_round = brain_motion_direction.generate_round(
                    random.Random((level * 100) + seed),
                    level,
                )
                items = game_round['data']['items']
                self.assertEqual(
                    len(items),
                    len({
                        tuple(item['position'])
                        for item in items
                    }),
                )
                for item in items:
                    self.assertEqual(
                        list(vectors[item['motion_direction']]),
                        item['motion_vector'],
                    )
                    self.assertEqual(
                        brain_motion_direction.FACING_ROTATIONS[
                            item['facing_direction']
                        ],
                        item['rotation_deg'],
                    )
                    animation = item['animation']
                    self.assertGreater(animation['duration_ms'], 0)
                    self.assertGreater(animation['travel'], 0)
                    self.assertGreaterEqual(animation['delay_ms'], 0)
                    start = item['trail']['start']
                    end = item['trail']['end']
                    for coordinate in (
                            item['position'] + start + end):
                        self.assertGreaterEqual(coordinate, 0)
                        self.assertLessEqual(coordinate, 1)
                    observed_delta = [
                        round(end[axis] - start[axis], 5)
                        for axis in range(2)
                    ]
                    animation_travel = animation['travel']
                    expected_delta = [
                        round(
                            item['motion_vector'][axis] * animation_travel,
                            5,
                        )
                        for axis in range(2)
                    ]
                    self.assertEqual(expected_delta, observed_delta)
                    self.assertEqual(
                        'end',
                        item['trail']['direction_marker'],
                    )

    def test_accessible_labels_describe_role_facing_and_motion(self):
        game_round = brain_motion_direction.generate_round(
            random.Random(99),
            10,
        )
        for item in game_round['data']['items']:
            label = item['accessible_label'].casefold()
            self.assertIn(item['visual_role'], {
                'target',
                'distractor',
            })
            self.assertIn(
                'tracked'
                if item['visual_role'] == 'target'
                else 'distractor',
                label,
            )
            self.assertIn(item['facing_direction'], label)
            self.assertIn(item['motion_direction'], label)

    def test_generation_is_seed_deterministic_and_seed_diverse(self):
        for level in range(1, 11):
            first = brain_motion_direction.generate_round(
                random.Random(700 + level),
                level,
            )
            second = brain_motion_direction.generate_round(
                random.Random(700 + level),
                level,
            )
            self.assertEqual(first, second)

        rounds = [
            brain_motion_direction.generate_round(
                random.Random(seed),
                10,
            )
            for seed in range(80)
        ]
        self.assertEqual(
            {'up', 'right', 'down', 'left'},
            {game_round['expected_answer'] for game_round in rounds},
        )
        self.assertGreater(
            len({
                tuple(
                    tuple(item['position'])
                    for item in game_round['data']['items']
                )
                for game_round in rounds
            }),
            70,
        )

    def test_invalid_levels_are_rejected(self):
        for level in (0, 11, -1, 1.5, '5', True, None):
            with self.subTest(level=level):
                with self.assertRaises(ValueError):
                    brain_motion_direction.generate_round(
                        random.Random(1),
                        level,
                    )


if __name__ == '__main__':
    unittest.main()
