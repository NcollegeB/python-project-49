import random
import threading
import unittest

from brain_games.games.catalog import CORE_GAMES
from brain_games.web_engine import GAME_CATALOG
from brain_games.web_engine import InvalidAnswerError
from brain_games.web_engine import RunEndedError
from brain_games.web_engine import RunStore
from brain_games.web_engine import StaleRoundError
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

    def top(self, limit=10, game=None, player=None):
        entries = self.records
        if game is not None:
            entries = [entry for entry in entries if entry['game'] == game]
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


class CatalogTest(unittest.TestCase):

    def test_catalog_includes_all_core_games_and_culmination(self):
        catalog = game_catalog()

        self.assertEqual(11, len(GAME_CATALOG))
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
                    },
                    set(game),
                )
                self.assertTrue(all(game.values()))

    def test_catalog_function_returns_fresh_mutable_copies(self):
        first = game_catalog()
        first[0]['name'] = 'Changed'
        first.pop()

        second = game_catalog()

        self.assertEqual(11, len(second))
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
                'hidden_prompt',
                'cycle_position',
                'cycle_total',
            },
            set(game_round),
        )
        self.assertEqual('even', game_round['source_slug'])
        self.assertEqual('choice', game_round['kind'])
        self.assertEqual({'number': 17}, game_round['data'])
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
            'hidden_prompt',
            'cycle_position',
            'cycle_total',
        }
        for game in CORE_GAMES:
            with self.subTest(game=game.SLUG):
                run = self.store.create(game.SLUG, 'Player')
                self.assertEqual(required_round_keys, set(run['round']))
                self.assertEqual(game.SLUG, run['round']['source_slug'])
                self.assertIsInstance(run['round']['data'], dict)
                self.assertIsInstance(run['round']['choices'], list)
                assert_no_private_answer(self, run)

    def test_answer_grades_server_side_and_moves_to_a_new_round(self):
        run = self.store.create('even', 'Ada')
        old_round = run['round']

        result = self.store.answer(
            run['run_id'],
            old_round['round_id'],
            ' N ',
        )

        self.assertEqual(1, result['score'])
        self.assertEqual(3, result['lives'])
        self.assertTrue(result['result']['correct'])
        self.assertEqual('N', result['result']['submitted_answer'])
        self.assertEqual('no', result['result']['expected_answer'])
        self.assertEqual('even', result['result']['source_slug'])
        self.assertNotEqual(
            old_round['round_id'],
            result['round']['round_id'],
        )
        assert_no_private_answer(self, result['round'])

    def test_stale_duplicate_and_invalid_choice_do_not_change_run(self):
        run = self.store.create('even', 'Ada')
        round_id = run['round']['round_id']

        with self.assertRaises(InvalidAnswerError) as invalid:
            self.store.answer(run['run_id'], round_id, 'sometimes')
        self.assertEqual(['yes', 'no'], invalid.exception.choices)

        answered = self.store.answer(run['run_id'], round_id, 'no')
        with self.assertRaises(StaleRoundError) as stale:
            self.store.answer(run['run_id'], round_id, 'no')

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
            [{'player': 'Grace', 'game': 'calc', 'score': 0}],
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
        self.assertEqual(self.board.records, self.store.leaders('PRIME'))
        self.assertEqual(
            self.board.records,
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

    def test_number_and_verbal_memory_are_isolated_between_runs(self):
        number_one = self.store.create('number-memory', 'One')
        number_two = self.store.create('number-memory', 'Two')
        number_one_next = self.store.answer(
            number_one['run_id'],
            number_one['round']['round_id'],
            number_one['round']['prompt'],
        )

        self.assertEqual(2, number_one_next['round']['data']['digits'])
        self.assertEqual(1, number_two['round']['data']['digits'])

        verbal_one = self.store.create('verbal-memory', 'One')
        verbal_two = self.store.create('verbal-memory', 'Two')
        verbal_one_next = self.store.answer(
            verbal_one['run_id'],
            verbal_one['round']['round_id'],
            'no',
        )

        self.assertEqual('acorn', verbal_one['round']['data']['word'])
        self.assertEqual('acorn', verbal_two['round']['data']['word'])
        self.assertNotEqual(
            verbal_one['round']['round_id'],
            verbal_two['round']['round_id'],
        )
        self.assertTrue(verbal_one_next['round']['data']['word'])

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
        barrier = threading.Barrier(3)
        outcomes = []

        def submit():
            barrier.wait()
            try:
                outcome = self.store.answer(
                    run['run_id'],
                    run['round']['round_id'],
                    'no',
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


class CulminationRunTest(unittest.TestCase):

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
        self.assertEqual(len(CORE_GAMES), len(set(sources[:10])))
        self.assertEqual(sources[0], sources[10])
        self.assertEqual(list(range(1, 11)) + [1], positions)
        self.assertTrue(all(
            item == len(CORE_GAMES)
            for item in [10, run['round']['cycle_total']]
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

        self.assertNotEqual(sources[9], sources[10])


if __name__ == '__main__':
    unittest.main()
