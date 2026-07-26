from collections import Counter
from math import ceil
from math import cos
from math import gcd
from math import radians
from math import sin
import json
import random
import threading
import unittest

from brain_games.difficulty import CORRECT_PER_LEVEL
from brain_games.difficulty import DIRECTION_DIFFERENCES_DEG
from brain_games.difficulty import DIRECTION_ITEM_COUNTS
from brain_games.difficulty import EXTENDED_MAX_LEVEL
from brain_games.difficulty import MAX_LEVEL
from brain_games.difficulty import max_level_for
from brain_games.difficulty import SYMBOL_SEQUENCE_LENGTHS
from brain_games.difficulty import time_limit_ms
from brain_games.difficulty import VERBAL_HISTORY_WINDOWS
from brain_games.difficulty import VERBAL_REPEAT_LAGS
from brain_games.difficulty import VERBAL_SEEN_PERCENTAGES
from brain_games.games.catalog import CORE_GAMES
import brain_games.web_engine as web_engine
from brain_games.web_engine import GAME_CATALOG
from brain_games.web_engine import InvalidAnswerError
from brain_games.web_engine import RunEndedError
from brain_games.web_engine import RunStore
from brain_games.web_engine import SCORE_GAME_PREFIX
from brain_games.web_engine import StaleRoundError
from brain_games.web_engine import TIMEOUT_ANSWER
from brain_games.web_engine import UnknownGameError
from brain_games.web_engine import UnknownRunError
from brain_games.web_engine import game_catalog


class MemoryLeaderboard:
    def __init__(self):
        self.records = []

    def record(self, player, game, score):
        entry = {'player': player, 'game': game, 'score': score}
        self.records.append(entry)
        return entry

    def top(
            self,
            limit=10,
            game=None,
            player=None,
            game_prefix=None,
    ):
        entries = self.records
        if game is not None:
            entries = [entry for entry in entries if entry['game'] == game]
        if game_prefix is not None:
            entries = [
                entry for entry in entries
                if entry['game'].startswith(game_prefix)
            ]
        if player is not None:
            entries = [
                entry for entry in entries
                if entry['player'].casefold() == player.casefold()
            ]
        entries = sorted(entries, key=lambda item: -item['score'])
        return [dict(entry) for entry in entries[:limit]]


class FailOnceLeaderboard(MemoryLeaderboard):
    def __init__(self):
        super().__init__()
        self.attempts = 0

    def record(self, player, game, score):
        self.attempts += 1
        if self.attempts == 1:
            raise OSError('temporary write failure')
        return super().record(player, game, score)


class NoShuffleRandom(random.Random):
    def shuffle(self, values):
        return None


class BoundaryRepeatRandom(NoShuffleRandom):
    def __init__(self, seed=None):
        super().__init__(seed)
        self.shuffle_count = 0

    def shuffle(self, values):
        self.shuffle_count += 1
        if self.shuffle_count == 2:
            values.insert(0, values.pop())


def expected_answer(store, run_id):
    return store._runs[run_id].round['expected_answer']


