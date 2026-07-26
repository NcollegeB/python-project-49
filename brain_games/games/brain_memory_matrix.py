"""Memorize highlighted cells in a progressively larger matrix."""

import random


NAME = 'Memory Matrix'
SLUG = 'memory-matrix'
CATEGORY = 'Memory'
RULES = (
    'Memorize the highlighted tiles, then find them one at a time after '
    'they disappear. A third missed tile costs one life.'
)
MAX_TILE_MISSES = 3

# Grid side, highlighted tiles, and preview time in milliseconds.
_LEVELS = {
    1: (3, 3, 1800),
    2: (4, 5, 1700),
    3: (5, 7, 1600),
    4: (6, 9, 1500),
    5: (7, 12, 1400),
}
_PATTERN_ATTEMPTS = 128
_FALLBACK_PATTERNS = {
    1: (0, 5, 7),
    2: (0, 3, 6, 9, 14),
    3: (0, 4, 7, 13, 16, 21, 23),
    4: (0, 5, 8, 13, 17, 22, 27, 31, 34),
    5: (0, 6, 9, 13, 16, 21, 25, 30, 34, 39, 43, 47),
}


def _is_nontrivial(indices, grid_size):
    """Reject line-only and evenly stepped patterns."""
    rows = {index // grid_size for index in indices}
    columns = {index % grid_size for index in indices}
    if len(rows) < 2 or len(columns) < 2:
        return False

    ordered = sorted(indices)
    gaps = [
        second - first
        for first, second in zip(ordered, ordered[1:])
    ]
    return len(set(gaps)) > 1


def _highlighted_indices(rng, level, grid_size, required_count):
    """Choose a reproducible, visually nontrivial set of tile indices."""
    population = range(grid_size * grid_size)
    for _attempt in range(_PATTERN_ATTEMPTS):
        indices = sorted(rng.sample(population, required_count))
        if _is_nontrivial(indices, grid_size):
            return indices
    return list(_FALLBACK_PATTERNS[level])


def generate_round(rng, level):
    """Return a JSON-safe Memory Matrix round for levels one through five."""
    if isinstance(level, bool) or not isinstance(level, int):
        raise ValueError('Memory Matrix level must be an integer from 1 to 5')
    if level not in _LEVELS:
        raise ValueError('Memory Matrix level must be an integer from 1 to 5')
    grid_size, required_count, preview_ms = _LEVELS[level]
    highlighted = _highlighted_indices(
        rng,
        level,
        grid_size,
        required_count,
    )
    expected_answer = ','.join(str(index) for index in highlighted)
    instruction = 'Memorize the highlighted tiles.'
    hidden_prompt = (
        'Find the {} highlighted tiles. Two misses are allowed.'
    ).format(required_count)
    accessible_instruction = (
        'Memorize {} highlighted tiles in a {} by {} grid, then find '
        'them one at a time after they disappear. A third missed tile '
        'costs one life.'
    ).format(required_count, grid_size, grid_size)

    return {
        'kind': 'memory-matrix',
        'prompt': instruction,
        'expected_answer': expected_answer,
        'data': {
            'render_mode': 'memory_matrix',
            'grid_size': grid_size,
            'highlighted_indices': highlighted,
            'required_count': required_count,
            'instruction': instruction,
            'accessible_instruction': accessible_instruction,
            'recall_mode': 'select_tiles',
            'interaction_mode': 'instant_tiles',
            'max_misses': MAX_TILE_MISSES,
        },
        'choices': [],
        'preview_ms': preview_ms,
        'hidden_prompt': hidden_prompt,
        'review': {
            'target_indices': list(highlighted),
            'explanation': (
                'Checks were remembered correctly, plus signs were missed, '
                'and crosses were incorrect clicks.'
            ),
        },
    }


def get_question_and_answer():
    """Return a compact level-one prompt for terminal-only callers."""
    generated = generate_round(random, 1)
    grid_size = generated['data']['grid_size']
    highlighted = set(generated['data']['highlighted_indices'])
    rows = []
    for row in range(grid_size):
        rows.append(' '.join(
            '■' if row * grid_size + column in highlighted else '□'
            for column in range(grid_size)
        ))
    question = '{}\n{}'.format(
        generated['prompt'],
        '\n'.join(rows),
    )
    return question, generated['expected_answer']
