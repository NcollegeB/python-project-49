import unittest

from brain_games.benchmarks import BENCHMARK_DISCLAIMER
from brain_games.benchmarks import BENCHMARK_METHOD
from brain_games.benchmarks import BENCHMARK_NAME
from brain_games.benchmarks import CORRECT_PER_LEVEL
from brain_games.benchmarks import MISSES_BEFORE_END
from brain_games.benchmarks import UnknownBenchmarkError
from brain_games.benchmarks import _average_score
from brain_games.benchmarks import _rank_out_of_100
from brain_games.benchmarks import all_benchmarks
from brain_games.benchmarks import benchmark_for
from brain_games.games.catalog import CORE_GAMES
from brain_games.web_engine import MAX_LIVES


class BenchmarkCatalogTest(unittest.TestCase):

    def test_benchmark_rules_match_live_gameplay_rules(self):
        self.assertEqual(MAX_LIVES, MISSES_BEFORE_END)
        self.assertEqual(3, CORRECT_PER_LEVEL)

    def test_benchmarks_cover_every_catalog_game_in_catalog_order(self):
        benchmarks = all_benchmarks()

        self.assertEqual(
            [game.SLUG for game in CORE_GAMES] + ['culmination'],
            [benchmark['slug'] for benchmark in benchmarks],
        )
        self.assertEqual(
            [game.NAME for game in CORE_GAMES] + ['Culmination Test'],
            [benchmark['name'] for benchmark in benchmarks],
        )
        self.assertEqual(11, len(benchmarks))
        self.assertEqual(11, len({item['slug'] for item in benchmarks}))

    def test_every_baseline_has_json_safe_model_metadata(self):
        expected_keys = {
            'slug',
            'name',
            'benchmark_name',
            'method',
            'misses_before_end',
            'correct_per_level',
            'level_accuracies',
            'level_accuracy_percents',
            'average_score',
            'disclaimer',
            'methodology',
        }

        for item in all_benchmarks():
            with self.subTest(game=item['slug']):
                self.assertEqual(expected_keys, set(item))
                self.assertEqual(BENCHMARK_NAME, item['benchmark_name'])
                self.assertEqual(BENCHMARK_METHOD, item['method'])
                self.assertEqual(
                    MISSES_BEFORE_END,
                    item['misses_before_end'],
                )
                self.assertEqual(
                    CORRECT_PER_LEVEL,
                    item['correct_per_level'],
                )
                self.assertEqual(BENCHMARK_DISCLAIMER, item['disclaimer'])
                self.assertIn('not measured population', item['disclaimer'])
                self.assertIn('five levels', item['methodology'])
                self.assertEqual(5, len(item['level_accuracies']))
                self.assertEqual(5, len(item['level_accuracy_percents']))
                self.assertTrue(all(
                    0.0 < accuracy < 1.0
                    for accuracy in item['level_accuracies']
                ))
                self.assertEqual(
                    sorted(item['level_accuracies'], reverse=True),
                    item['level_accuracies'],
                )
                self.assertGreater(item['average_score'], 0.0)

    def test_results_are_fresh_copies(self):
        first = all_benchmarks()
        first[0]['name'] = 'Changed'
        first.pop()

        second = all_benchmarks()

        self.assertEqual(11, len(second))
        self.assertEqual('Even or Odd', second[0]['name'])


