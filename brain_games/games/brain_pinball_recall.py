"""Generate deterministic mirror-grid working-memory challenges."""

import random


NAME = 'Pinball Recall'
SLUG = 'pinball-recall'
CATEGORY = 'Memory'
RULES = (
    'Memorize the slash mirrors. After they disappear, trace the ball '
    'from its entry port and choose the perimeter port where it exits.'
)

RECALL_MODE = 'mirrors_then_entry'
HIDDEN_PROMPT = (
    'The mirrors are hidden. The ball enters at {entry}. '
    'Which perimeter port will it exit?'
)

LEVEL_GRID_SIZES = (4, 4, 5, 6, 7)
LEVEL_PATH_BOUNCES = (2, 3, 4, 5, 6)
LEVEL_DISTRACTOR_COUNTS = (2, 3, 5, 7, 9)
LEVEL_PREVIEW_MS = (4200, 4800, 5600, 6400, 7200)

_SIDES = ('N', 'E', 'S', 'W')
_DIRECTION_DELTAS = {
    'up': (-1, 0),
    'right': (0, 1),
    'down': (1, 0),
    'left': (0, -1),
}
_REFLECTIONS = {
    '/': {
        'up': 'right',
        'right': 'up',
        'down': 'left',
        'left': 'down',
    },
    '\\': {
        'up': 'left',
        'left': 'up',
        'down': 'right',
        'right': 'down',
    },
}
_MAX_ROUTE_SEARCHES = 50000


def _validated_grid_size(grid_size):
    if type(grid_size) is not int or grid_size < 1:
        raise ValueError('grid_size must be a positive integer')
    return grid_size


def canonical_port_label(side, index, grid_size):
    """Return a validated one-based perimeter label such as ``N3``."""
    size = _validated_grid_size(grid_size)
    normalised_side = str(side).strip().upper()
    if normalised_side not in _SIDES:
        raise ValueError('port side must be N, E, S, or W')
    if type(index) is not int or not 1 <= index <= size:
        raise ValueError('port index is outside the grid perimeter')
    return '{}{}'.format(normalised_side, index)


def perimeter_ports(grid_size):
    """Return every canonical perimeter port in stable N/E/S/W groups."""
    size = _validated_grid_size(grid_size)
    return tuple(
        canonical_port_label(side, index, size)
        for side in _SIDES
        for index in range(1, size + 1)
    )


def _normalised_port_label(port, grid_size):
    raw_label = port.get('label') if isinstance(port, dict) else port
    label = str(raw_label or '').strip().upper()
    if len(label) < 2:
        raise ValueError('entry port must be a perimeter label')
    side = label[0]
    raw_index = label[1:]
    if not raw_index.isdigit() or raw_index.startswith('0'):
        raise ValueError('entry port must use a one-based index')
    return canonical_port_label(side, int(raw_index), grid_size)


def _entry_state(grid_size, port):
    label = _normalised_port_label(port, grid_size)
    offset = int(label[1:]) - 1
    side = label[0]
    if side == 'N':
        return label, (-1, offset), 'down'
    if side == 'E':
        return label, (offset, grid_size), 'left'
    if side == 'S':
        return label, (grid_size, offset), 'up'
    return label, (offset, -1), 'right'


def _exit_label(grid_size, row, column):
    if row < 0:
        return canonical_port_label('N', column + 1, grid_size)
    if column >= grid_size:
        return canonical_port_label('E', row + 1, grid_size)
    if row >= grid_size:
        return canonical_port_label('S', column + 1, grid_size)
    if column < 0:
        return canonical_port_label('W', row + 1, grid_size)
    raise ValueError('exit coordinates are still inside the grid')


def _inside(grid_size, cell):
    row, column = cell
    return 0 <= row < grid_size and 0 <= column < grid_size


def reflect_direction(direction, orientation):
    """Reflect a travel direction from a ``/`` or ``\\`` mirror."""
    if orientation not in _REFLECTIONS:
        raise ValueError('mirror orientation must be / or \\\\')
    if direction not in _DIRECTION_DELTAS:
        raise ValueError('unknown travel direction')
    return _REFLECTIONS[orientation][direction]


