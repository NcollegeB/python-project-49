"""Compatibility entry point for the motion-based Direction Focus game."""

import random

from brain_games.games import brain_motion_direction as _motion


NAME = _motion.NAME
SLUG = _motion.SLUG
CATEGORY = _motion.CATEGORY
RULES = _motion.RULES
ANSWER_ALIASES = _motion.ANSWER_ALIASES
DIRECTIONS = _motion.DIRECTIONS


def generate_round(rng, level):
    """Delegate browser-style rounds to the motion-first generator."""
    return _motion.generate_round(rng, level)


def get_question_and_answer():
    """Return a text-only motion round for legacy terminal callers."""
    generated = generate_round(random, 2)
    item = generated['data']['items'][0]
    start = item['trail']['start']
    end = item['trail']['end']
    question = (
        'Tracked arrow faces {facing}. Its center moves from '
        '({start_x:.2f}, {start_y:.2f}) to '
        '({end_x:.2f}, {end_y:.2f}). Which way did it move?'
    ).format(
        facing=item['facing_direction'],
        start_x=start[0],
        start_y=start[1],
        end_x=end[0],
        end_y=end[1],
    )
    return question, generated['expected_answer']
