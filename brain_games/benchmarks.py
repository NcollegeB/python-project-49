"""Fixed, model-based score references for BrainHacker.

The values in this module are deliberately static.  They are not collected
from players and must not be presented as population norms or scientific
measurements.  Each game has one reference round accuracy for each of its five
levels.  A player advances after every three correct answers and a run ends on
its third miss.

The score distribution is calculated deterministically from those static
assumptions, with negligible floating-point tail truncation.  This gives the
UI a stable point of comparison without allowing current players or
leaderboard activity to move the benchmark.
"""

from functools import lru_cache
import math
from dataclasses import dataclass

from brain_games.difficulty import CORRECT_PER_LEVEL
from brain_games.difficulty import MAX_LEVEL


BENCHMARK_NAME = 'BrainHacker benchmark'
BENCHMARK_METHOD = 'progressive_five_level_score_before_three_misses'
MISSES_BEFORE_END = 3
BENCHMARK_DISCLAIMER = (
    'A fixed mathematical reference, not measured population or scientific '
    'data.'
)
BENCHMARK_METHODOLOGY = (
    'Assumes independent rounds using one fixed reference accuracy at each '
    'of five levels. Every three correct answers advances a level, level 5 '
    'continues indefinitely, and a run ends after three misses.'
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
    level_accuracies: tuple


# These are product-design reference assumptions, not observed player data.
# Keep the order aligned with the public game catalog.
_SPECS = (
    _BenchmarkSpec('even', 'Even or Odd', (0.95, 0.92, 0.86, 0.78, 0.65)),
    _BenchmarkSpec('calc', 'Calculator', (0.90, 0.82, 0.72, 0.60, 0.45)),
    _BenchmarkSpec(
        'gcd',
        'Greatest Common Divisor',
        (0.88, 0.78, 0.66, 0.55, 0.42),
    ),
    _BenchmarkSpec(
        'progression',
        'Missing Progression',
        (0.90, 0.82, 0.70, 0.58, 0.45),
    ),
    _BenchmarkSpec('prime', 'Prime Number', (0.90, 0.80, 0.68, 0.55, 0.42)),
    _BenchmarkSpec(
        'number-memory',
        'Number Memory',
        (0.92, 0.82, 0.70, 0.56, 0.40),
    ),
    _BenchmarkSpec(
        'verbal-memory',
        'Verbal Memory',
        (0.94, 0.90, 0.84, 0.76, 0.65),
    ),
    _BenchmarkSpec(
        'direction-focus',
        'Direction Focus',
        (0.95, 0.88, 0.78, 0.66, 0.52),
    ),
    _BenchmarkSpec(
        'symbol-match',
        'Symbol Match',
        (0.96, 0.90, 0.82, 0.72, 0.58),
    ),
    _BenchmarkSpec(
        'word-scramble',
        'Word Scramble',
        (0.90, 0.80, 0.68, 0.55, 0.42),
    ),
    _BenchmarkSpec(
        'culmination',
        'Culmination Test',
        (0.92, 0.84, 0.73, 0.61, 0.48),
    ),
)

_SPECS_BY_SLUG = {spec.slug: spec for spec in _SPECS}


def _normalise(value):
    return str(value).strip().casefold()


def _validate_score(score):
    if isinstance(score, bool) or not isinstance(score, int):
        raise TypeError('score must be an integer')
    if score < 0:
        raise ValueError('score must not be negative')


@lru_cache(maxsize=None)
def _model_summary(level_accuracies):
    """Return ``(average, cdf_by_score)`` for a five-level score model.

    ``arrivals[m]`` is the probability of reaching the current score with
    ``m`` misses.  Before the next success, a player can miss zero or more
    times, up to the third miss that ends the run.  Carrying those three
    states forward preserves level boundaries; only a probability tail below
    1e-12 is omitted.
    """
    if len(level_accuracies) != MAX_LEVEL:
        raise ValueError('one reference accuracy is required per level')
    if any(
            not math.isfinite(accuracy) or not 0.0 < accuracy < 1.0
            for accuracy in level_accuracies
    ):
        raise ValueError('reference accuracies must be between zero and one')
    arrivals = (1.0, 0.0, 0.0)
    cumulative = 0.0
    average = 0.0
    cdf_by_score = []
    score = 0

    while sum(arrivals) > 1e-12:
        level_index = min(
            score // CORRECT_PER_LEVEL,
            len(level_accuracies) - 1,
        )
        accuracy = level_accuracies[level_index]
        miss_probability = 1.0 - accuracy
        finished_here = 0.0
        next_arrivals = [0.0, 0.0, 0.0]

        for misses, arrival_probability in enumerate(arrivals):
            misses_until_end = MISSES_BEFORE_END - misses
            terminal_path = miss_probability ** misses_until_end
            finished_here += arrival_probability * terminal_path
            for extra_misses in range(MISSES_BEFORE_END - misses):
                failure_path = miss_probability ** extra_misses
                success_path = arrival_probability * failure_path
                next_arrivals[misses + extra_misses] += (
                    success_path * accuracy
                )

        cumulative = min(1.0, cumulative + finished_here)
        cdf_by_score.append(cumulative)
        arrivals = tuple(next_arrivals)
        average += sum(arrivals)
        score += 1

    return average, tuple(cdf_by_score)


def _average_score(level_accuracies):
    average, _ = _model_summary(level_accuracies)
    return average


def _rank_out_of_100(level_accuracies, score):
    """Return the progressive score-model CDF as a whole-number rank."""
    _, cdf_by_score = _model_summary(level_accuracies)
    if score >= len(cdf_by_score):
        cumulative = 1.0
    else:
        cumulative = cdf_by_score[score]

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

    average = _average_score(spec.level_accuracies)
    result = {
        'slug': spec.slug,
        'name': spec.name,
        'benchmark_name': BENCHMARK_NAME,
        'method': BENCHMARK_METHOD,
        'misses_before_end': MISSES_BEFORE_END,
        'correct_per_level': CORRECT_PER_LEVEL,
        'level_accuracies': list(spec.level_accuracies),
        'level_accuracy_percents': [
            int(round(accuracy * 100))
            for accuracy in spec.level_accuracies
        ],
        'average_score': round(average, 1),
        'disclaimer': BENCHMARK_DISCLAIMER,
        'methodology': BENCHMARK_METHODOLOGY,
    }

    if score is not None:
        _validate_score(score)
        rank = _rank_out_of_100(spec.level_accuracies, score)
        result.update({
            'score': score,
            'percentile': rank,
            'percentile_label': '{} percentile'.format(_ordinal(rank)),
            'percentile_rank_out_of_100': rank,
            # Retained for existing clients; this is a percentile rank, not
            # conventional leaderboard placement.
            'rank_out_of_100': rank,
        })

    return result


def all_benchmarks():
    """Return fresh JSON-safe baseline data for every catalog game."""
    return [benchmark_for(spec.slug) for spec in _SPECS]