def _normalised_bumpers(grid_size, bumpers):  # noqa: C901
    if not isinstance(bumpers, (list, tuple)):
        raise ValueError('bumpers must be a list')
    by_cell = {}
    for bumper in bumpers:
        if not isinstance(bumper, dict):
            raise ValueError('each bumper must be an object')
        cell = bumper.get('cell')
        if not isinstance(cell, (list, tuple)) or len(cell) != 2:
            raise ValueError('bumper cell must contain row and column')
        if any(type(coordinate) is not int for coordinate in cell):
            raise ValueError('bumper coordinates must be integers')
        normalised_cell = tuple(cell)
        if not _inside(grid_size, normalised_cell):
            raise ValueError('bumper cell is outside the grid')
        if normalised_cell in by_cell:
            raise ValueError('two bumpers cannot share a cell')
        orientation = bumper.get('orientation')
        if orientation not in _REFLECTIONS:
            raise ValueError('mirror orientation must be / or \\\\')
        by_cell[normalised_cell] = orientation
    return by_cell


def simulate_path(grid_size, bumpers, entry_port):
    """Trace a board exactly and report its exit, cells, and bounce count."""
    size = _validated_grid_size(grid_size)
    mirror_by_cell = _normalised_bumpers(size, bumpers)
    _entry, cursor, direction = _entry_state(size, entry_port)
    row, column = cursor
    visited_states = set()
    path = []
    bounce_count = 0

    while True:
        delta_row, delta_column = _DIRECTION_DELTAS[direction]
        row += delta_row
        column += delta_column
        if not _inside(size, (row, column)):
            return {
                'exit': _exit_label(size, row, column),
                'path': path,
                'bounces': bounce_count,
                'looped': False,
            }

        state = (row, column, direction)
        if state in visited_states:
            return {
                'exit': None,
                'path': path,
                'bounces': bounce_count,
                'looped': True,
            }
        visited_states.add(state)
        path.append([row, column])

        orientation = mirror_by_cell.get((row, column))
        if orientation is not None:
            direction = reflect_direction(direction, orientation)
            bounce_count += 1


def validate_board(  # noqa: C901
        grid_size,
        bumpers,
        entry_port,
        expected_exit=None,
        exact_bounces=None):
    """Validate termination plus optional exact exit and bounce invariants."""
    simulation = simulate_path(grid_size, bumpers, entry_port)
    if simulation['looped'] or simulation['exit'] is None:
        raise ValueError('the pinball path does not exit the board')
    if expected_exit is not None:
        canonical_exit = _normalised_port_label(
            expected_exit,
            grid_size,
        )
        if simulation['exit'] != canonical_exit:
            raise ValueError('the pinball exits through a different port')
    if exact_bounces is not None:
        if type(exact_bounces) is not int or exact_bounces < 0:
            raise ValueError('exact_bounces must be a non-negative integer')
        if simulation['bounces'] != exact_bounces:
            raise ValueError('the pinball has a different bounce count')
    return simulation


def _route_search(  # noqa: C901
        rng,
        grid_size,
        cursor,
        direction,
        remaining_bounces,
        visited,
        path,
        mirrors,
        maximum_path_cells,
        search_budget):
    if search_budget[0] <= 0:
        return None

    delta_row, delta_column = _DIRECTION_DELTAS[direction]
    row = cursor[0] + delta_row
    column = cursor[1] + delta_column
    ray = []
    while _inside(grid_size, (row, column)):
        if (row, column) in visited:
            break
        ray.append((row, column))
        row += delta_row
        column += delta_column

    if remaining_bounces == 0:
        if _inside(grid_size, (row, column)):
            return None
        if len(path) + len(ray) > maximum_path_cells:
            return None
        return path + ray, mirrors

    candidate_indices = list(range(len(ray)))
    rng.shuffle(candidate_indices)
    for candidate_index in candidate_indices:
        segment = ray[:candidate_index + 1]
        if len(path) + len(segment) > maximum_path_cells:
            continue
        bounce_cell = segment[-1]
        orientations = ['/', '\\']
        rng.shuffle(orientations)
        for orientation in orientations:
            search_budget[0] -= 1
            if search_budget[0] <= 0:
                return None
            outgoing = reflect_direction(direction, orientation)
            next_mirrors = dict(mirrors)
            next_mirrors[bounce_cell] = orientation
            result = _route_search(
                rng,
                grid_size,
                bounce_cell,
                outgoing,
                remaining_bounces - 1,
                visited.union(segment),
                path + segment,
                next_mirrors,
                maximum_path_cells,
                search_budget,
            )
            if result is not None:
                return result
    return None


