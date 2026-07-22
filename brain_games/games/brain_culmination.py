"""Mix every Brain Games challenge into one endless test."""

import random

from brain_games.games.catalog import CORE_GAMES


NAME = 'Culmination Test'
SLUG = 'culmination'
CATEGORY = 'Mixed'
RULES = 'Every round comes from a different Brain Games challenge.'

SOURCE_GAMES = CORE_GAMES

_game_bag = []
_active_game = None


def _run_hook(game, hook_name):
    hook = getattr(game, hook_name, None)
    if callable(hook):
        hook()


def start_session():
    """Reset every source game and start a fresh shuffled rotation."""
    global _active_game
    _game_bag.clear()
    _active_game = None
    for game in SOURCE_GAMES:
        _run_hook(game, 'start_session')


def _refill_game_bag():
    _game_bag.extend(SOURCE_GAMES)
    random.shuffle(_game_bag)
    if _active_game is not None and len(_game_bag) > 1:
        if _game_bag[0] is _active_game:
            _game_bag[0], _game_bag[1] = _game_bag[1], _game_bag[0]


def get_active_game():
    """Return the source game used by the current round."""
    return _active_game


def get_question_and_answer():
    """Choose each source game once per shuffled ten-round cycle."""
    global _active_game
    if not _game_bag:
        _refill_game_bag()
    _active_game = _game_bag.pop(0)
    return _active_game.get_question_and_answer()
