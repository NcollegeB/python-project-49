"""Find the one arrow pointing away from its distractors."""

import random


NAME = 'Direction Focus'
SLUG = 'direction-focus'
CATEGORY = 'Attention'
RULES = 'Name the odd arrow: up/down/left/right or u/d/l/r.'
ANSWER_ALIASES = {
    'u': 'up',
    'd': 'down',
    'l': 'left',
    'r': 'right',
    '^': 'up',
    'v': 'down',
    '<': 'left',
    '>': 'right',
    '↑': 'up',
    '↓': 'down',
    '←': 'left',
    '→': 'right',
}
DIRECTIONS = {
    'up': '↑',
    'down': '↓',
    'left': '←',
    'right': '→',
}
ARROW_COUNT = 7


def get_question_and_answer():
    """Return a row containing exactly one differently directed arrow."""
    direction_names = tuple(DIRECTIONS)
    target_direction = random.choice(direction_names)
    distractor_options = tuple(
        name for name in direction_names if name != target_direction
    )
    distractor_direction = random.choice(distractor_options)
    target_index = random.randrange(ARROW_COUNT)

    arrows = [DIRECTIONS[distractor_direction]] * ARROW_COUNT
    arrows[target_index] = DIRECTIONS[target_direction]
    question = 'Find the odd arrow: {}'.format('  '.join(arrows))
    return question, target_direction