def _construct_route(rng, grid_size, bounce_count, distractor_count):
    ports = list(perimeter_ports(grid_size))
    rng.shuffle(ports)
    maximum_path_cells = (grid_size ** 2) - distractor_count

    for entry_port in ports:
        _label, cursor, direction = _entry_state(
            grid_size,
            entry_port,
        )
        route = _route_search(
            rng,
            grid_size,
            cursor,
            direction,
            bounce_count,
            set(),
            [],
            {},
            maximum_path_cells,
            [_MAX_ROUTE_SEARCHES],
        )
        if route is not None:
            path, mirrors = route
            return entry_port, path, mirrors
    raise RuntimeError('could not construct a non-looping pinball route')


def _bumper_payload(cell, orientation):
    row, column = cell
    slash_name = 'rising slash' if orientation == '/' else 'falling slash'
    return {
        'cell': [row, column],
        'orientation': orientation,
        'accessible_label': (
            'row {}, column {}, {} mirror'
        ).format(row + 1, column + 1, slash_name),
    }


def generate_round(rng, level):
    """Generate a fully deterministic level 1-5 Pinball Recall round."""
    if type(level) is not int or not 1 <= level <= 5:
        raise ValueError('Pinball Recall level must be from 1 to 5')
    level_index = level - 1
    grid_size = LEVEL_GRID_SIZES[level_index]
    bounce_count = LEVEL_PATH_BOUNCES[level_index]
    distractor_count = LEVEL_DISTRACTOR_COUNTS[level_index]
    entry_port, constructed_path, path_mirrors = _construct_route(
        rng,
        grid_size,
        bounce_count,
        distractor_count,
    )

    path_cells = set(constructed_path)
    off_path_cells = [
        (row, column)
        for row in range(grid_size)
        for column in range(grid_size)
        if (row, column) not in path_cells
    ]
    rng.shuffle(off_path_cells)
    distractor_cells = off_path_cells[:distractor_count]
    all_mirrors = dict(path_mirrors)
    for cell in distractor_cells:
        all_mirrors[cell] = rng.choice(('/', '\\'))

    bumpers = [
        _bumper_payload(cell, orientation)
        for cell, orientation in all_mirrors.items()
    ]
    rng.shuffle(bumpers)
    simulation = validate_board(
        grid_size,
        bumpers,
        entry_port,
        exact_bounces=bounce_count,
    )
    if simulation['path'] != [
            list(cell) for cell in constructed_path
    ]:
        raise AssertionError('constructed route disagrees with simulation')

    instruction = (
        'Memorize every mirror position and slash direction. '
        'The entry port appears after the board is hidden.'
    )
    port_labels = list(perimeter_ports(grid_size))
    return {
        'kind': 'pinball-recall',
        'prompt': instruction,
        'expected_answer': simulation['exit'],
        'data': {
            'render_mode': 'pinball_recall',
            'grid_size': grid_size,
            'bumpers': bumpers,
            'entry_port': entry_port,
            'perimeter_ports': port_labels,
            'instruction': instruction,
            'accessible_instruction': (
                '{} The board is {} by {} with {} mirrors.'
            ).format(
                instruction,
                grid_size,
                grid_size,
                len(bumpers),
            ),
            'recall_mode': RECALL_MODE,
        },
        'choices': port_labels,
        'preview_ms': LEVEL_PREVIEW_MS[level_index],
        'hidden_prompt': HIDDEN_PROMPT.format(entry=entry_port),
        'review': {
            'exit': simulation['exit'],
            'path': simulation['path'],
        },
    }


def format_board(grid_size, bumpers):
    """Return a compact text board for terminal and debugging fallbacks."""
    size = _validated_grid_size(grid_size)
    mirror_by_cell = _normalised_bumpers(size, bumpers)
    rows = []
    for row in range(size):
        rows.append(' '.join(
            mirror_by_cell.get((row, column), '·')
            for column in range(size)
        ))
    return '\n'.join(rows)


def get_question_and_answer():
    """Return a basic terminal-compatible practice prompt and answer."""
    game_round = generate_round(random, 1)
    data = game_round['data']
    question = '{}\n{}\nEntry: {}\nExit port?'.format(
        RULES,
        format_board(data['grid_size'], data['bumpers']),
        data['entry_port'],
    )
    return question, game_round['expected_answer']
