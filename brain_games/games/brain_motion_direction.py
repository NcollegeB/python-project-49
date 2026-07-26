"""Generate motion-first Direction Focus rounds for the browser game."""

from math import ceil


NAME = 'Direction Focus'
SLUG = 'direction-focus'
CATEGORY = 'Attention'
RULES = (
    'Watch how the tracked arrow or group moves, not where the arrows '
    'face. Answer up, right, down, or left (u/r/d/l).'
)
ANSWER_ALIASES = {
    'u': 'up',
    'r': 'right',
    'd': 'down',
    'l': 'left',
    '^': 'up',
    '>': 'right',
    'v': 'down',
    '<': 'left',
    '↑': 'up',
    '→': 'right',
    '↓': 'down',
    '←': 'left',
}

DIRECTIONS = ('up', 'right', 'down', 'left')
MOTION_VECTORS = {
    'up': (0, -1),
    'right': (1, 0),
    'down': (0, 1),
    'left': (-1, 0),
}
FACING_ROTATIONS = {
    'up': 0,
    'right': 90,
    'down': 180,
    'left': 270,
}

_TRACKED_GROUP_ID = 'tracked'
_FIELD_GROUP_ID = 'field'
_FIELD_MARGIN = 0.16
_POSITION_PRECISION = 6

_LEVEL_CONFIGS = {
    1: {
        'task_mode': 'single_congruent',
        'item_count': 1,
        'target_count': 1,
        'grid_columns': 1,
        'facing_mode': 'congruent',
        'duration_ms': 1800,
        'delay_max_ms': 0,
        'travel': 0.22,
        'instruction': (
            'Which way is the arrow moving? Follow its motion.'
        ),
    },
    2: {
        'task_mode': 'single_incongruent',
        'item_count': 1,
        'target_count': 1,
        'grid_columns': 1,
        'facing_mode': 'incongruent',
        'duration_ms': 1700,
        'delay_max_ms': 0,
        'travel': 0.22,
        'instruction': (
            'Which way is the arrow moving? Ignore where it points.'
        ),
    },
    3: {
        'task_mode': 'mixed_facing_group',
        'item_count': 3,
        'target_count': 3,
        'grid_columns': 3,
        'facing_mode': 'mixed',
        'duration_ms': 1600,
        'delay_max_ms': 70,
        'travel': 0.21,
        'instruction': (
            'The arrows face different ways. Which way do they move?'
        ),
    },
    4: {
        'task_mode': 'multi_arrow_flow',
        'item_count': 6,
        'target_count': 6,
        'grid_columns': 3,
        'facing_mode': 'mixed',
        'duration_ms': 1500,
        'delay_max_ms': 90,
        'travel': 0.20,
        'instruction': (
            'Track the motion of the full group, not the arrowheads.'
        ),
    },
    5: {
        'task_mode': 'marked_group_intro',
        'item_count': 8,
        'target_count': 2,
        'grid_columns': 4,
        'facing_mode': 'decoupled',
        'duration_ms': 1400,
        'delay_max_ms': 110,
        'travel': 0.20,
        'instruction': (
            'Which way does the marked group move? Ignore every facing.'
        ),
    },
    6: {
        'task_mode': 'marked_group_distractors',
        'item_count': 12,
        'target_count': 3,
        'grid_columns': 4,
        'facing_mode': 'decoupled',
        'duration_ms': 1300,
        'delay_max_ms': 130,
        'travel': 0.19,
        'instruction': (
            'Track only the marked group through the moving field.'
        ),
    },
    7: {
        'task_mode': 'balanced_motion_field',
        'item_count': 16,
        'target_count': 4,
        'grid_columns': 4,
        'facing_mode': 'decoupled',
        'duration_ms': 1200,
        'delay_max_ms': 150,
        'travel': 0.18,
        'instruction': (
            'The field is direction-balanced. Follow the marked group.'
        ),
    },
    8: {
        'task_mode': 'dense_balanced_field',
        'item_count': 16,
        'target_count': 4,
        'grid_columns': 4,
        'facing_mode': 'decoupled',
        'duration_ms': 1080,
        'delay_max_ms': 180,
        'travel': 0.17,
        'instruction': (
            'Follow the marked group despite mixed motion and facings.'
        ),
    },
    9: {
        'task_mode': 'rapid_balanced_field',
        'item_count': 20,
        'target_count': 5,
        'grid_columns': 5,
        'facing_mode': 'decoupled',
        'duration_ms': 970,
        'delay_max_ms': 210,
        'travel': 0.16,
        'instruction': (
            'Read the marked group motion in the rapid balanced field.'
        ),
    },
    10: {
        'task_mode': 'extreme_balanced_field',
        'item_count': 24,
        'target_count': 6,
        'grid_columns': 6,
        'facing_mode': 'decoupled',
        'duration_ms': 860,
        'delay_max_ms': 240,
        'travel': 0.15,
        'instruction': (
            'Track the marked group only. Motion counts and facings are '
            'balanced decoys.'
        ),
    },
}


