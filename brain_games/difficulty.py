"""Shared difficulty metadata for browser game runs."""

MAX_LEVEL = 5
EXTENDED_MAX_LEVEL = 8
CORRECT_PER_LEVEL = 3
TIMEOUT_ANSWER = '__brainhacker_timeout__'

_DIFFICULTY_LABELS = {
    1: 'Foundation',
    2: 'Developing',
    3: 'Skilled',
    4: 'Advanced',
    5: 'Expert',
    6: 'Master',
    7: 'Elite',
    8: 'Apex',
}

_TIME_LIMITS_MS = {
    'even': (4000, 5000, 7000, 9000, 12000),
    'calc': (8000, 10000, 14000, 18000, 25000),
    'gcd': (12000, 15000, 20000, 25000, 35000),
    'progression': (10000, 12000, 15000, 20000, 28000),
    'prime': (6000, 8000, 12000, 18000, 25000),
    'number-memory': (0, 0, 0, 0, 0),
    'verbal-memory': (0, 0, 0, 0, 0),
    'direction-focus': (
        8000, 8000, 8500, 9500, 11000, 13000, 15000, 18000,
    ),
    'symbol-match': (
        6000, 7000, 8000, 9000, 11000, 14000, 17000, 20000,
    ),
    'word-scramble': (20000, 24000, 28000, 35000, 45000),
}

_NUMBER_MEMORY_DIGITS = {
    1: (2, 3, 4),
    2: (5, 5, 6),
    3: (7, 7, 8),
    4: (9, 9, 10),
    5: (11, 12, 13),
}

VERBAL_HISTORY_WINDOWS = (4, 8, 14, 24, None)
VERBAL_REPEAT_LAGS = (1, 2, 4, 7, 12)
VERBAL_SEEN_PERCENTAGES = (35, 45, 50, 50, 50)

DIRECTION_ITEM_COUNTS = (5, 9, 16, 25, 24, 36, 36, 36)
DIRECTION_DIFFERENCES_DEG = (90, 60, 45, 30, 60, 45, 30, 15)

SYMBOL_SEQUENCE_LENGTHS = (2, 4, 6, 8, 10, 12, 10, 9)

_EXTENDED_LEVEL_GAMES = frozenset((
    'direction-focus',
    'symbol-match',
    'culmination',
))


def max_level_for(game_slug):
    """Return the authored progression cap for one public game."""
    slug = str(game_slug).strip().casefold()
    if slug in _EXTENDED_LEVEL_GAMES:
        return EXTENDED_MAX_LEVEL
    return MAX_LEVEL


def difficulty_label(level):
    """Return the short public label for a validated level."""
    return _DIFFICULTY_LABELS[level]


def time_limit_ms(game_slug, level):
    """Return a standard-mode response limit, or zero when not timed."""
    limits = _TIME_LIMITS_MS.get(game_slug)
    if limits is None:
        return 0
    if not 1 <= level <= len(limits):
        raise ValueError('level is outside the timer table')
    return limits[level - 1]


def number_memory_digits(level, level_progress):
    """Return the digit count for one Number Memory round."""
    return _NUMBER_MEMORY_DIGITS[level][level_progress]


def number_memory_preview_ms(digits):
    """Give longer numbers proportionally more encoding time."""
    return max(1800, 500 * digits)


for _game_slug, _limits in _TIME_LIMITS_MS.items():
    if len(_limits) != max_level_for(_game_slug):
        raise RuntimeError(
            '{} timer table does not match its level cap'.format(
                _game_slug,
            ),
        )

_DIRECTION_TABLE_LENGTHS = {
    len(DIRECTION_ITEM_COUNTS),
    len(DIRECTION_DIFFERENCES_DEG),
    max_level_for('direction-focus'),
}
if len(_DIRECTION_TABLE_LENGTHS) != 1:
    raise RuntimeError('Direction Focus difficulty tables are inconsistent')

if len(SYMBOL_SEQUENCE_LENGTHS) != max_level_for('symbol-match'):
    raise RuntimeError('Symbol Match difficulty table is inconsistent')