def assert_no_private_answer(test_case, value):
    if isinstance(value, dict):
        test_case.assertNotIn('expected_answer', value)
        for child in value.values():
            assert_no_private_answer(test_case, child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            assert_no_private_answer(test_case, child)


def assert_no_forbidden_keys(test_case, value, forbidden):
    if isinstance(value, dict):
        for key, child in value.items():
            test_case.assertNotIn(key, forbidden)
            assert_no_forbidden_keys(test_case, child, forbidden)
    elif isinstance(value, (list, tuple)):
        for child in value:
            assert_no_forbidden_keys(test_case, child, forbidden)


def evaluate_expression(expression):
    python_expression = expression.replace('×', '*').replace('÷', '//')
    return eval(python_expression, {'__builtins__': {}}, {})


def rotate_symbol_grid_for_review(angles, quarter_turns):
    expected = list(angles)
    for _turn in range(quarter_turns):
        rotated = [None] * 9
        for row in range(3):
            for column in range(3):
                target_row = column
                target_column = 2 - row
                target_index = (target_row * 3) + target_column
                source_index = (row * 3) + column
                rotated[target_index] = (expected[source_index] + 90) % 360
        expected = rotated
    return expected


def symbol_review_values(data):
    rule = data['comparison_rule']
    transform = data['transform_degrees']
    if rule in ('polycube_rotation', 'polycube_chirality'):
        return (
            [RunStore._polycube_canonical(data['left_cubes'])],
            [RunStore._polycube_canonical(data['right_cubes'])],
        )
    if rule == 'exact':
        expected = [
            token['symbol']
            for token in data['left_tokens']
        ]
    elif rule == 'global_rotation':
        expected = [
            (token['rotation_deg'] + transform) % 360
            for token in data['left_tokens']
        ]
    else:
        expected = rotate_symbol_grid_for_review(
            [
                token['rotation_deg']
                for token in data['left_tokens']
            ],
            transform // 90,
        )
    actual = [
        (
            token['symbol']
            if rule == 'exact'
            else token['rotation_deg']
        )
        for token in data['right_tokens']
    ]
    return expected, actual


class CatalogTest(unittest.TestCase):

    def test_catalog_includes_all_core_games_and_culmination(self):
        catalog = game_catalog()

        self.assertEqual(len(CORE_GAMES) + 1, len(GAME_CATALOG))
        self.assertEqual(
            [game.SLUG for game in CORE_GAMES] + ['culmination'],
            [game['slug'] for game in catalog],
        )
        for game in catalog:
            with self.subTest(game=game['slug']):
                self.assertEqual(
                    {
                        'slug',
                        'name',
                        'category',
                        'rules',
                        'description',
                        'icon',
                        'max_level',
                    },
                    set(game),
                )
                self.assertTrue(all(game.values()))
                self.assertEqual(
                    max_level_for(game['slug']),
                    game['max_level'],
                )

    def test_only_extended_games_receive_ten_levels(self):
        self.assertEqual(
            EXTENDED_MAX_LEVEL,
            max_level_for('direction-focus'),
        )
        self.assertEqual(
            EXTENDED_MAX_LEVEL,
            max_level_for('symbol-match'),
        )
        self.assertEqual(
            EXTENDED_MAX_LEVEL,
            max_level_for('culmination'),
        )
        self.assertEqual(MAX_LEVEL, max_level_for('calc'))
        self.assertEqual(MAX_LEVEL, max_level_for('unknown-game'))

    def test_catalog_function_returns_fresh_mutable_copies(self):
        first = game_catalog()
        first[0]['name'] = 'Changed'
        first.pop()

        second = game_catalog()

        self.assertEqual(len(CORE_GAMES) + 1, len(second))
        self.assertNotEqual('Changed', second[0]['name'])


class RunStoreTest(unittest.TestCase):

    def setUp(self):
        self.board = MemoryLeaderboard()
        self.store = RunStore(
            leaderboard=self.board,
            random_factory=lambda: random.Random(1),
        )

    def test_create_returns_a_public_structured_round(self):
        run = self.store.create(' even ', ' Ada ')
        game_round = run['round']

        self.assertEqual('even', run['game'])
        self.assertEqual('Even or Odd', run['game_name'])
        self.assertEqual('Ada', run['player'])
        self.assertEqual(0, run['score'])
        self.assertEqual(3, run['lives'])
        self.assertEqual(3, run['max_lives'])
        self.assertEqual(1, run['level'])
        self.assertEqual(0, run['level_progress'])
        self.assertEqual(3, run['level_goal'])
        self.assertEqual(5, run['max_level'])
        self.assertTrue(run['ranked'])
        self.assertEqual('standard', run['timing_mode'])
        self.assertFalse(run['ended'])
        self.assertFalse(run['quit_early'])
        self.assertEqual(32, len(run['run_id']))
        self.assertEqual(
            {
                'round_id',
                'source_slug',
                'source_name',
                'source_category',
                'kind',
                'prompt',
                'rules',
                'data',
                'choices',
                'preview_ms',
                'level',
                'difficulty_label',
                'time_limit_ms',
                'hidden_prompt',
                'cycle_position',
                'cycle_total',
                'source_level',
            },
            set(game_round),
        )
        self.assertEqual('even', game_round['source_slug'])
        self.assertEqual('choice', game_round['kind'])
        self.assertIn('number', game_round['data'])
        self.assertEqual(1, game_round['level'])
        self.assertEqual(1, game_round['source_level'])
        self.assertEqual('Foundation', game_round['difficulty_label'])
        self.assertEqual(4000, game_round['time_limit_ms'])
        self.assertEqual(['yes', 'no'], game_round['choices'])
        self.assertIsNone(game_round['cycle_position'])
        assert_no_private_answer(self, run)

    def test_every_core_game_creates_json_safe_public_round(self):
        required_round_keys = {
            'round_id',
            'source_slug',
            'source_name',
            'source_category',
            'kind',
            'prompt',
            'rules',
            'data',
            'choices',
            'preview_ms',
            'level',
            'difficulty_label',
            'time_limit_ms',
            'hidden_prompt',
            'cycle_position',
            'cycle_total',
            'source_level',
        }
        for game in CORE_GAMES:
            with self.subTest(game=game.SLUG):
                run = self.store.create(game.SLUG, 'Player')
                self.assertEqual(required_round_keys, set(run['round']))
                self.assertEqual(game.SLUG, run['round']['source_slug'])
                self.assertIsInstance(run['round']['data'], dict)
                self.assertIsInstance(run['round']['choices'], list)
                assert_no_private_answer(self, run)

    def test_every_game_varies_its_first_round_across_random_seeds(self):
        for game in GAME_CATALOG:
            fingerprints = set()
            for seed in range(24):
                store = RunStore(
                    leaderboard=MemoryLeaderboard(),
                    random_factory=lambda seed=seed: random.Random(seed),
                )
                game_round = dict(
                    store.create(game['slug'], 'Player')['round'],
                )
                game_round.pop('round_id')
                fingerprints.add(json.dumps(game_round, sort_keys=True))

            with self.subTest(game=game['slug']):
                self.assertGreaterEqual(len(fingerprints), 12)

    def test_answer_grades_server_side_and_moves_to_a_new_round(self):
        run = self.store.create('even', 'Ada')
        old_round = run['round']

        result = self.store.answer(
            run['run_id'],
            old_round['round_id'],
            expected_answer(self.store, run['run_id']),
        )

        self.assertEqual(1, result['score'])
        self.assertEqual(3, result['lives'])
        self.assertTrue(result['result']['correct'])
        self.assertEqual(
            result['result']['submitted_answer'],
            result['result']['expected_answer'],
        )
        self.assertEqual('even', result['result']['source_slug'])
        self.assertFalse(result['result']['timed_out'])
        self.assertEqual(1, result['result']['level_before'])
        self.assertEqual(1, result['result']['level_after'])
        self.assertFalse(result['result']['leveled_up'])
        self.assertNotEqual(
            old_round['round_id'],
            result['round']['round_id'],
        )
        assert_no_private_answer(self, result['round'])

    def test_review_is_revealed_only_after_each_round_is_graded(self):
        slugs = [game.SLUG for game in CORE_GAMES]
        slugs.append('culmination')

        for slug in slugs:
            with self.subTest(game=slug):
                run = self.store.create(slug, 'Ada')
                active = self.store._runs[run['run_id']].round
                private_review = active['review']

                assert_no_forbidden_keys(
                    self,
                    run['round'],
                    {'review'},
                )
                answered = self.store.answer(
                    run['run_id'],
                    run['round']['round_id'],
                    active['expected_answer'],
                )

                self.assertEqual(
                    private_review,
                    answered['result']['review'],
                )
                self.assertTrue(
                    answered['result']['review']['explanation'],
                )
                assert_no_forbidden_keys(
                    self,
                    answered['round'],
                    {'review'},
                )

    def test_verbal_review_reports_new_and_seen_prompt_history(self):
        new_run = self.store.create('verbal-memory', 'New')
        new_result = self.store.answer(
            new_run['run_id'],
            new_run['round']['round_id'],
            'no',
        )
        new_review = new_result['result']['review']

        self.assertFalse(new_review['was_seen'])
        self.assertIsNone(new_review['prior_lag'])
        self.assertIn('had not appeared', new_review['explanation'])

        seen_run = self.store.create('verbal-memory', 'Seen')
        state = self.store._runs[seen_run['run_id']]
        target = RunStore._verbal_term_for_index(0)
        other = RunStore._verbal_term_for_index(1)
        state.level = 2
        state.word_history = [target, other]
        state.seen_words = {target, other}
        state.new_word_index = 2
        state.truth_bags = {'verbal-memory:2': [True]}
        state.round = self.store._make_round(state)
        public = self.store._public_run(state)

        self.assertEqual(target, public['round']['data']['word'])
        assert_no_forbidden_keys(self, public['round'], {'review'})
        seen_result = self.store.answer(
            public['run_id'],
            public['round']['round_id'],
            'yes',
        )
        seen_review = seen_result['result']['review']

        self.assertTrue(seen_review['was_seen'])
        self.assertEqual(2, seen_review['prior_lag'])
        self.assertIn('2 prompts ago', seen_review['explanation'])

    def test_direction_review_identifies_private_tracked_group(self):
        run = self.store.create('direction-focus', 'Ada')
        state = self.store._runs[run['run_id']]
        state.level = EXTENDED_MAX_LEVEL
        state.round = self.store._make_round(state)
        public = self.store._public_run(state)
        private_review = state.round['review']
        target_items = [
            item
            for item in public['round']['data']['items']
            if item['visual_role'] == 'target'
        ]

        self.assertTrue(target_items)
        self.assertTrue(all(
            item['motion_direction'] == state.round['expected_answer']
            for item in target_items
        ))
        self.assertEqual('motion_direction_2d', public['round']['data'][
            'render_mode'
        ])
        self.assertEqual(
            {item['item_id'] for item in target_items},
            set(private_review['target_item_ids']),
        )
        assert_no_forbidden_keys(
            self,
            public['round'],
            {
                'review',
                'target_item_ids',
                'target_group_id',
                'expected_answer',
            },
        )
        wrong_answer = next(
            choice
            for choice in public['round']['choices']
            if choice != state.round['expected_answer']
        )
        result = self.store.answer(
            public['run_id'],
            public['round']['round_id'],
            wrong_answer,
        )

        self.assertEqual(
            'tracked',
            result['result']['review']['target_group_id'],
        )

    def test_symbol_review_identifies_private_transformed_mismatch(self):
        run = self.store.create('symbol-match', 'Ada')
        state = self.store._runs[run['run_id']]
        state.level = EXTENDED_MAX_LEVEL
        state.truth_bags = {
            'symbol-match:{}'.format(EXTENDED_MAX_LEVEL): [False],
        }
        state.round = self.store._make_round(state)
        public = self.store._public_run(state)
        review = state.round['review']
        data = public['round']['data']
        left_canonical = RunStore._polycube_canonical(
            data['left_cubes'],
        )
        right_canonical = RunStore._polycube_canonical(
            data['right_cubes'],
        )

        self.assertFalse(review['matches'])
        self.assertNotEqual(left_canonical, right_canonical)
        self.assertEqual(
            list(range(data['shape_size'])),
            review['mismatch_indices'],
        )
        assert_no_forbidden_keys(
            self,
            public['round'],
            {'review', 'mismatch_indices'},
        )
        result = self.store.answer(
            public['run_id'],
            public['round']['round_id'],
            'yes',
        )

        self.assertEqual(
            review['mismatch_indices'],
            result['result']['review']['mismatch_indices'],
        )

    def test_direction_review_tracks_the_marked_group_at_every_level(self):
        for level in range(1, EXTENDED_MAX_LEVEL + 1):
            with self.subTest(level=level):
                run = self.store.create('direction-focus', 'Ada')
                state = self.store._runs[run['run_id']]
                state.level = level
                state.round = self.store._make_round(state)
                public = self.store._public_run(state)['round']
                review = state.round['review']
                items = public['data']['items']
                target_items = [
                    item
                    for item in items
                    if item['visual_role'] == 'target'
                ]

                self.assertEqual(
                    public['data']['level_config']['target_count'],
                    len(target_items),
                )
                expected_direction = state.round['expected_answer']
                self.assertTrue(all(
                    item['motion_direction'] == expected_direction
                    for item in target_items
                ))
                self.assertEqual(
                    {item['item_id'] for item in target_items},
                    set(review['target_item_ids']),
                )
                assert_no_forbidden_keys(
                    self,
                    public,
                    {'review', 'target_item_ids', 'expected_answer'},
                )

    def test_symbol_review_matches_every_level_and_rule(self):
        for level in range(1, EXTENDED_MAX_LEVEL + 1):
            for matches in (True, False):
                with self.subTest(level=level, matches=matches):
                    run = self.store.create('symbol-match', 'Ada')
                    state = self.store._runs[run['run_id']]
                    state.level = level
                    state.truth_bags = {
                        'symbol-match:{}'.format(level): [matches],
                    }
                    state.round = self.store._make_round(state)
                    public = self.store._public_run(state)['round']
                    data = public['data']
                    review = state.round['review']
                    self.assertEqual(matches, review['matches'])
                    expected, actual = symbol_review_values(data)
                    self.assertEqual(matches, expected == actual)
                    if level <= 8:
                        mismatch_indices = [
                            index
                            for index, pair in enumerate(
                                zip(expected, actual),
                            )
                            if pair[0] != pair[1]
                        ]
                        self.assertEqual(
                            mismatch_indices,
                            review['mismatch_indices'],
                        )
                        self.assertEqual(
                            0 if matches else 1,
                            len(review['mismatch_indices']),
                        )
                    else:
                        expected_count = 0 if matches else 1
                        self.assertGreaterEqual(
                            len(review['mismatch_indices']),
                            expected_count,
                        )
                    assert_no_forbidden_keys(
                        self,
                        public,
                        {'review', 'mismatch_indices'},
                    )

    def test_stale_duplicate_and_invalid_choice_do_not_change_run(self):
        run = self.store.create('even', 'Ada')
        round_id = run['round']['round_id']

        with self.assertRaises(InvalidAnswerError) as invalid:
            self.store.answer(run['run_id'], round_id, 'sometimes')
        self.assertEqual(['yes', 'no'], invalid.exception.choices)

        correct_answer = expected_answer(self.store, run['run_id'])
        answered = self.store.answer(
            run['run_id'],
            round_id,
            correct_answer,
        )
        with self.assertRaises(StaleRoundError) as stale:
            self.store.answer(run['run_id'], round_id, correct_answer)

        self.assertEqual(run['run_id'], stale.exception.run_id)
        self.assertEqual(round_id, stale.exception.round_id)
        self.assertEqual(
            answered['round']['round_id'],
            stale.exception.current_round_id,
        )
        self.assertEqual(1, answered['score'])

    def test_three_misses_end_and_record_exactly_once(self):
        run = self.store.create('calc', 'Grace')
        latest = run
        for _miss in range(3):
            latest = self.store.answer(
                run['run_id'],
                latest['round']['round_id'],
                'definitely-wrong',
            )

        self.assertTrue(latest['ended'])
        self.assertFalse(latest['quit_early'])
        self.assertEqual(0, latest['lives'])
        self.assertIsNone(latest['round'])
        self.assertEqual(
            [{
                'player': 'Grace',
                'game': '{}calc'.format(SCORE_GAME_PREFIX),
                'score': 0,
            }],
            self.board.records,
        )
        with self.assertRaises(RunEndedError):
            self.store.answer(run['run_id'], 'anything', '0')
        ended_again = self.store.quit(run['run_id'])
        self.assertTrue(ended_again['ended'])
        self.assertEqual(1, len(self.board.records))

    def test_quit_is_idempotent_and_leaders_can_filter(self):
        run = self.store.create('prime', 'Lin')

        first = self.store.quit(run['run_id'])
        second = self.store.quit(run['run_id'])

        self.assertTrue(first['ended'])
        self.assertTrue(first['quit_early'])
        self.assertIsNone(first['round'])
        self.assertEqual(first, second)
        self.assertEqual(1, len(self.board.records))
        self.assertEqual(
            [{
                'player': 'Lin',
                'game': 'prime',
                'score': 0,
            }],
            self.store.leaders('PRIME'),
        )
        self.assertEqual(
            [{
                'player': 'Lin',
                'game': 'prime',
                'score': 0,
            }],
            self.store.leaders(player='lin'),
        )
        self.assertEqual([], self.store.leaders('even'))

    def test_failed_score_write_can_be_retried_by_quitting(self):
        board = FailOnceLeaderboard()
        store = RunStore(
            leaderboard=board,
            random_factory=lambda: random.Random(1),
        )
        run = store.create('calc', 'Grace')
        latest = run
        for _miss in range(2):
            latest = store.answer(
                run['run_id'],
                latest['round']['round_id'],
                'definitely-wrong',
            )

        with self.assertRaises(OSError):
            store.answer(
                run['run_id'],
                latest['round']['round_id'],
                'definitely-wrong',
            )

        ended = store.quit(run['run_id'])
        self.assertTrue(ended['ended'])
        self.assertEqual(2, board.attempts)
        self.assertEqual(1, len(board.records))

    def test_store_prunes_completed_runs_at_its_configured_limit(self):
        store = RunStore(
            leaderboard=MemoryLeaderboard(),
            random_factory=lambda: random.Random(1),
            max_runs=2,
        )
        first = store.create('even', 'One')
        store.quit(first['run_id'])
        second = store.create('even', 'Two')
        third = store.create('even', 'Three')

        with self.assertRaises(UnknownRunError):
            store.quit(first['run_id'])
        self.assertEqual('Two', store.quit(second['run_id'])['player'])
        self.assertEqual('Three', store.quit(third['run_id'])['player'])

    def test_run_records_under_the_ruleset_it_started_with(self):
        run = self.store.create('even', 'Legacy')
        state = self.store._runs[run['run_id']]
        state.score_ruleset = 'r3'

        self.store.quit(run['run_id'])

        self.assertEqual('r3:even', self.board.records[-1]['game'])

    def test_number_and_verbal_memory_are_isolated_between_runs(self):
        number_one = self.store.create('number-memory', 'One')
        number_two = self.store.create('number-memory', 'Two')
        number_one_next = self.store.answer(
            number_one['run_id'],
            number_one['round']['round_id'],
            number_one['round']['prompt'],
        )

        self.assertEqual(3, number_one_next['round']['data']['digits'])
        self.assertEqual(2, number_two['round']['data']['digits'])

        verbal_one = self.store.create('verbal-memory', 'One')
        verbal_two = self.store.create('verbal-memory', 'Two')
        verbal_one_next = self.store.answer(
            verbal_one['run_id'],
            verbal_one['round']['round_id'],
            'no',
        )

        self.assertTrue(verbal_one['round']['data']['word'])
        self.assertTrue(verbal_two['round']['data']['word'])
        self.assertNotEqual(
            verbal_one['round']['round_id'],
            verbal_two['round']['round_id'],
        )
        self.assertTrue(verbal_one_next['round']['data']['word'])

    def test_verbal_memory_randomises_fresh_unseen_word_order(self):
        first_words = set()
        for seed in range(12):
            store = RunStore(
                leaderboard=MemoryLeaderboard(),
                random_factory=lambda seed=seed: random.Random(seed),
            )
            run = store.create('verbal-memory', 'Player')
            first_words.add(run['round']['data']['word'])

        self.assertGreaterEqual(len(first_words), 8)
        self.assertNotEqual(
            {RunStore._verbal_term_for_index(0)},
            first_words,
        )

    def test_unknown_inputs_expose_useful_exception_attributes(self):
        with self.assertRaises(UnknownGameError) as unknown_game:
            self.store.create('missing', 'Ada')
        self.assertEqual('missing', unknown_game.exception.game_slug)

        with self.assertRaises(UnknownRunError) as unknown_run:
            self.store.quit('missing-run')
        self.assertEqual('missing-run', unknown_run.exception.run_id)

        with self.assertRaises(UnknownGameError):
            self.store.leaders('missing')
        with self.assertRaises(ValueError):
            self.store.create('even', '   ')

    def test_concurrent_duplicate_answers_only_grade_once(self):
        run = self.store.create('even', 'Ada')
        answer = expected_answer(self.store, run['run_id'])
        barrier = threading.Barrier(3)
        outcomes = []

        def submit():
            barrier.wait()
            try:
                outcome = self.store.answer(
                    run['run_id'],
                    run['round']['round_id'],
                    answer,
                )
            except Exception as error:
                outcomes.append(error)
            else:
                outcomes.append(outcome)

        threads = [threading.Thread(target=submit) for _item in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        successes = [item for item in outcomes if isinstance(item, dict)]
        failures = [item for item in outcomes if isinstance(item, Exception)]
        self.assertEqual(1, len(successes))
        self.assertEqual(1, successes[0]['score'])
        self.assertEqual(1, len(failures))
        self.assertIsInstance(failures[0], StaleRoundError)


class LevelProgressionTest(unittest.TestCase):

    def setUp(self):
        self.board = MemoryLeaderboard()
        self.store = RunStore(
            leaderboard=self.board,
            random_factory=lambda: random.Random(13),
        )

    def _answer_correctly(self, run):
        return self.store.answer(
            run['run_id'],
            run['round']['round_id'],
            expected_answer(self.store, run['run_id']),
        )

    def test_three_correct_answers_advance_and_a_timeout_keeps_progress(self):
        run = self.store.create('even', 'Ada')
        run = self._answer_correctly(run)
        run = self._answer_correctly(run)

        self.assertEqual(1, run['level'])
        self.assertEqual(2, run['level_progress'])

        timed_out = self.store.answer(
            run['run_id'],
            run['round']['round_id'],
            TIMEOUT_ANSWER,
        )

        self.assertEqual(2, timed_out['lives'])
        self.assertEqual(1, timed_out['level'])
        self.assertEqual(2, timed_out['level_progress'])
        self.assertTrue(timed_out['result']['timed_out'])
        self.assertFalse(timed_out['result']['correct'])
        self.assertEqual(1, timed_out['result']['level_before'])
        self.assertEqual(1, timed_out['result']['level_after'])
        self.assertFalse(timed_out['result']['leveled_up'])

        advanced = self._answer_correctly(timed_out)
        self.assertEqual(2, advanced['level'])
        self.assertEqual(0, advanced['level_progress'])
        self.assertEqual(2, advanced['round']['level'])
        self.assertEqual(1, advanced['result']['level_before'])
        self.assertEqual(2, advanced['result']['level_after'])
        self.assertTrue(advanced['result']['leveled_up'])

    def test_default_games_stop_at_five_and_extended_games_stop_at_eight(self):
        for slug in ('calc', 'direction-focus', 'symbol-match', 'culmination'):
            with self.subTest(game=slug):
                run = self.store.create(slug, 'Ada')
                state = self.store._runs[run['run_id']]
                cap = max_level_for(slug)
                state.level = cap
                state.level_progress = CORRECT_PER_LEVEL - 1
                state.round = self.store._make_round(state)
                run = self.store._public_run(state)

                result = self._answer_correctly(run)

                self.assertEqual(cap, result['level'])
                self.assertEqual(0, result['level_progress'])
                self.assertFalse(result['result']['leveled_up'])
                self.assertEqual(cap, result['result']['level_before'])
                self.assertEqual(cap, result['result']['level_after'])
                self.assertEqual(cap, result['max_level'])

    def test_extended_games_advance_beyond_level_five(self):
        for slug in ('direction-focus', 'symbol-match', 'culmination'):
            with self.subTest(game=slug):
                run = self.store.create(slug, 'Ada')
                state = self.store._runs[run['run_id']]
                state.level = MAX_LEVEL
                state.level_progress = CORRECT_PER_LEVEL - 1
                state.round = self.store._make_round(state)

                result = self._answer_correctly(
                    self.store._public_run(state),
                )

                self.assertEqual(MAX_LEVEL + 1, result['level'])
                self.assertEqual(EXTENDED_MAX_LEVEL, result['max_level'])
                self.assertTrue(result['result']['leveled_up'])

    def test_unranked_runs_never_write_and_ruleset_scores_are_isolated(self):
        unranked = self.store.create('calc', 'Practice', ranked=False)
        self.assertFalse(unranked['ranked'])
        for _miss in range(3):
            unranked = self.store.answer(
                unranked['run_id'],
                unranked['round']['round_id'],
                TIMEOUT_ANSWER,
            )
        self.assertEqual([], self.board.records)

        self.board.record('Legacy', 'even', 999)
        ranked = self.store.create('even', 'Current')
        self.store.quit(ranked['run_id'])

        self.assertEqual(
            [{'player': 'Current', 'game': 'even', 'score': 0}],
            self.store.leaders(),
        )
        self.assertTrue(self.board.records[-1]['game'].startswith(
            SCORE_GAME_PREFIX,
        ))

    def test_ranked_argument_must_be_boolean(self):
        with self.assertRaises(TypeError):
            self.store.create('even', 'Ada', ranked='yes')

    def test_selected_start_level_is_exact_and_always_unranked(self):
        practice = self.store.create(
            'calc',
            'Practice',
            start_level=4,
        )

        self.assertEqual(4, practice['level'])
        self.assertEqual(4, practice['round']['level'])
        self.assertEqual(4, practice['round']['source_level'])
        self.assertEqual('Advanced', practice['round']['difficulty_label'])
        self.assertFalse(practice['ranked'])

        latest = practice
        for _correct in range(3):
            latest = self.store.answer(
                latest['run_id'],
                latest['round']['round_id'],
                expected_answer(self.store, latest['run_id']),
            )
        self.assertEqual(5, latest['level'])
        self.store.quit(latest['run_id'])
        self.assertEqual([], self.board.records)

    def test_level_one_remains_ranked_and_extended_games_start_at_ten(self):
        ranked = self.store.create('even', 'Ranked', start_level=1)
        spatial = self.store.create(
            'direction-focus',
            'Spatial',
            start_level=10,
        )

        self.assertTrue(ranked['ranked'])
        self.assertEqual(1, ranked['level'])
        self.assertFalse(spatial['ranked'])
        self.assertEqual(10, spatial['level'])
        self.assertEqual(10, spatial['round']['source_level'])
        self.assertEqual('Extreme', spatial['round']['difficulty_label'])

    def test_start_level_must_be_an_integer_in_the_game_range(self):
        for invalid in (None, True, False, 1.0, '2'):
            with self.subTest(start_level=invalid):
                with self.assertRaises(TypeError):
                    self.store.create(
                        'even',
                        'Ada',
                        start_level=invalid,
                    )

        for slug, invalid in (
                ('even', 0),
                ('even', 6),
                ('direction-focus', 11)):
            with self.subTest(game=slug, start_level=invalid):
                with self.assertRaises(ValueError):
                    self.store.create(
                        slug,
                        'Ada',
                        start_level=invalid,
                    )

    def test_supported_timing_modes_change_only_the_answer_window(self):
        standard = self.store.create(
            'calc',
            'Standard',
            timing_mode='standard',
        )
        self_paced = self.store.create(
            'calc',
            'Self paced',
            timing_mode='self-paced',
        )

        self.assertEqual(8000, standard['round']['time_limit_ms'])
        self.assertEqual(0, self_paced['round']['time_limit_ms'])
        self.assertEqual('self-paced', self_paced['timing_mode'])
        self.assertFalse(self_paced['ranked'])

        memory = self.store.create(
            'number-memory',
            'Memory',
            timing_mode='self-paced',
        )
        self.assertEqual(0, memory['round']['time_limit_ms'])
        self.assertEqual(1800, memory['round']['preview_ms'])

    def test_timing_mode_must_be_supported(self):
        with self.assertRaises(TypeError):
            self.store.create('even', 'Ada', timing_mode=None)
        for invalid in ('relaxed', 'turbo'):
            with self.subTest(timing_mode=invalid):
                with self.assertRaises(ValueError):
                    self.store.create(
                        'even',
                        'Ada',
                        timing_mode=invalid,
                    )


class DifficultyGeneratorTest(unittest.TestCase):

    def setUp(self):
        self.store = RunStore(
            leaderboard=MemoryLeaderboard(),
            random_factory=lambda: random.Random(29),
        )

    def _rounds(self, slug, level, count=12, progress=0):
        run = self.store.create(slug, 'Player')
        state = self.store._runs[run['run_id']]
        state.level = level
        state.level_progress = progress
        state.truth_bags = {}
        state.seen_words = set()
        state.word_history = []
        state.new_word_index = 0
        state.content_bags = {}
        state.recent_content = {}
        rounds = []
        for _index in range(count):
            state.round = self.store._make_round(state)
            rounds.append(state.round)
        return rounds

    def test_every_source_exposes_level_label_and_configured_timer(self):
        for game in CORE_GAMES:
            for level in range(1, max_level_for(game.SLUG) + 1):
                with self.subTest(game=game.SLUG, level=level):
                    game_round = self._rounds(
                        game.SLUG,
                        level,
                        count=1,
                    )[0]['public']
                    self.assertEqual(level, game_round['level'])
                    self.assertEqual(level, game_round['source_level'])
                    self.assertTrue(game_round['difficulty_label'])
                    self.assertEqual(
                        time_limit_ms(game.SLUG, level),
                        game_round['time_limit_ms'],
                    )

    def test_extended_timer_and_content_tables_have_ten_levels(self):
        self.assertEqual(EXTENDED_MAX_LEVEL, len(DIRECTION_ITEM_COUNTS))
        self.assertEqual(
            EXTENDED_MAX_LEVEL,
            len(DIRECTION_DIFFERENCES_DEG),
        )
        self.assertEqual(
            EXTENDED_MAX_LEVEL,
            len(SYMBOL_SEQUENCE_LENGTHS),
        )
        for slug in ('direction-focus', 'symbol-match'):
            with self.subTest(game=slug):
                limits = tuple(
                    time_limit_ms(slug, level)
                    for level in range(1, EXTENDED_MAX_LEVEL + 1)
                )
                self.assertEqual(EXTENDED_MAX_LEVEL, len(limits))
                self.assertTrue(all(limit > 0 for limit in limits))

    def test_even_timer_grows_with_content_complexity(self):
        self.assertEqual(
            (4000, 5000, 7000, 9000, 12000),
            tuple(
                time_limit_ms('even', level)
                for level in range(1, MAX_LEVEL + 1)
            ),
        )

    def test_balanced_truth_bags_are_random_without_pairwise_alternation(self):
        run = self.store.create('even', 'Player')
        state = self.store._runs[run['run_id']]
        state.rng = NoShuffleRandom(29)
        state.truth_bags = {}
        truths = [
            RunStore._next_balanced_truth(state, 'even', 1)
            for _index in range(10)
        ]

        self.assertEqual({True: 5, False: 5}, Counter(truths))
        self.assertTrue(any(
            first == second
            for first, second in zip(truths, truths[1:])
        ))

    def test_recent_content_guard_prevents_accidental_round_duplicates(self):
        for game in CORE_GAMES:
            if game.SLUG == 'verbal-memory':
                continue
            for level in range(1, max_level_for(game.SLUG) + 1):
                with self.subTest(game=game.SLUG, level=level):
                    run = self.store.create(game.SLUG, 'Player')
                    state = self.store._runs[run['run_id']]
                    state.level = level
                    state.level_progress = 0
                    state.truth_bags = {}
                    state.content_bags = {}
                    state.recent_content = {}
                    for _index in range(8):
                        state.round = self.store._make_round(state)
                        recent = state.recent_content[game.SLUG]
                        self.assertEqual(len(recent), len(set(recent)))
                        self.assertTrue(all(
                            len(digest) == 32
                            for digest in recent
                        ))

    def test_prime_and_scramble_content_bags_draw_without_replacement(self):
        run = self.store.create('word-scramble', 'Player')
        state = self.store._runs[run['run_id']]
        for level, words in web_engine._SCRAMBLE_WORDS_BY_LEVEL.items():
            state.content_bags = {}
            answers = [
                self.store._generate_word_scramble(
                    state,
                    level,
                )['expected_answer']
                for _index in range(len(words))
            ]
            self.assertEqual(len(words), len(set(answers)))

        for level, truth_pools in web_engine._PRIME_POOLS.items():
            for truth, numbers in truth_pools.items():
                state.content_bags = {}
                draws = [
                    RunStore._next_content(
                        state,
                        'prime:{}:{}'.format(level, int(truth)),
                        numbers,
                    )
                    for _index in range(len(numbers))
                ]
                self.assertEqual(len(numbers), len(set(draws)))

    def test_recent_guard_survives_content_bag_refills(self):
        run = self.store.create('word-scramble', 'Player')
        state = self.store._runs[run['run_id']]
        for level, words in web_engine._SCRAMBLE_WORDS_BY_LEVEL.items():
            state.content_bags = {}
            state.recent_content = {}
            recent_answers = []
            for _index in range((len(words) * 2) + 4):
                generated = self.store._generate_nonrepeating_round(
                    state,
                    'word-scramble',
                    level,
                )
                answer = generated['expected_answer']
                self.assertNotIn(answer, recent_answers[-4:])
                recent_answers.append(answer)

        for truth in (True, False):
            state.content_bags = {}
            state.recent_content = {}
            recent_numbers = []
            pool = web_engine._PRIME_POOLS[1][truth]
            for _index in range((len(pool) * 2) + 4):
                state.truth_bags = {'prime:1': [truth]}
                generated = self.store._generate_nonrepeating_round(
                    state,
                    'prime',
                    1,
                )
                number = generated['data']['number']
                self.assertNotIn(number, recent_numbers[-4:])
                recent_numbers.append(number)

    def test_gcd_recent_signature_ignores_operand_order(self):
        first = {
            'prompt': '12 18',
            'data': {'numbers': [12, 18]},
        }
        reversed_pair = {
            'prompt': '18 12',
            'data': {'numbers': [18, 12]},
        }

        self.assertEqual(
            RunStore._round_content_signature('gcd', first),
            RunStore._round_content_signature('gcd', reversed_pair),
        )

    def test_even_levels_have_correct_parity_and_balanced_answers(self):
        for level in range(1, MAX_LEVEL + 1):
            rounds = self._rounds('even', level, count=10)
            answers = []
            for game_round in rounds:
                expression = game_round['public']['data'].get(
                    'expression',
                    game_round['public']['data'].get('number'),
                )
                value = evaluate_expression(str(expression))
                expected = 'yes' if value % 2 == 0 else 'no'
                self.assertEqual(expected, game_round['expected_answer'])
                answers.append(game_round['expected_answer'])
            self.assertEqual({'yes': 5, 'no': 5}, Counter(answers))

    def test_calculator_levels_always_generate_exact_nonnegative_answers(self):
        for level in range(1, MAX_LEVEL + 1):
            for game_round in self._rounds('calc', level, count=30):
                expression = game_round['public']['data']['expression']
                calculated = evaluate_expression(expression)
                self.assertEqual(
                    calculated,
                    int(game_round['expected_answer']),
                )
                self.assertGreaterEqual(calculated, 0)

    def test_gcd_levels_construct_bounded_pairs_with_exact_answers(self):
        maximums = (96, 90, 400, 1500, 5000)
        for level, maximum in enumerate(maximums, start=1):
            for game_round in self._rounds('gcd', level, count=30):
                numbers = game_round['public']['data']['numbers']
                self.assertLessEqual(max(numbers), maximum)
                self.assertEqual(
                    gcd(*numbers),
                    int(game_round['expected_answer']),
                )

    def test_progression_levels_use_the_declared_pattern_families(self):
        validators = {
            1: self._assert_arithmetic,
            2: self._assert_arithmetic,
            3: self._assert_geometric,
            4: self._assert_interleaved,
            5: self._assert_second_difference,
        }
        patterns = {
            1: 'arithmetic',
            2: 'arithmetic',
            3: 'geometric',
            4: 'interleaved_arithmetic',
            5: 'constant_second_difference',
        }
        for level in range(1, MAX_LEVEL + 1):
            for game_round in self._rounds(
                    'progression',
                    level,
                    count=20):
                data = game_round['public']['data']
                values = list(data['sequence'])
                values[data['hidden_index']] = game_round[
                    'expected_answer'
                ]
                values = [int(value) for value in values]
                self.assertEqual(patterns[level], data['pattern'])
                self.assertTrue(data['pattern_label'])
                validators[level](values)

    def _assert_arithmetic(self, values):
        differences = [
            right - left
            for left, right in zip(values, values[1:])
        ]
        self.assertEqual(1, len(set(differences)))

    def _assert_geometric(self, values):
        ratios = [
            right // left
            for left, right in zip(values, values[1:])
        ]
        self.assertEqual(1, len(set(ratios)))

    def _assert_interleaved(self, values):
        self._assert_arithmetic(values[::2])
        self._assert_arithmetic(values[1::2])

    def _assert_second_difference(self, values):
        differences = [
            right - left
            for left, right in zip(values, values[1:])
        ]
        self._assert_arithmetic(differences)

    def test_prime_levels_are_balanced_and_respect_factor_floors(self):
        specs = web_engine._PRIME_LEVEL_SPECS
        for level, (lower, upper, minimum_factor) in specs.items():
            rounds = self._rounds('prime', level, count=20)
            answers = []
            for game_round in rounds:
                number = game_round['public']['data']['number']
                answer = game_round['expected_answer']
                self.assertGreaterEqual(number, lower)
                self.assertLessEqual(number, upper)
                self.assertEqual(
                    web_engine._is_prime(number),
                    answer == 'yes',
                )
                if answer == 'no':
                    self.assertGreaterEqual(
                        web_engine._smallest_prime_factor(number),
                        minimum_factor,
                    )
                answers.append(answer)
            self.assertEqual({'yes': 10, 'no': 10}, Counter(answers))

    def test_number_memory_uses_level_progress_digit_bands(self):
        bands = {
            1: (2, 3, 4),
            2: (5, 5, 6),
            3: (7, 7, 8),
            4: (9, 9, 10),
            5: (11, 12, 13),
        }
        for level, digits_by_progress in bands.items():
            for progress, digits in enumerate(digits_by_progress):
                game_round = self._rounds(
                    'number-memory',
                    level,
                    count=1,
                    progress=progress,
                )[0]
                public = game_round['public']
                self.assertEqual(digits, public['data']['digits'])
                self.assertEqual(digits, len(public['prompt']))
                self.assertEqual(
                    max(1800, digits * 500),
                    public['preview_ms'],
                )
                self.assertEqual(0, public['time_limit_ms'])

    def test_verbal_levels_apply_windows_lags_and_safe_words(self):
        for level in range(1, MAX_LEVEL + 1):
            rounds = self._rounds(
                'verbal-memory',
                level,
                count=30,
            )
            history = []
            seen_answers = 0
            for game_round in rounds:
                public = game_round['public']
                data = public['data']
                word = data['word']
                self.assertNotIn('-', word)
                self.assertEqual(
                    VERBAL_REPEAT_LAGS[level - 1],
                    data['minimum_repeat_lag'],
                )
                self.assertEqual(
                    VERBAL_SEEN_PERCENTAGES[level - 1],
                    data['seen_probability_percent'],
                )
                if game_round['expected_answer'] == 'yes':
                    eligible = RunStore._eligible_repeat_words(
                        history,
                        VERBAL_HISTORY_WINDOWS[level - 1],
                        VERBAL_REPEAT_LAGS[level - 1],
                    )
                    self.assertIn(word, eligible)
                    seen_answers += 1
                else:
                    self.assertNotIn(word, history)
                history.append(word)
            self.assertGreater(seen_answers, 0)

    def test_verbal_repeat_lag_uses_the_most_recent_occurrence(self):
        history = ['acorn', 'beacon', 'acorn']

        eligible = RunStore._eligible_repeat_words(
            history,
            history_window=None,
            minimum_lag=2,
        )

        self.assertNotIn('acorn', eligible)
        self.assertIn('beacon', eligible)

    def test_verbal_new_terms_remain_unique_beyond_the_base_word_list(self):
        terms = [
            RunStore._verbal_term_for_index(index)
            for index in range(5000)
        ]

        self.assertEqual(len(terms), len(set(terms)))
        self.assertTrue(all(' ' in term for term in terms))
        self.assertTrue(all('-' not in term for term in terms))

    def test_verbal_levels_balance_seen_prompts_in_twenty_round_blocks(self):
        expected_seen_counts = (7, 9, 10, 10, 10)
        seed_words = list(web_engine.brain_verbal_memory.WORDS[:20])
        for level, expected_seen in enumerate(
                expected_seen_counts,
                start=1):
            run = self.store.create('verbal-memory', 'Player')
            state = self.store._runs[run['run_id']]
            state.level = level
            state.word_history = list(seed_words)
            state.seen_words = set(seed_words)
            state.new_word_index = len(seed_words)
            state.truth_bags = {}

            answers = []
            for _index in range(20):
                state.round = self.store._make_round(state)
                answers.append(state.round['expected_answer'])
                self.assertEqual(
                    0,
                    state.round['public']['time_limit_ms'],
                )

            self.assertEqual(expected_seen, answers.count('yes'))
            self.assertEqual(20 - expected_seen, answers.count('no'))

    def test_culmination_verbal_lag_warms_up_with_source_history(self):
        run = self.store.create('culmination', 'Player')
        state = self.store._runs[run['run_id']]
        state.level = 5
        state.word_history = []
        state.seen_words = set()
        state.new_word_index = 0
        state.truth_bags = {}
        answers = []
        effective_lags = []

        for _index in range(20):
            game_round = self.store._generate_verbal_memory(state)
            answers.append(game_round['expected_answer'])
            effective_lags.append(
                game_round['data']['minimum_repeat_lag'],
            )
            self.assertEqual(
                12,
                game_round['data']['configured_repeat_lag'],
            )

        self.assertEqual('no', answers[0])
        self.assertIn('yes', answers[1:12])
        self.assertGreaterEqual(answers.count('yes'), 8)
        self.assertEqual(sorted(effective_lags), effective_lags)
        self.assertLess(effective_lags[0], effective_lags[-1])

    def test_motion_direction_levels_use_the_pure_generator_contract(self):
        for level in range(1, EXTENDED_MAX_LEVEL + 1):
            for game_round in self._rounds(
                    'direction-focus',
                    level,
                    count=8):
                public = game_round['public']
                data = public['data']
                target_items = [
                    item
                    for item in data['items']
                    if item['visual_role'] == 'target'
                ]

                self.assertEqual('motion-direction', public['kind'])
                self.assertEqual(
                    'motion_direction_2d',
                    data['render_mode'],
                )
                self.assertEqual(level, data['level_config']['level'])
                self.assertEqual(data['item_count'], len(data['items']))
                self.assertEqual(
                    data['level_config']['target_count'],
                    len(target_items),
                )
                expected_direction = game_round['expected_answer']
                self.assertTrue(all(
                    item['motion_direction'] == expected_direction
                    for item in target_items
                ))
                self.assertEqual(
                    ['up', 'right', 'down', 'left'],
                    public['choices'],
                )
                assert_no_forbidden_keys(
                    self,
                    public,
                    {'review', 'target_item_ids', 'expected_answer'},
                )

    def test_motion_direction_hard_fields_have_no_mean_or_majority_leak(self):
        for level in range(5, EXTENDED_MAX_LEVEL + 1):
            for game_round in self._rounds(
                    'direction-focus',
                    level,
                    count=24):
                items = game_round['public']['data']['items']
                counts = Counter(
                    item['motion_direction']
                    for item in items
                )
                vector_sum = [
                    sum(item['motion_vector'][axis] for item in items)
                    for axis in range(2)
                ]

                self.assertEqual(1, len(set(counts.values())))
                self.assertEqual([0, 0], vector_sum)
                self.assertTrue(
                    game_round['public']['data']['motion_balance'][
                        'is_exact'
                    ],
                )

    def test_new_memory_games_keep_preview_and_private_review_contracts(self):
        expectations = {
            'memory-matrix': ('memory-matrix', 'memory_matrix'),
            'pinball-recall': ('pinball-recall', 'pinball_recall'),
        }
        for slug, (kind, render_mode) in expectations.items():
            for level in range(1, MAX_LEVEL + 1):
                game_round = self._rounds(
                    slug,
                    level,
                    count=3,
                )[0]
                public = game_round['public']

                self.assertEqual(kind, public['kind'])
                self.assertEqual(render_mode, public['data']['render_mode'])
                self.assertGreater(public['preview_ms'], 0)
                self.assertTrue(public['hidden_prompt'])
                self.assertEqual(
                    time_limit_ms(slug, level),
                    public['time_limit_ms'],
                )
                assert_no_forbidden_keys(
                    self,
                    public,
                    {'review', 'expected_answer'},
                )

    def legacy_direction_orientation_levels_have_one_target_angle(self):
        for level in range(1, 3):
            for game_round in self._rounds(
                    'direction-focus',
                    level,
                    count=12):
                public = game_round['public']
                data = public['data']
                target_angle = web_engine._DIRECTION_ANGLES[
                    game_round['expected_answer']
                ]
                rotations = data['rotations']

                self.assertEqual('orientation', data['task_mode'])
                self.assertEqual(level, public['source_level'])
                self.assertEqual(
                    DIRECTION_ITEM_COUNTS[level - 1],
                    len(rotations),
                )
                self.assertEqual(1, rotations.count(target_angle))
                self.assertEqual(len(rotations), len(data['items']))
                self.assertEqual(
                    len(rotations),
                    len(data['accessible_sequence']),
                )
                self.assertTrue(all(
                    item['accessible_label']
                    for item in data['items']
                ))
                differences = {
                    self._angular_difference(rotation, target_angle)
                    for rotation in rotations
                    if rotation != target_angle
                }
                self.assertEqual(
                    {DIRECTION_DIFFERENCES_DEG[level - 1]},
                    differences,
                )
                assert_no_forbidden_keys(
                    self,
                    public,
                    {'target_index', 'is_target'},
                )

    def legacy_direction_two_feature_levels_require_unique_combination(self):
        for level in (3, 4):
            for game_round in self._rounds(
                    'direction-focus',
                    level,
                    count=16):
                public = game_round['public']
                data = public['data']
                items = data['items']
                combinations = Counter(
                    (item['rotation_deg'], item['frame'])
                    for item in items
                )
                unique = [
                    combination
                    for combination, count in combinations.items()
                    if count == 1
                ]
                target_angle = web_engine._DIRECTION_ANGLES[
                    game_round['expected_answer']
                ]

                self.assertEqual(
                    'two_feature_conjunction',
                    data['task_mode'],
                )
                self.assertEqual(DIRECTION_ITEM_COUNTS[level - 1], len(items))
                self.assertEqual(8, len(combinations))
                self.assertEqual(1, len(unique))
                self.assertEqual(target_angle, unique[0][0])
                self.assertTrue(all(
                    count > 1
                    for combination, count in combinations.items()
                    if combination != unique[0]
                ))
                orientation_counts = Counter(
                    item['rotation_deg']
                    for item in items
                )
                frame_counts = Counter(
                    item['frame']
                    for item in items
                )
                self.assertEqual(4, len(orientation_counts))
                self.assertEqual(
                    [len(items) // 4] * 4,
                    sorted(orientation_counts.values()),
                )
                self.assertEqual(2, len(frame_counts))
                if level == 3:
                    self.assertEqual([7, 9], sorted(frame_counts.values()))
                else:
                    self.assertEqual(
                        [len(items) // 2] * 2,
                        sorted(frame_counts.values()),
                    )
                assert_no_forbidden_keys(
                    self,
                    public,
                    {'target_index', 'is_target'},
                )

    def legacy_direction_three_feature_levels_balance_every_feature(self):
        for level in (5, 6, 7, 8):
            for game_round in self._rounds(
                    'direction-focus',
                    level,
                    count=16):
                public = game_round['public']
                data = public['data']
                items = data['items']
                combinations = Counter(
                    (
                        item['rotation_deg'],
                        item['frame'],
                        item['marker'],
                    )
                    for item in items
                )
                unique = [
                    combination
                    for combination, count in combinations.items()
                    if count == 1
                ]
                target_angle = web_engine._DIRECTION_ANGLES[
                    game_round['expected_answer']
                ]

                self.assertEqual(
                    'three_feature_conjunction',
                    data['task_mode'],
                )
                self.assertEqual(DIRECTION_ITEM_COUNTS[level - 1], len(items))
                self.assertEqual(
                    8 if level == 5 else 16,
                    len(combinations),
                )
                self.assertEqual(1, len(unique))
                self.assertEqual(target_angle, unique[0][0])
                expected_binary_count = len(items) // 2
                for feature in ('frame', 'marker'):
                    feature_counts = Counter(
                        item[feature]
                        for item in items
                    )
                    self.assertEqual(
                        [expected_binary_count, expected_binary_count],
                        sorted(feature_counts.values()),
                    )
                orientation_counts = Counter(
                    item['rotation_deg']
                    for item in items
                )
                self.assertEqual(
                    [len(items) // 4] * 4,
                    sorted(orientation_counts.values()),
                )
                assert_no_forbidden_keys(
                    self,
                    public,
                    {'target_index', 'is_target'},
                )

    def legacy_direction_conjunction_field_has_no_average_heading_leak(self):
        for level in range(3, 9):
            for game_round in self._rounds(
                    'direction-focus',
                    level,
                    count=32):
                rotations = game_round['public']['data']['rotations']
                horizontal = sum(
                    sin(radians(rotation))
                    for rotation in rotations
                )
                vertical = sum(
                    cos(radians(rotation))
                    for rotation in rotations
                )

                self.assertAlmostEqual(0.0, horizontal, places=9)
                self.assertAlmostEqual(0.0, vertical, places=9)

    def legacy_spatial_direction_feature_marginals(self):  # noqa: C901
        expected_directions = {
            'up', 'right', 'down', 'left', 'toward', 'away',
        }
        for level in (9, 10):
            for game_round in self._rounds(
                    'direction-focus',
                    level,
                    count=16):
                public = game_round['public']
                data = public['data']
                items = data['items']
                review = game_round['review']
                target = items[review['target_index']]
                feature_count = data['feature_count']

                def feature_key(item):
                    features = [
                        item['profile'],
                        item['head_style'],
                    ]
                    if feature_count == 3:
                        features.append(item['shaft_style'])
                    return tuple(features)

                feature_counts = Counter(map(feature_key, items))
                direction_counts = Counter(
                    item['direction']
                    for item in items
                )
                vector_sum = [
                    sum(item['direction_vector'][axis] for item in items)
                    for axis in range(3)
                ]

                self.assertEqual('direction_3d', data['render_mode'])
                self.assertEqual(24, len(items))
                self.assertEqual(expected_directions, set(direction_counts))
                self.assertEqual(
                    {len(items) // len(expected_directions)},
                    set(direction_counts.values()),
                )
                self.assertEqual([0, 0, 0], vector_sum)
                self.assertEqual(
                    game_round['expected_answer'],
                    target['direction'],
                )
                self.assertEqual(1, feature_counts[feature_key(target)])
                self.assertTrue(all(
                    count > 1
                    for key, count in feature_counts.items()
                    if key != feature_key(target)
                ))
                for feature in ('profile', 'head_style'):
                    marginal = Counter(
                        item[feature]
                        for item in items
                    )
                    self.assertGreater(marginal[target[feature]], 1)
                self.assertEqual(
                    [8, 8, 8],
                    sorted(Counter(
                        item['profile']
                        for item in items
                    ).values()),
                )
                self.assertEqual(
                    [12, 12],
                    sorted(Counter(
                        item['head_style']
                        for item in items
                    ).values()),
                )
                if level == 10:
                    self.assertEqual(
                        [12, 12],
                        sorted(Counter(
                            item['shaft_style']
                            for item in items
                        ).values()),
                    )
                    self.assertEqual(
                        {'short', 'long'},
                        {
                            item['shaft_style']
                            for item in items
                        },
                    )
                else:
                    self.assertEqual(
                        {'long'},
                        {
                            item['shaft_style']
                            for item in items
                        },
                    )
                self.assertEqual(
                    {'triangular', 'square', 'octagonal'},
                    {
                        item['profile']
                        for item in items
                    },
                )
                self.assertEqual(
                    {'narrow', 'wide'},
                    {
                        item['head_style']
                        for item in items
                    },
                )
                self.assertEqual(
                    (
                        'spatial_profile_head'
                        if level == 9
                        else 'spatial_profile_head_shaft'
                    ),
                    data['task_mode'],
                )
                self.assertTrue(all(
                    not {'solid', 'band', 'beacon'}.intersection(item)
                    for item in items
                ))
                self.assertTrue(all(
                    all((
                        7 <= abs(item['spin_speed_deg_s']) <= 13,
                        0 <= item['spin_phase_deg'] < 360,
                    ))
                    for item in items
                ))
                assert_no_forbidden_keys(
                    self,
                    public,
                    {
                        'review',
                        'target_index',
                        '_review_target',
                        'is_target',
                        'target_features',
                    },
                )

    def legacy_level_ten_spatial_target_requires_all_three_features(self):
        feature_names = ('profile', 'head_style', 'shaft_style')
        for game_round in self._rounds(
                'direction-focus',
                10,
                count=64):
            items = game_round['public']['data']['items']
            target = items[game_round['review']['target_index']]
            target_features = tuple(
                target[feature]
                for feature in feature_names
            )
            full_feature_counts = Counter(
                tuple(item[feature] for feature in feature_names)
                for item in items
            )
            self.assertEqual(
                1,
                full_feature_counts[target_features],
            )

            for omitted_feature in feature_names:
                retained_features = tuple(
                    feature
                    for feature in feature_names
                    if feature != omitted_feature
                )
                matches = [
                    item
                    for item in items
                    if all(
                        item[feature] == target[feature]
                        for feature in retained_features
                    )
                ]
                with self.subTest(omitted_feature=omitted_feature):
                    self.assertGreater(len(matches), 1)
                    self.assertTrue(any(
                        item[omitted_feature] != target[omitted_feature]
                        for item in matches
                    ))

    @staticmethod
    def _angular_difference(first, second):
        difference = abs(first - second)
        return min(difference, 360 - difference)

    def test_symbol_basic_levels_use_exact_comparisons(self):
        for level in range(1, 4):
            for game_round in self._rounds(
                    'symbol-match',
                    level,
                    count=10):
                public = game_round['public']
                data = public['data']
                left = data['left_symbols']
                right = data['right_symbols']
                mismatch_indices = [
                    index
                    for index, pair in enumerate(zip(left, right))
                    if pair[0] != pair[1]
                ]
                expected_mismatches = (
                    0 if game_round['expected_answer'] == 'yes' else 1
                )

                self.assertEqual('exact', data['comparison_rule'])
                self.assertEqual(
                    SYMBOL_SEQUENCE_LENGTHS[level - 1],
                    len(left),
                )
                self.assertEqual(expected_mismatches, len(mismatch_indices))
                self._assert_public_symbol_tokens(data)
                self._assert_no_symbol_answer_leak(public)
                if mismatch_indices:
                    index = mismatch_indices[0]
                    self._assert_basic_symbol_feature_change(
                        level,
                        data['left_tokens'][index],
                        data['right_tokens'][index],
                    )

    def test_symbol_arrow_levels_scale_orientation_precision(self):
        specifications = {
            4: (8, 90),
            5: (10, 45),
            6: (12, 15),
        }
        for level, (length, angle_step) in specifications.items():
            for game_round in self._rounds(
                    'symbol-match',
                    level,
                    count=10):
                public = game_round['public']
                data = public['data']
                left = [
                    token['rotation_deg']
                    for token in data['left_tokens']
                ]
                right = [
                    token['rotation_deg']
                    for token in data['right_tokens']
                ]
                violations = [
                    index
                    for index, pair in enumerate(zip(left, right))
                    if pair[0] != pair[1]
                ]
                expected_violations = (
                    0 if game_round['expected_answer'] == 'yes' else 1
                )

                self.assertEqual('exact', data['comparison_rule'])
                self.assertEqual(length, len(left))
                self.assertTrue(all(
                    angle % angle_step == 0
                    for angle in left + right
                ))
                self.assertEqual(expected_violations, len(violations))
                if violations:
                    index = violations[0]
                    self.assertEqual(
                        angle_step,
                        self._angular_difference(
                            left[index],
                            right[index],
                        ),
                    )
                self._assert_public_symbol_tokens(data)
                self._assert_no_symbol_answer_leak(public)

    def test_symbol_level_seven_applies_one_global_rotation(self):
        for game_round in self._rounds(
                'symbol-match',
                7,
                count=10):
            public = game_round['public']
            data = public['data']
            transform = data['transform_degrees']
            left = [
                token['rotation_deg']
                for token in data['left_tokens']
            ]
            right = [
                token['rotation_deg']
                for token in data['right_tokens']
            ]
            expected = [
                (angle + transform) % 360
                for angle in left
            ]
            violations = [
                index
                for index, pair in enumerate(zip(expected, right))
                if pair[0] != pair[1]
            ]
            expected_violations = (
                0 if game_round['expected_answer'] == 'yes' else 1
            )

            self.assertEqual('global_rotation', data['comparison_rule'])
            self.assertIn(transform, (90, 180, 270))
            self.assertEqual(SYMBOL_SEQUENCE_LENGTHS[6], len(left))
            self.assertEqual(expected_violations, len(violations))
            self._assert_public_symbol_tokens(data)
            self._assert_no_symbol_answer_leak(public)

    def test_symbol_level_eight_rotates_grid_positions_and_arrows(self):
        for game_round in self._rounds(
                'symbol-match',
                8,
                count=10):
            public = game_round['public']
            data = public['data']
            transform = data['transform_degrees']
            left = [
                token['rotation_deg']
                for token in data['left_tokens']
            ]
            right = [
                token['rotation_deg']
                for token in data['right_tokens']
            ]
            expected = self._rotate_test_grid(left, transform // 90)
            violations = [
                index
                for index, pair in enumerate(zip(expected, right))
                if pair[0] != pair[1]
            ]
            expected_violations = (
                0 if game_round['expected_answer'] == 'yes' else 1
            )

            self.assertEqual('grid_rotation', data['comparison_rule'])
            self.assertIn(transform, (90, 180, 270))
            self.assertEqual(3, data['pattern_columns'])
            self.assertEqual(9, len(left))
            self.assertEqual(expected_violations, len(violations))
            self._assert_public_symbol_tokens(data)
            self._assert_no_symbol_answer_leak(public)

    def test_symbol_spatial_levels_use_proper_3d_congruence(self):
        for level in (9, 10):
            for matches in (True, False):
                for seed in range(12):
                    store = RunStore(
                        leaderboard=MemoryLeaderboard(),
                        random_factory=(
                            lambda seed=seed: random.Random(seed)
                        ),
                    )
                    run = store.create('symbol-match', 'Player')
                    state = store._runs[run['run_id']]
                    state.level = level
                    state.truth_bags = {
                        'symbol-match:{}'.format(level): [matches],
                    }
                    state.recent_content = {}
                    state.round = store._make_round(state)
                    game_round = state.round
                    data = game_round['public']['data']
                    review = game_round['review']
                    left = tuple(map(tuple, data['left_cubes']))
                    right = tuple(map(tuple, data['right_cubes']))
                    left_canonical = RunStore._polycube_canonical(left)
                    right_canonical = RunStore._polycube_canonical(right)
                    canonical_matches = left_canonical == right_canonical

                    self.assertEqual('polycube_3d', data['render_mode'])
                    self.assertEqual(matches, canonical_matches)
                    self.assertEqual(matches, review['matches'])
                    self.assertEqual(
                        SYMBOL_SEQUENCE_LENGTHS[level - 1],
                        len(left),
                    )
                    self.assertTrue(RunStore._polycube_connected(left))
                    self.assertTrue(RunStore._polycube_connected(right))
                    self.assertEqual(3, len(data['spin_axis']))
                    self.assertTrue(all(
                        isinstance(value, int)
                        for value in data['spin_axis']
                    ))
                    self._assert_no_symbol_answer_leak(
                        game_round['public'],
                    )

                    if matches:
                        self.assertEqual([], review['mismatch_indices'])
                    elif level == 9:
                        self.assertEqual(1, len(review['mismatch_indices']))
                    else:
                        self.assertEqual(
                            list(range(len(right))),
                            review['mismatch_indices'],
                        )

    def test_cube_rotation_table_contains_24_unique_proper_rotations(self):
        self.assertEqual(24, len(web_engine._CUBE_ROTATIONS))
        self.assertEqual(24, len(set(web_engine._CUBE_ROTATIONS)))

    def test_symbol_truth_answers_balance_at_every_level(self):
        for level in range(1, EXTENDED_MAX_LEVEL + 1):
            answers = [
                game_round['expected_answer']
                for game_round in self._rounds(
                    'symbol-match',
                    level,
                    count=10,
                )
            ]
            self.assertEqual({'yes': 5, 'no': 5}, Counter(answers))

    def _assert_public_symbol_tokens(self, data):
        self.assertEqual(
            data['left_symbols'],
            [token['symbol'] for token in data['left_tokens']],
        )
        self.assertEqual(
            data['right_symbols'],
            [token['symbol'] for token in data['right_tokens']],
        )
        self.assertTrue(all(
            token['accessible_label']
            for token in data['left_tokens'] + data['right_tokens']
        ))

    def _assert_no_symbol_answer_leak(self, public):
        assert_no_forbidden_keys(
            self,
            public,
            {
                'answer',
                'expected_answer',
                'mismatch_index',
                'mismatch_kind',
            },
        )

    @staticmethod
    def _rotate_test_grid(angles, quarter_turns):
        rotated = list(angles)
        for _turn in range(quarter_turns):
            next_grid = [None] * 9
            for row in range(3):
                for column in range(3):
                    next_row = column
                    next_column = 2 - row
                    next_grid[(next_row * 3) + next_column] = (
                        rotated[(row * 3) + column] + 90
                    ) % 360
            rotated = next_grid
        return rotated

    def _assert_basic_symbol_feature_change(self, level, left, right):
        if level == 1:
            self.assertNotEqual(left['shape'], right['shape'])
            self.assertNotEqual(left['fill'], right['fill'])
        elif level == 2:
            self.assertNotEqual(left['shape'], right['shape'])
            self.assertEqual(left['fill'], right['fill'])
        elif level == 3:
            self.assertEqual(left['shape'], right['shape'])
            self.assertNotEqual(left['fill'], right['fill'])

    def test_scramble_pool_excludes_ambiguous_and_invalid_candidates(self):
        all_words = [
            word
            for words in web_engine._SCRAMBLE_WORDS_BY_LEVEL.values()
            for word in words
        ]
        signatures = [''.join(sorted(word)) for word in all_words]
        self.assertEqual(len(signatures), len(set(signatures)))
        removed_words = {
            'ocean', 'canoe', 'garden', 'danger',
            'silver', 'sliver', 'livers', 'ginger',
        }
        self.assertTrue(removed_words.isdisjoint(all_words))

        for (level, word), candidates in (
                web_engine._SCRAMBLE_DERANGEMENTS.items()):
            self.assertTrue(candidates)
            for candidate in candidates:
                self.assertTrue(
                    web_engine._scramble_candidate_is_valid(
                        level,
                        word,
                        candidate,
                    ),
                )

    def test_scramble_rounds_expose_controlled_shuffle_metrics(self):
        length_ranges = {
            1: (4, 5),
            2: (6, 6),
            3: (7, 7),
            4: (8, 8),
            5: (9, 10),
        }
        minimum_moved_ratios = {
            1: 0.60,
            2: 0.70,
            3: 0.80,
            4: 1.00,
            5: 1.00,
        }
        for level, (minimum, maximum) in length_ranges.items():
            for game_round in self._rounds(
                    'word-scramble',
                    level,
                    count=24):
                public = game_round['public']
                word = game_round['expected_answer']
                scrambled = public['data']['scrambled']
                self.assertGreaterEqual(len(word), minimum)
                self.assertLessEqual(len(word), maximum)
                self.assertEqual(Counter(word), Counter(scrambled))
                moved_positions, preserved_bigrams = (
                    web_engine._scramble_metrics(word, scrambled)
                )
                self.assertEqual(
                    moved_positions,
                    public['data']['moved_positions'],
                )
                self.assertEqual(
                    preserved_bigrams,
                    public['data']['preserved_bigrams'],
                )
                self.assertGreaterEqual(
                    moved_positions,
                    ceil(len(word) * minimum_moved_ratios[level]),
                )
                if level in (1, 2):
                    self.assertEqual(1, preserved_bigrams)
                elif level == 3:
                    self.assertLessEqual(preserved_bigrams, 1)
                else:
                    self.assertEqual(len(word), moved_positions)
                    self.assertEqual(0, preserved_bigrams)
                self.assertEqual(
                    level == 1,
                    public['data']['hint'] is not None,
                )


class CulminationRunTest(unittest.TestCase):

    def test_level_ten_clamps_each_source_and_uses_its_timer(self):
        source_levels = {
            'even': MAX_LEVEL,
            'direction-focus': EXTENDED_MAX_LEVEL,
            'symbol-match': EXTENDED_MAX_LEVEL,
        }
        for source_slug, source_level in source_levels.items():
            with self.subTest(source=source_slug):
                store = RunStore(
                    leaderboard=MemoryLeaderboard(),
                    random_factory=lambda: NoShuffleRandom(5),
                )
                run = store.create('culmination', 'Ada')
                state = store._runs[run['run_id']]
                state.level = EXTENDED_MAX_LEVEL
                state.level_progress = 1
                state.game_bag = [source_slug]
                state.round = store._make_round(state)
                public = state.round['public']

                self.assertEqual(EXTENDED_MAX_LEVEL, public['level'])
                self.assertEqual(source_slug, public['source_slug'])
                self.assertEqual(source_level, public['source_level'])
                self.assertEqual(
                    time_limit_ms(source_slug, source_level),
                    public['time_limit_ms'],
                )
                self.assertEqual(
                    web_engine.difficulty_label(source_level),
                    public['difficulty_label'],
                )

    def test_cycle_contains_every_core_game_before_repeating(self):
        store = RunStore(
            leaderboard=MemoryLeaderboard(),
            random_factory=lambda: NoShuffleRandom(2),
        )
        run = store.create('culmination', 'Ada')
        sources = []
        positions = []

        for _turn in range(len(CORE_GAMES) + 1):
            game_round = run['round']
            sources.append(game_round['source_slug'])
            positions.append(game_round['cycle_position'])
            answer = expected_answer(store, run['run_id'])
            run = store.answer(
                run['run_id'],
                game_round['round_id'],
                answer,
            )

        self.assertEqual(
            [game.SLUG for game in CORE_GAMES],
            sources[:len(CORE_GAMES)],
        )
        self.assertEqual(
            len(CORE_GAMES),
            len(set(sources[:len(CORE_GAMES)])),
        )
        self.assertEqual(sources[0], sources[len(CORE_GAMES)])
        self.assertEqual(
            list(range(1, len(CORE_GAMES) + 1)) + [1],
            positions,
        )
        self.assertTrue(all(
            item == len(CORE_GAMES)
            for item in [
                len(CORE_GAMES),
                run['round']['cycle_total'],
            ]
        ))

    def test_new_cycle_avoids_a_boundary_duplicate(self):
        store = RunStore(
            leaderboard=MemoryLeaderboard(),
            random_factory=lambda: BoundaryRepeatRandom(3),
        )
        run = store.create('culmination', 'Ada')
        sources = []

        for _turn in range(len(CORE_GAMES) + 1):
            sources.append(run['round']['source_slug'])
            answer = expected_answer(store, run['run_id'])
            run = store.answer(
                run['run_id'],
                run['round']['round_id'],
                answer,
            )

        self.assertNotEqual(
            sources[len(CORE_GAMES) - 1],
            sources[len(CORE_GAMES)],
        )


if __name__ == '__main__':
    unittest.main()
