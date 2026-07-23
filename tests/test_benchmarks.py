import unittest

from brain_games.benchmarks import BENCHMARK_DISCLAIMER
from brain_games.benchmarks import BENCHMARK_METHOD
from brain_games.benchmarks import BENCHMARK_NAME
from brain_games.benchmarks import MISSES_BEFORE_END
from brain_games.benchmarks import UnknownBenchmarkError
from brain_games.benchmarks import all_benchmarks
from brain_games.benchmarks import benchmark_for
from brain_games.games.catalog import CORE_GAMES


class BenchmarkCatalogTest(unittest.TestCase):

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
            'reference_accuracy',
            'reference_accuracy_percent',
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
                self.assertEqual(BENCHMARK_DISCLAIMER, item['disclaimer'])
                self.assertIn('not measured population', item['disclaimer'])
                self.assertIn('3p / (1 - p)', item['methodology'])
                self.assertGreater(item['reference_accuracy'], 0.0)
                self.assertLess(item['reference_accuracy'], 1.0)
                self.assertGreater(item['average_score'], 0.0)

    def test_results_are_fresh_copies(self):
        first = all_benchmarks()
        first[0]['name'] = 'Changed'
        first.pop()

        second = all_benchmarks()

        self.assertEqual(11, len(second))
        self.assertEqual('Even or Odd', second[0]['name'])


class BenchmarkCalculationTest(unittest.TestCase):

    def test_average_is_expected_successes_before_three_misses(self):
        for item in all_benchmarks():
            with self.subTest(game=item['slug']):
                accuracy = item['reference_accuracy']
                expected = round(3 * accuracy / (1 - accuracy), 1)
                self.assertEqual(expected, item['average_score'])

        self.assertEqual(27.0, benchmark_for('even')['average_score'])
        self.assertEqual(9.0, benchmark_for('culmination')['average_score'])

    def test_known_negative_binomial_cdf_values_are_rounded_half_up(self):
        # GCD uses p=.65.  At zero successes, CDF=(1-.65)^3=.042875.
        self.assertEqual(4, benchmark_for('gcd', 0)['percentile'])

        # At one success, add 3 * p * (1-p)^3 for CDF=.12648125.
        result = benchmark_for('gcd', 1)
        self.assertEqual(13, result['percentile'])
        self.assertEqual(13, result['rank_out_of_100'])
        self.assertEqual('13th percentile', result['percentile_label'])

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
