"""Unscramble common words."""

import random


NAME = 'Word Scramble'
SLUG = 'word-scramble'
CATEGORY = 'Language'
RULES = 'Rearrange the letters to make the original word.'

# These are ordinary words selected for this project, not game-provider content.
WORDS = (
    'amber',
    'badger',
    'button',
    'cactus',
    'camera',
    'castle',
    'comet',
    'coral',
    'dolphin',
    'dragon',
    'engine',
    'fabric',
    'falcon',
    'galaxy',
    'garden',
    'ginger',
    'hammer',
    'island',
    'jungle',
    'kitten',
    'ladder',
    'magnet',
    'market',
    'meteor',
    'napkin',
    'ocean',
    'pencil',
    'pepper',
    'pillow',
    'planet',
    'puzzle',
    'rabbit',
    'rocket',
    'sailor',
    'shadow',
    'silver',
    'spider',
    'temple',
    'thunder',
    'ticket',
    'tulip',
    'valley',
    'velvet',
    'walnut',
    'window',
    'winter',
)


def scramble_word(word):
    """Return a shuffled spelling that never equals the supplied word."""
    if len(set(word)) < 2:
        raise ValueError('A scramble needs at least two different letters.')

    for _attempt in range(12):
        scrambled = ''.join(random.sample(word, len(word)))
        if scrambled != word:
            return scrambled

    # A rotation is a deterministic fallback if sampling repeatedly returns
    # the original ordering. Every word in WORDS has varied letters.
    return word[1:] + word[:1]


def get_question_and_answer():
    """Return a scrambled word and its original spelling."""
    answer = random.choice(WORDS)
    scrambled = scramble_word(answer)
    return 'Unscramble: {}'.format(scrambled), answer
