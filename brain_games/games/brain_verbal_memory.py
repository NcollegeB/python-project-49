"""Decide whether a word has already appeared in the current run."""

import random


NAME = 'Verbal Memory'
SLUG = 'verbal-memory'
CATEGORY = 'Memory'
RULES = 'Answer yes/y if the term appeared earlier, otherwise no/n.'
ANSWER_ALIASES = {
    'y': 'yes',
    'n': 'no',
}
# A small, original selection of ordinary words keeps the game self-contained.
WORDS = (
    'acorn',
    'anchor',
    'apricot',
    'basket',
    'beacon',
    'blanket',
    'breeze',
    'bridge',
    'candle',
    'canyon',
    'carpet',
    'castle',
    'cedar',
    'circle',
    'cloud',
    'copper',
    'cricket',
    'dawn',
    'drift',
    'feather',
    'fern',
    'flame',
    'forest',
    'garden',
    'harbor',
    'hazel',
    'island',
    'jacket',
    'kettle',
    'lantern',
    'lemon',
    'marble',
    'meadow',
    'mirror',
    'nectar',
    'oasis',
    'orchard',
    'pebble',
    'pepper',
    'planet',
    'pocket',
    'ribbon',
    'river',
    'saddle',
    'shadow',
    'silver',
    'spruce',
    'sunset',
    'thimble',
    'timber',
    'valley',
    'velvet',
    'willow',
    'window',
)

_seen_words = set()
_new_word_index = 0


def start_session():
    """Forget words from the previous run."""
    global _new_word_index
    _seen_words.clear()
    _new_word_index = 0


def seen_word_count():
    """Return how many distinct words have appeared this run."""
    return len(_seen_words)


def _choose_new_word():
    """Return a unique token, extending into word pairs when needed."""
    global _new_word_index
    index = _new_word_index
    _new_word_index += 1
    components = []
    word_count = len(WORDS)

    while True:
        index, remainder = divmod(index, word_count)
        components.append(WORDS[remainder])
        if index == 0:
            break
        index -= 1

    return '-'.join(reversed(components))


def get_question_and_answer():
    """Return a seen/new word prompt and remember the displayed word."""
    ask_seen = bool(_seen_words) and random.choice((True, False))

    if ask_seen:
        word = random.choice(tuple(sorted(_seen_words)))
        answer = 'yes'
    else:
        word = _choose_new_word()
        answer = 'no'

    _seen_words.add(word)
    question = 'Have you seen "{}" before? (yes/no or y/n)'.format(word)
    return question, answer
