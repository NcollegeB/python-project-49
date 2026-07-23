"""Fixed, model-based score references for BrainHacker.

The values in this module are deliberately static.  They are not collected
from players and must not be presented as population norms or scientific
measurements.  Each game has a fixed reference round accuracy ``p``.  A run
ends on its third miss, so the score (correct answers before three misses)
follows a negative-binomial model with:

    expected score = 3p / (1 - p)

The percentile is the model CDF at the supplied score, rounded to the nearest
whole rank out of 100.  This gives the UI a stable point of comparison without
allowing current players or leaderboard activity to move the benchmark.
"""

import math
from dataclasses import dataclass


BENCHMARK_NAME = 'BrainHacker benchmark'
BENCHMARK_METHOD = 'negative_binomial_score_before_three_misses'
MISSES_BEFORE_END = 3
BENCHMARK_DISCLAIMER = (
    'A fixed mathematical reference, not measured population or scientific '
    'data.'
)
BENCHMARK_METHODOLOGY = (
    'Assumes independent rounds at a fixed reference accuracy. A run ends '
    'after three misses, so expected score = 3p / (1 - p).'
)


class UnknownBenchmarkError(LookupError):
    """Raised when no BrainHacker benchmark exists for a game slug."""

    def __init__(self, game_slug):
        self.game_slug = game_slug
        super().__init__('Unknown benchmark: {}'.format(game_slug))


@dataclass(frozen=True)
class _BenchmarkSpec:
    slug: str
    name: str
    reference_accuracy: float


# These are product-design reference assumptions, not observed player data.
# Keep the order aligned with the public game catalog.
_SPECS = (
    _BenchmarkSpec('even', 'Even or Odd', 0.90),
    _BenchmarkSpec('calc', 'Calculator', 0.72),
    _BenchmarkSpec('gcd', 'Greatest Common Divisor', 0.65),
    _BenchmarkSpec('progression', 'Missing Progression', 0.75),
    _BenchmarkSpec('prime', 'Prime Number', 0.68),
    _BenchmarkSpec('number-memory', 'Number Memory', 0.67),
    _BenchmarkSpec('verbal-memory', 'Verbal Memory', 0.74),
    _BenchmarkSpec('direction-focus', 'Direction Focus', 0.88),
    _BenchmarkSpec('symbol-match', 'Symbol Match', 0.90),
    _BenchmarkSpec('word-scramble', 'Word Scramble', 0.62),
    _BenchmarkSpec('culmination', 'Culmination Test', 0.75),
)

_SPECS_BY_SLUG = {spec.slug: spec for spec in _SPECS}


def _normalise(value):
    return str(value).strip().casefold()


def _validate_score(score):
    if isinstance(score, bool) or not isinstance(score, int):
        raise TypeError('score must be an integer')
    if score < 0:
        raise ValueError('score must not be negative')


def _average_score(reference_accuracy):
    numerator = MISSES_BEFORE_END * reference_accuracy
    return numerator / (1.0 - reference_accuracy)


def _rank_out_of_100(reference_accuracy, score):
    """Return the negative-binomial CDF as a whole-number rank.

    The recurrence avoids factorial-sized intermediate values.  Once the CDF
    is numerically indistinguishable from one, even extremely large scores can
    finish without iterating all the way to ``score``.
    """
    miss_probability = 1.0 - reference_accuracy
    probability = miss_probability ** MISSES_BEFORE_END
    cumulative = 0.0

    for successes in range(score + 1):
        cumulative += probability
        if cumulative >= 1.0 - 1e-12:
            return 100
        numerator = reference_accuracy * (
            successes + MISSES_BEFORE_END
        )
        probability *= numerator / (successes + 1)

    # Use conventional half-up rounding instead of Python's bankers rounding.
    rank = int(math.floor((100.0 * cumulative) + 0.5))
    return min(100, max(1, rank))


def _ordinal(number):
    if 10 <= number % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th')
    return '{}{}'.format(number, suffix)


def benchmark_for(game_slug, score=None):
    """Return a JSON-safe BrainHacker benchmark for one game.

    ``score`` is optional.  When supplied, the result also includes the fixed
    model percentile and equivalent rank out of 100.
    """
    slug = _normalise(game_slug)
    try:
        spec = _SPECS_BY_SLUG[slug]
    except KeyError as error:
        raise UnknownBenchmarkError(game_slug) from error

    average = _average_score(spec.reference_accuracy)
    result = {
        'slug': spec.slug,
        'name': spec.name,
        'benchmark_name': BENCHMARK_NAME,
        'method': BENCHMARK_METHOD,
        'misses_before_end': MISSES_BEFORE_END,
        'reference_accuracy': spec.reference_accuracy,
        'reference_accuracy_percent': int(
            round(spec.reference_accuracy * 100),
        ),
        'average_score': round(average, 1),
        'disclaimer': BENCHMARK_DISCLAIMER,
        'methodology': BENCHMARK_METHODOLOGY,
    }

    if score is not None:
        _validate_score(score)
        rank = _rank_out_of_100(spec.reference_accuracy, score)
        result.update({
            'score': score,
            'percentile': rank,
            'percentile_label': '{} percentile'.format(_ordinal(rank)),
            'rank_out_of_100': rank,
        })

    return result


def all_benchmarks():
    """Return fresh JSON-safe baseline data for every catalog game."""
    return [benchmark_for(spec.slug) for spec in _SPECS]
