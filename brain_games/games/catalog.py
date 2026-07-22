"""Shared catalog of standalone Brain Games challenges."""

from brain_games.games import brain_calc
from brain_games.games import brain_direction_focus
from brain_games.games import brain_even
from brain_games.games import brain_gcd
from brain_games.games import brain_number_memory
from brain_games.games import brain_prime
from brain_games.games import brain_progression
from brain_games.games import brain_symbol_match
from brain_games.games import brain_verbal_memory
from brain_games.games import brain_word_scramble


CORE_GAMES = (
    brain_even,
    brain_calc,
    brain_gcd,
    brain_progression,
    brain_prime,
    brain_number_memory,
    brain_verbal_memory,
    brain_direction_focus,
    brain_symbol_match,
    brain_word_scramble,
)
