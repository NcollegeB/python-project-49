"""Remember an increasingly long number."""

import random


NAME = 'Number Memory'
SLUG = 'number-memory'
CATEGORY = 'Memory'
RULES = 'Remember the number, then type it after it disappears.'
PREVIEW_SECONDS = 1.5
HIDDEN_QUESTION = 'What number did you see?'

MIN_DIGITS = 1
MAX_DIGITS = 18

_digit_count = MIN_DIGITS


def start_session():
    """Reset the adaptive difficulty for a new run."""
    global _digit_count
    _digit_count = MIN_DIGITS


def current_digit_count():
    """Return the number of digits used by the next question."""
    return _digit_count


def record_result(correct):
    """Make the next number longer after a hit and shorter after a miss."""
    global _digit_count
    change = 1 if correct else -1
    _digit_count = min(MAX_DIGITS, max(MIN_DIGITS, _digit_count + change))


def get_question_and_answer():
    """Return a number whose length matches the current difficulty."""
    if _digit_count == 1:
        lower_bound = 0
    else:
        lower_bound = 10 ** (_digit_count - 1)
    upper_bound = (10 ** _digit_count) - 1
    number = str(random.randint(lower_bound, upper_bound))
    return number, number