def _balanced_direction_sequence(rng, count):
    """Return directions whose cardinal counts differ by at most one."""
    result = []
    while len(result) < count:
        cycle = list(DIRECTIONS)
        rng.shuffle(cycle)
        result.extend(cycle)
    return result[:count]


def _motion_specs(rng, config, target_direction):
    """Build target and distractor motion with exact hard-level balance."""
    target_count = config['target_count']
    item_count = config['item_count']
    targets = [
        {
            'group_id': _TRACKED_GROUP_ID,
            'visual_role': 'target',
            'motion_direction': target_direction,
        }
        for _index in range(target_count)
    ]
    if target_count == item_count:
        return targets

    per_direction = item_count // len(DIRECTIONS)
    distractor_directions = [
        direction
        for direction in DIRECTIONS
        if direction != target_direction
        for _index in range(per_direction)
    ]
    rng.shuffle(distractor_directions)
    distractors = [
        {
            'group_id': _FIELD_GROUP_ID,
            'visual_role': 'distractor',
            'motion_direction': direction,
        }
        for direction in distractor_directions
    ]
    return targets + distractors


def _facing_directions(rng, config, specs, target_direction):
    """Create facing directions that never become a motion shortcut."""
    mode = config['facing_mode']
    if mode == 'congruent':
        return [target_direction]
    if mode == 'incongruent':
        alternatives = [
            direction
            for direction in DIRECTIONS
            if direction != target_direction
        ]
        return [rng.choice(alternatives)]
    if config['target_count'] == config['item_count']:
        return _balanced_direction_sequence(rng, len(specs))

    quota = len(specs) // len(DIRECTIONS)
    remaining = {
        direction: quota
        for direction in DIRECTIONS
    }
    target_facings = _balanced_direction_sequence(
        rng,
        config['target_count'],
    )
    for direction in target_facings:
        remaining[direction] -= 1
    distractor_facings = [
        direction
        for direction in DIRECTIONS
        for _index in range(remaining[direction])
    ]
    rng.shuffle(distractor_facings)
    return target_facings + distractor_facings


def _layout_positions(rng, count, columns, travel):
    """Return jittered normalized centers whose complete trails stay bounded."""
    if count == 1:
        return [[
            round(rng.uniform(0.36, 0.64), _POSITION_PRECISION),
            round(rng.uniform(0.36, 0.64), _POSITION_PRECISION),
        ]]

    rows = ceil(count / columns)
    margin = max(_FIELD_MARGIN, (travel / 2) + 0.025)
    x_step = (
        (1 - (2 * margin)) / (columns - 1)
        if columns > 1
        else 0
    )
    y_step = (
        (1 - (2 * margin)) / (rows - 1)
        if rows > 1
        else 0
    )
    jitter = min(
        0.018,
        x_step * 0.12 if x_step else 0.018,
        y_step * 0.12 if y_step else 0.018,
    )
    cells = [
        [
            margin + (column * x_step),
            margin + (row * y_step),
        ]
        for row in range(rows)
        for column in range(columns)
    ]
    rng.shuffle(cells)
    positions = []
    for x_value, y_value in cells[:count]:
        positions.append([
            round(
                min(
                    1 - margin,
                    max(margin, x_value + rng.uniform(-jitter, jitter)),
                ),
                _POSITION_PRECISION,
            ),
            round(
                min(
                    1 - margin,
                    max(margin, y_value + rng.uniform(-jitter, jitter)),
                ),
                _POSITION_PRECISION,
            ),
        ])
    return positions


def _trail(position, vector, travel):
    half_travel = travel / 2
    start = [
        round(
            position[axis] - (vector[axis] * half_travel),
            _POSITION_PRECISION,
        )
        for axis in range(2)
    ]
    end = [
        round(
            position[axis] + (vector[axis] * half_travel),
            _POSITION_PRECISION,
        )
        for axis in range(2)
    ]
    return {
        'start': start,
        'end': end,
        'direction_marker': 'end',
    }


