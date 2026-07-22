"""Quickly decide whether two displayed symbols match."""

import random


NAME = 'Symbol Match'
SLUG = 'symbol-match'
CATEGORY = 'Attention'
RULES = 'Answer yes/y if the symbols match, otherwise no/n.'
ANSWER_ALIASES = {
    'y': 'yes',
    'n': 'no',
}
SYMBOLS = (
    '○',
    '●',
    '□',
    '■',
    '△',
    '▲',
    '◇',
    '◆',
    '☆',
    '★',
)


def get_question_and_answer():
    """Return a symbol pair that is either equal or deliberately different."""
    left_symbol = random.choice(SYMBOLS)
    symbols_match = random.choice((True, False))
    if symbols_match:
        right_symbol = left_symbol
    else:
        alternatives = tuple(
            symbol for symbol in SYMBOLS if symbol != left_symbol
        )
        right_symbol = random.choice(alternatives)

    question = 'Symbols: {}  |  {}. Same? (yes/no or y/n)'.format(
        left_symbol,
        right_symbol,
    )
    answer = 'yes' if symbols_match else 'no'
    return question, answer