class BenchmarkCalculationTest(unittest.TestCase):

    def test_averages_reflect_progressively_harder_levels(self):
        for item in all_benchmarks():
            with self.subTest(game=item['slug']):
                easiest_accuracy = item['level_accuracies'][0]
                numerator = MISSES_BEFORE_END * easiest_accuracy
                denominator = 1 - easiest_accuracy
                fixed_easy_average = numerator / denominator
                self.assertLess(
                    item['average_score'],
                    fixed_easy_average,
                )

        expected_averages = {
            'even': 13.9,
            'calc': 9.5,
            'gcd': 8.5,
            'progression': 9.3,
            'prime': 8.9,
            'number-memory': 9.3,
            'verbal-memory': 13.3,
            'direction-focus': 11.2,
            'symbol-match': 12.4,
            'word-scramble': 8.9,
            'culmination': 10.0,
        }
        self.assertEqual(expected_averages, {
            item['slug']: item['average_score']
            for item in all_benchmarks()
        })

    def test_constant_accuracy_reduces_to_negative_binomial_mean(self):
        self.assertAlmostEqual(3.0, _average_score((0.5,) * 5))

    def test_model_rejects_invalid_reference_accuracy_specs(self):
        invalid_specs = (
            (0.5,) * 4,
            (0.5, 0.5, 0.0, 0.5, 0.5),
            (0.5, 0.5, 1.0, 0.5, 0.5),
            (0.5, 0.5, float('nan'), 0.5, 0.5),
        )
        for spec in invalid_specs:
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError):
                    _average_score(spec)

    def test_rank_rounding_is_conventional_half_up(self):
        # At score zero with p=.5, the CDF is .5 ** 3 = 12.5%.
        self.assertEqual(13, _rank_out_of_100((0.5,) * 5, 0))

    def test_known_progressive_model_values_are_rounded_half_up(self):
        # GCD level 1 uses p=.88. At zero, CDF=(1-.88)^3=.001728.
        self.assertEqual(1, benchmark_for('gcd', 0)['percentile'])

        # One success still uses level 1: add 3 * p * (1-p)^3.
        result = benchmark_for('gcd', 1)
        self.assertEqual(1, result['percentile'])
        self.assertEqual(1, result['rank_out_of_100'])
        self.assertEqual('1st percentile', result['percentile_label'])

        # The fourth correct answer is evaluated using level 2 accuracy.
        self.assertEqual(1, benchmark_for('gcd', 2)['percentile'])
        self.assertEqual(5, benchmark_for('gcd', 3)['percentile'])

    def test_percentiles_are_deterministic_monotonic_and_bounded(self):
        for baseline in all_benchmarks():
            with self.subTest(game=baseline['slug']):
                first = [
                    benchmark_for(baseline['slug'], score)['percentile']
                    for score in range(101)
                ]
                second = [
                    benchmark_for(baseline['slug'], score)['percentile']
                    for score in range(101)
                ]

                self.assertEqual(first, second)
                self.assertEqual(first, sorted(first))
                self.assertTrue(all(1 <= value <= 100 for value in first))
                self.assertEqual(
                    100,
                    benchmark_for(baseline['slug'], 10000)['percentile'],
                )

    def test_score_result_includes_score_and_display_fields(self):
        baseline = benchmark_for(' even ')
        scored = benchmark_for(' EVEN ', 12)

        self.assertNotIn('score', baseline)
        self.assertNotIn('percentile', baseline)
        self.assertEqual(12, scored['score'])
        self.assertIsInstance(scored['percentile'], int)
        self.assertEqual(
            scored['percentile'],
            scored['percentile_rank_out_of_100'],
        )
        self.assertEqual(
            scored['percentile'],
            scored['rank_out_of_100'],
        )
        self.assertTrue(scored['percentile_label'].endswith(' percentile'))

    def test_unknown_game_has_specific_error(self):
        with self.assertRaises(UnknownBenchmarkError) as context:
            benchmark_for('missing')

        self.assertEqual('missing', context.exception.game_slug)
        self.assertIn('missing', str(context.exception))

    def test_score_must_be_a_nonnegative_integer(self):
        for invalid in (-1, 1.5, '3', True):
            with self.subTest(score=invalid):
                expected_error = ValueError if invalid == -1 else TypeError
                with self.assertRaises(expected_error):
                    benchmark_for('even', invalid)


if __name__ == '__main__':
    unittest.main()