def _motion_balance(items):
    counts = {
        direction: sum(
            item['motion_direction'] == direction
            for item in items
        )
        for direction in DIRECTIONS
    }
    vector_sum = [
        sum(item['motion_vector'][axis] for item in items)
        for axis in range(2)
    ]
    return {
        'counts': counts,
        'vector_sum': vector_sum,
        'is_exact': len(set(counts.values())) == 1,
    }


def generate_round(rng, level):
    """Return one deterministic-with-rng motion-direction browser round."""
    if isinstance(level, bool) or not isinstance(level, int):
        raise ValueError('level must be an integer from 1 through 10')
    if level not in _LEVEL_CONFIGS:
        raise ValueError('level must be from 1 through 10')

    config = _LEVEL_CONFIGS[level]
    target_direction = rng.choice(DIRECTIONS)
    specs = _motion_specs(rng, config, target_direction)
    facings = _facing_directions(
        rng,
        config,
        specs,
        target_direction,
    )
    entries = [
        {
            **spec,
            'facing_direction': facing,
        }
        for spec, facing in zip(specs, facings)
    ]
    rng.shuffle(entries)
    positions = _layout_positions(
        rng,
        config['item_count'],
        config['grid_columns'],
        config['travel'],
    )
    tracked_delay = (
        rng.randrange(config['delay_max_ms'] + 1)
        if config['delay_max_ms']
        else 0
    )

    items = []
    target_item_ids = []
    for index, (entry, position) in enumerate(zip(entries, positions)):
        item_id = 'motion-{:02d}'.format(index + 1)
        motion_direction = entry['motion_direction']
        motion_vector = MOTION_VECTORS[motion_direction]
        is_tracked = entry['group_id'] == _TRACKED_GROUP_ID
        delay_ms = (
            tracked_delay
            if is_tracked
            else rng.randrange(config['delay_max_ms'] + 1)
        )
        role_label = 'Tracked' if is_tracked else 'Distractor'
        item = {
            'item_id': item_id,
            'group_id': entry['group_id'],
            'visual_role': entry['visual_role'],
            'position': position,
            'motion_direction': motion_direction,
            'motion_vector': list(motion_vector),
            'facing_direction': entry['facing_direction'],
            'rotation_deg': FACING_ROTATIONS[
                entry['facing_direction']
            ],
            'glyph': '↑',
            'animation': {
                'duration_ms': config['duration_ms'],
                'delay_ms': delay_ms,
                'travel': config['travel'],
            },
            'trail': _trail(
                position,
                motion_vector,
                config['travel'],
            ),
            'accessible_label': (
                '{} arrow {} faces {} and moves {}.'
            ).format(
                role_label,
                index + 1,
                entry['facing_direction'],
                motion_direction,
            ),
        }
        items.append(item)
        if is_tracked:
            target_item_ids.append(item_id)

    balance = _motion_balance(items)
    level_config = {
        'level': level,
        'item_count': config['item_count'],
        'target_count': config['target_count'],
        'distractor_count': (
            config['item_count'] - config['target_count']
        ),
        'facing_mode': config['facing_mode'],
        'motion_balance': (
            'exact_cardinal'
            if balance['is_exact']
            else 'learning'
        ),
    }
    return {
        'kind': 'motion-direction',
        'prompt': config['instruction'],
        'expected_answer': target_direction,
        'data': {
            'render_mode': 'motion_direction_2d',
            'items': items,
            'item_count': config['item_count'],
            'grid_columns': config['grid_columns'],
            'task_mode': config['task_mode'],
            'instruction': config['instruction'],
            'accessible_instruction': config['instruction'],
            'level_config': level_config,
            'field_bounds': {
                'min_x': 0,
                'max_x': 1,
                'min_y': 0,
                'max_y': 1,
            },
            'motion_balance': balance,
            'reduced_motion': {
                'mode': 'static_trails',
                'direction_marker': 'end',
            },
        },
        'choices': list(DIRECTIONS),
        'aliases': dict(ANSWER_ALIASES),
        'review': {
            'target_group_id': _TRACKED_GROUP_ID,
            'target_item_ids': target_item_ids,
            'explanation': (
                'The marked group moved {}. Arrow facing did not '
                'determine the answer.'
            ).format(target_direction),
        },
    }
