"""Server-side game engine for the browser interface.

The terminal games predate the web application and some of them keep session
state in module globals.  This module deliberately owns all state per run so
that concurrent browser sessions cannot affect one another.
"""

import copy
from hashlib import blake2s
from itertools import permutations
from itertools import product
import json
from math import ceil
from math import gcd
from math import isqrt
import random
import threading
import uuid

from brain_games.difficulty import CORRECT_PER_LEVEL
from brain_games.difficulty import DIRECTION_DIFFERENCES_DEG
from brain_games.difficulty import DIRECTION_ITEM_COUNTS
from brain_games.difficulty import difficulty_label
from brain_games.difficulty import max_level_for
from brain_games.difficulty import number_memory_digits
from brain_games.difficulty import number_memory_preview_ms
from brain_games.difficulty import SYMBOL_SEQUENCE_LENGTHS
from brain_games.difficulty import time_limit_ms
from brain_games.difficulty import TIMEOUT_ANSWER
from brain_games.difficulty import VERBAL_HISTORY_WINDOWS
from brain_games.difficulty import VERBAL_REPEAT_LAGS
from brain_games.difficulty import VERBAL_SEEN_PERCENTAGES
from brain_games.games import brain_calc
from brain_games.games import brain_direction_focus
from brain_games.games import brain_even
from brain_games.games import brain_gcd
from brain_games.games import brain_memory_matrix
from brain_games.games import brain_motion_direction
from brain_games.games import brain_number_memory
from brain_games.games import brain_pinball_recall
from brain_games.games import brain_prime
from brain_games.games import brain_progression
from brain_games.games import brain_symbol_match
from brain_games.games import brain_verbal_memory
from brain_games.games import brain_word_scramble
from brain_games.games.catalog import CORE_GAMES
from brain_games.leaderboard import Leaderboard


MAX_LIVES = 3
CULMINATION_SLUG = 'culmination'
DEFAULT_MAX_RUNS = 512
MAX_PLAYER_LENGTH = 64
SCORE_RULESET = 'r4'
SCORE_GAME_PREFIX = '{}:'.format(SCORE_RULESET)
TIMING_MODES = ('standard', 'self-paced')
RESTORABLE_TIMING_MODES = TIMING_MODES + ('relaxed',)
RECENT_CONTENT_LIMIT = 4
ROUND_GENERATION_ATTEMPTS = 8


class UnknownGameError(LookupError):
    """Raised when a game slug is not in the public catalog."""

    def __init__(self, game_slug):
        self.game_slug = game_slug
        super().__init__('Unknown game: {}'.format(game_slug))


class UnknownRunError(LookupError):
    """Raised when a run id is unknown to this store."""

    def __init__(self, run_id):
        self.run_id = run_id
        super().__init__('Unknown run: {}'.format(run_id))


class StaleRoundError(RuntimeError):
    """Raised when an answer targets an old or otherwise invalid round."""

    def __init__(self, run_id, round_id, current_round_id=None):
        self.run_id = run_id
        self.round_id = round_id
        self.current_round_id = current_round_id
        super().__init__('Round {} is no longer active'.format(round_id))


class RunEndedError(RuntimeError):
    """Raised when an answer is submitted after a run has ended."""

    def __init__(self, run_id):
        self.run_id = run_id
        super().__init__('Run has ended: {}'.format(run_id))


class InvalidAnswerError(ValueError):
    """Raised when an answer is blank or is not an available choice."""

    def __init__(self, answer, choices=None):
        self.answer = answer
        self.choices = list(choices or [])
        if self.choices:
            message = 'Answer must be one of: {}'.format(
                ', '.join(self.choices),
            )
        else:
            message = 'Answer must not be blank'
        super().__init__(message)


def _catalog_entry(game, description, icon):
    return {
        'slug': game.SLUG,
        'name': game.NAME,
        'category': game.CATEGORY,
        'rules': game.RULES,
        'description': description,
        'icon': icon,
        'max_level': max_level_for(game.SLUG),
    }


GAME_CATALOG = (
    _catalog_entry(
        brain_even,
        'Classify numbers as even or odd.',
        '÷2',
    ),
    _catalog_entry(
        brain_calc,
        'Solve a stream of quick arithmetic expressions.',
        '+−×',
    ),
    _catalog_entry(
        brain_gcd,
        'Find the greatest common divisor of two numbers.',
        'GCD',
    ),
    _catalog_entry(
        brain_progression,
        'Recover the missing value in a number sequence.',
        '…',
    ),
    _catalog_entry(
        brain_prime,
        'Decide whether each number is prime.',
        'P',
    ),
    _catalog_entry(
        brain_number_memory,
        'Remember numbers that adapt to your performance.',
        '123',
    ),
    _catalog_entry(
        brain_verbal_memory,
        'Track which words have appeared during this run.',
        'Aa',
    ),
    _catalog_entry(
        brain_motion_direction,
        'Track marked motion while arrow facings try to distract you.',
        '→',
    ),
    _catalog_entry(
        brain_symbol_match,
        'Compare symbols, rotated grids, and 3D cube solids.',
        '◇',
    ),
    _catalog_entry(
        brain_word_scramble,
        'Rearrange shuffled letters into the original word.',
        'ABC',
    ),
    _catalog_entry(
        brain_memory_matrix,
        'Memorize highlighted tiles, then rebuild the pattern.',
        '▦',
    ),
    _catalog_entry(
        brain_pinball_recall,
        'Memorize mirrors, then trace the hidden pinball route.',
        '◩',
    ),
    {
        'slug': CULMINATION_SLUG,
        'name': 'Culmination Test',
        'category': 'Mixed',
        'rules': (
            'Every round comes from a different BrainHacker test.'
        ),
        'description': 'Take on all twelve challenges in shuffled cycles.',
        'icon': '★',
        'max_level': max_level_for(CULMINATION_SLUG),
    },
)

_CATALOG_BY_SLUG = {
    entry['slug']: entry
    for entry in GAME_CATALOG
}
_CORE_SLUGS = tuple(game.SLUG for game in CORE_GAMES)


def game_catalog():
    """Return a JSON-safe copy of the public game catalog."""
    return copy.deepcopy(list(GAME_CATALOG))


def _normalise(value):
    return str(value).strip().casefold()


def _new_id():
    return uuid.uuid4().hex


def _number_with_parity(rng, lower_bound, upper_bound, parity):
    """Return a uniformly selected integer with the requested parity."""
    first = lower_bound
    if first % 2 != parity:
        first += 1
    count = ((upper_bound - first) // 2) + 1
    return first + (2 * rng.randrange(count))


def _coprime_pair(rng, lower_bound, upper_bound):
    """Return two distinct coprime values in the inclusive range."""
    for _attempt in range(128):
        first = rng.randint(lower_bound, upper_bound)
        second = rng.randint(lower_bound, upper_bound)
        if first != second and gcd(first, second) == 1:
            return first, second

    for first in range(lower_bound, upper_bound + 1):
        for second in range(first + 1, upper_bound + 1):
            if gcd(first, second) == 1:
                return first, second
    raise ValueError('range does not contain a coprime pair')


def _is_prime(number):
    if number < 2:
        return False
    if number == 2:
        return True
    if number % 2 == 0:
        return False
    for divisor in range(3, isqrt(number) + 1, 2):
        if number % divisor == 0:
            return False
    return True


def _smallest_prime_factor(number):
    if number % 2 == 0:
        return 2
    for divisor in range(3, isqrt(number) + 1, 2):
        if number % divisor == 0:
            return divisor
    return number


_PRIME_LEVEL_SPECS = {
    1: (2, 50, 2),
    2: (51, 199, 3),
    3: (200, 999, 7),
    4: (1000, 4999, 11),
    5: (5000, 9999, 29),
}


def _build_prime_pools():
    pools = {}
    for level, (lower_bound, upper_bound, minimum_factor) in (
            _PRIME_LEVEL_SPECS.items()):
        primes = []
        composites = []
        for number in range(lower_bound, upper_bound + 1):
            if _is_prime(number):
                primes.append(number)
            elif _smallest_prime_factor(number) >= minimum_factor:
                composites.append(number)
        pools[level] = {
            True: tuple(primes),
            False: tuple(composites),
        }
    return pools


_PRIME_POOLS = _build_prime_pools()

_DIRECTION_ANGLES = {
    'up': 0,
    'right': 90,
    'down': 180,
    'left': 270,
}

_SPATIAL_DIRECTIONS = {
    'up': {
        'vector': (0, 1, 0),
        'glyph': '↑',
        'label': 'up',
    },
    'right': {
        'vector': (1, 0, 0),
        'glyph': '→',
        'label': 'right',
    },
    'down': {
        'vector': (0, -1, 0),
        'glyph': '↓',
        'label': 'down',
    },
    'left': {
        'vector': (-1, 0, 0),
        'glyph': '←',
        'label': 'left',
    },
    'toward': {
        'vector': (0, 0, 1),
        'glyph': '⊙',
        'label': 'toward you',
    },
    'away': {
        'vector': (0, 0, -1),
        'glyph': '⊗',
        'label': 'away from you',
    },
}

_CUBE_NEIGHBOURS = (
    (1, 0, 0),
    (-1, 0, 0),
    (0, 1, 0),
    (0, -1, 0),
    (0, 0, 1),
    (0, 0, -1),
)


def _permutation_sign(indices):
    inversions = sum(
        indices[first] > indices[second]
        for first in range(len(indices))
        for second in range(first + 1, len(indices))
    )
    return -1 if inversions % 2 else 1


def _build_cube_rotations():
    """Return the 24 orientation-preserving symmetries of a cube."""
    rotations = []
    for axes in permutations(range(3)):
        axis_sign = _permutation_sign(axes)
        for signs in product((-1, 1), repeat=3):
            if axis_sign * signs[0] * signs[1] * signs[2] != 1:
                continue
            rotations.append(tuple(
                tuple(
                    signs[row] if column == axes[row] else 0
                    for column in range(3)
                )
                for row in range(3)
            ))
    if len(rotations) != 24:
        raise RuntimeError('cube rotation table must contain 24 entries')
    return tuple(rotations)


_CUBE_ROTATIONS = _build_cube_rotations()

_SYMBOL_TOKENS = {
    '○': {
        'shape': 'circle',
        'fill': 'outline',
        'rotation_deg': 0,
        'internal_mark': 'none',
        'accessible_label': 'outline circle',
    },
    '●': {
        'shape': 'circle',
        'fill': 'solid',
        'rotation_deg': 0,
        'internal_mark': 'none',
        'accessible_label': 'solid circle',
    },
    '□': {
        'shape': 'square',
        'fill': 'outline',
        'rotation_deg': 0,
        'internal_mark': 'none',
        'accessible_label': 'outline square',
    },
    '■': {
        'shape': 'square',
        'fill': 'solid',
        'rotation_deg': 0,
        'internal_mark': 'none',
        'accessible_label': 'solid square',
    },
    '△': {
        'shape': 'triangle',
        'fill': 'outline',
        'rotation_deg': 0,
        'internal_mark': 'none',
        'accessible_label': 'outline upward triangle',
    },
    '▲': {
        'shape': 'triangle',
        'fill': 'solid',
        'rotation_deg': 0,
        'internal_mark': 'none',
        'accessible_label': 'solid upward triangle',
    },
    '◇': {
        'shape': 'diamond',
        'fill': 'outline',
        'rotation_deg': 0,
        'internal_mark': 'none',
        'accessible_label': 'outline diamond',
    },
    '◆': {
        'shape': 'diamond',
        'fill': 'solid',
        'rotation_deg': 0,
        'internal_mark': 'none',
        'accessible_label': 'solid diamond',
    },
    '☆': {
        'shape': 'star',
        'fill': 'outline',
        'rotation_deg': 0,
        'internal_mark': 'none',
        'accessible_label': 'outline star',
    },
    '★': {
        'shape': 'star',
        'fill': 'solid',
        'rotation_deg': 0,
        'internal_mark': 'none',
        'accessible_label': 'solid star',
    },
    '▶': {
        'shape': 'triangle',
        'fill': 'solid',
        'rotation_deg': 90,
        'internal_mark': 'none',
        'accessible_label': 'solid right-pointing triangle',
    },
    '▼': {
        'shape': 'triangle',
        'fill': 'solid',
        'rotation_deg': 180,
        'internal_mark': 'none',
        'accessible_label': 'solid downward triangle',
    },
    '◀': {
        'shape': 'triangle',
        'fill': 'solid',
        'rotation_deg': 270,
        'internal_mark': 'none',
        'accessible_label': 'solid left-pointing triangle',
    },
    '⊙': {
        'shape': 'circle',
        'fill': 'outline',
        'rotation_deg': 0,
        'internal_mark': 'dot',
        'accessible_label': 'circle with center dot',
    },
    '⊗': {
        'shape': 'circle',
        'fill': 'outline',
        'rotation_deg': 0,
        'internal_mark': 'cross',
        'accessible_label': 'circle with center cross',
    },
    '⊕': {
        'shape': 'circle',
        'fill': 'outline',
        'rotation_deg': 0,
        'internal_mark': 'plus',
        'accessible_label': 'circle with center plus',
    },
    '⊖': {
        'shape': 'circle',
        'fill': 'outline',
        'rotation_deg': 0,
        'internal_mark': 'minus',
        'accessible_label': 'circle with center minus',
    },
}

_SYMBOL_STANDARD_TOKENS = tuple(brain_symbol_match.SYMBOLS)
_SYMBOL_ROTATION_TOKENS = ('▲', '▶', '▼', '◀')
_SYMBOL_MARK_TOKENS = ('⊙', '⊗', '⊕', '⊖')
_SYMBOL_ROTATION_PARTNERS = {
    '▲': '▶',
    '▶': '▼',
    '▼': '◀',
    '◀': '▲',
}
_SYMBOL_MARK_PARTNERS = {
    '⊙': '⊗',
    '⊗': '⊙',
    '⊕': '⊖',
    '⊖': '⊕',
}

_VERBAL_DESCRIPTORS = (
    'amber',
    'ancient',
    'autumn',
    'blue',
    'bold',
    'bright',
    'calm',
    'clear',
    'cool',
    'coral',
    'crisp',
    'dark',
    'deep',
    'early',
    'gentle',
    'golden',
    'green',
    'hidden',
    'ivory',
    'light',
    'little',
    'misty',
    'narrow',
    'quiet',
    'red',
    'round',
    'silver',
    'soft',
    'still',
    'warm',
    'wild',
    'young',
)

_SCRAMBLE_WORDS_BY_LEVEL = {
    1: (
        'lamp', 'mint', 'bread', 'brick', 'chair', 'cloud',
        'flame', 'lemon', 'piano', 'stone', 'tiger', 'whale',
    ),
    2: (
        'beacon', 'cactus', 'camera', 'castle', 'fabric', 'falcon',
        'jungle', 'kitten', 'ladder', 'magnet', 'market', 'meteor',
        'napkin', 'pencil', 'pillow', 'planet', 'puzzle', 'rabbit',
        'rocket', 'sailor', 'shadow', 'spider', 'temple', 'ticket',
        'valley', 'velvet', 'walnut', 'window', 'winter',
    ),
    3: (
        'apricot', 'blanket', 'compass', 'cricket', 'diamond',
        'dolphin', 'emerald', 'feather', 'journey', 'lantern',
        'orchard', 'popcorn', 'rainbow', 'sunrise', 'thunder',
        'tractor', 'volcano', 'whisper',
    ),
    4: (
        'airplane', 'backpack', 'building', 'calendar', 'computer',
        'dinosaur', 'elephant', 'firework', 'football', 'hospital',
        'kangaroo', 'keyboard', 'medicine', 'mountain', 'notebook',
        'painting', 'sandwich', 'shoulder', 'stairway', 'treasure',
        'triangle', 'umbrella',
    ),
    5: (
        'adventure', 'basketball', 'butterfly', 'chocolate',
        'crocodile', 'detective', 'education', 'furniture',
        'helicopter', 'jellyfish', 'lighthouse', 'microscope',
        'newspaper', 'pineapple', 'playground', 'skateboard',
        'snowflake', 'spaceship', 'strawberry', 'telescope',
        'watermelon',
    ),
}

_SCRAMBLE_LEVEL_CONSTRAINTS = {
    1: {
        'minimum_moved_ratio': 0.60,
        'preserved_bigrams': 1,
    },
    2: {
        'minimum_moved_ratio': 0.70,
        'preserved_bigrams': 1,
    },
    3: {
        'minimum_moved_ratio': 0.80,
        'maximum_preserved_bigrams': 1,
    },
    4: {
        'minimum_moved_ratio': 1.00,
        'preserved_bigrams': 0,
    },
    5: {
        'minimum_moved_ratio': 1.00,
        'preserved_bigrams': 0,
    },
}


def _scramble_metrics(word, candidate):
    moved_positions = sum(
        original != shuffled
        for original, shuffled in zip(word, candidate)
    )
    original_bigrams = {
        word[index:index + 2]
        for index in range(len(word) - 1)
    }
    preserved_bigrams = sum(
        candidate[index:index + 2] in original_bigrams
        for index in range(len(candidate) - 1)
    )
    return moved_positions, preserved_bigrams


def _scramble_candidate_is_valid(level, word, candidate):
    constraints = _SCRAMBLE_LEVEL_CONSTRAINTS[level]
    moved_positions, preserved_bigrams = _scramble_metrics(
        word,
        candidate,
    )
    minimum_moved = ceil(
        len(word) * constraints['minimum_moved_ratio'],
    )
    if moved_positions < minimum_moved:
        return False
    if 'preserved_bigrams' in constraints:
        return (
            preserved_bigrams == constraints['preserved_bigrams']
        )
    maximum_preserved = constraints['maximum_preserved_bigrams']
    return preserved_bigrams <= maximum_preserved


def _scramble_candidates_for(level, word):
    """Build deterministic, bounded candidates without easing constraints."""
    seed = (level * 100000) + sum(
        (index + 1) * ord(character)
        for index, character in enumerate(word)
    )
    rng = random.Random(seed)
    candidates = []
    seen = set()
    for _attempt in range(10000):
        candidate = ''.join(rng.sample(word, len(word)))
        if candidate in seen:
            continue
        seen.add(candidate)
        if _scramble_candidate_is_valid(level, word, candidate):
            candidates.append(candidate)
            if len(candidates) >= 12:
                break
    return tuple(candidates)


def _build_scramble_pools(words_by_level):
    """Exclude ambiguous signatures and words with no valid shuffle."""
    signatures = {}
    filtered_words = {}
    candidates = {}
    for level, words in words_by_level.items():
        accepted = []
        for word in words:
            signature = ''.join(sorted(word))
            if signature in signatures:
                continue
            word_candidates = _scramble_candidates_for(level, word)
            if not word_candidates:
                continue
            signatures[signature] = word
            accepted.append(word)
            candidates[(level, word)] = word_candidates
        if not accepted:
            raise ValueError(
                'word-scramble level {} has no valid words'.format(level),
            )
        filtered_words[level] = tuple(accepted)
    return filtered_words, candidates


_SCRAMBLE_WORDS_BY_LEVEL, _SCRAMBLE_DERANGEMENTS = (
    _build_scramble_pools(_SCRAMBLE_WORDS_BY_LEVEL)
)


class _RunState:
    """Private mutable state for one browser run."""

    def __init__(
            self,
            run_id,
            game_slug,
            player,
            rng,
            ranked=True,
            timing_mode='standard',
            score_ruleset=SCORE_RULESET,
    ):
        self.run_id = run_id
        self.game_slug = game_slug
        self.player = player
        self.rng = rng
        self.ranked = ranked
        self.timing_mode = timing_mode
        self.score_ruleset = score_ruleset
        self.score = 0
        self.lives = MAX_LIVES
        self.level = 1
        self.level_progress = 0
        self.ended = False
        self.quit_early = False
        self.recorded = False
        self.round = None
        # Retained for backwards-compatible snapshot loading; level metadata
        # now controls Number Memory difficulty.
        self.digit_count = brain_number_memory.MIN_DIGITS
        self.seen_words = set()
        self.word_history = []
        self.new_word_index = 0
        self.game_bag = []
        self.last_source_slug = None
        self.cycle_position = None
        self.truth_bags = {}
        self.content_bags = {}
        self.recent_content = {}


class RunStore:
    """Thread-safe in-memory storage and grader for browser game runs."""

    def __init__(
            self,
            leaderboard=None,
            random_factory=None,
            max_runs=DEFAULT_MAX_RUNS,
    ):
        self._leaderboard = (
            Leaderboard() if leaderboard is None else leaderboard
        )
        self._random_factory = random_factory or random.Random
        if not callable(self._random_factory):
            raise TypeError('random_factory must be callable')
        if isinstance(max_runs, bool) or not isinstance(max_runs, int):
            raise TypeError('max_runs must be an integer')
        if max_runs < 1:
            raise ValueError('max_runs must be positive')
        self._max_runs = max_runs
        self._runs = {}
        self._lock = threading.RLock()

    def create(
            self,
            game_slug,
            player,
            ranked=True,
            timing_mode='standard',
            start_level=1,
    ):
        """Create a run and return its first public round."""
        slug, clean_player = self._validated_run_owner(game_slug, player)
        if not isinstance(ranked, bool):
            raise TypeError('ranked must be a boolean')
        if not isinstance(timing_mode, str):
            raise TypeError('timing_mode must be a string')
        clean_timing_mode = _normalise(timing_mode)
        if clean_timing_mode not in TIMING_MODES:
            raise ValueError(
                'timing_mode must be one of: {}'.format(
                    ', '.join(TIMING_MODES),
                ),
            )
        self._validate_start_level(slug, start_level)
        ranked = all((
            ranked,
            clean_timing_mode == 'standard',
            start_level == 1,
        ))
        with self._lock:
            state = _RunState(
                _new_id(),
                slug,
                clean_player,
                self._new_rng(),
                ranked,
                clean_timing_mode,
            )
            state.level = start_level
            state.round = self._make_round(state)
            self._make_room_for_run()
            self._runs[state.run_id] = state
            return self._public_run(state)

    def answer(self, run_id, round_id, answer):
        """Grade one active round and return its result and next round."""
        with self._lock:
            state = self._get_run(run_id)
            payload = self._answer_state(state, round_id, answer)
            if state.ended:
                self._record_final_score(state)
            return payload

    def quit(self, run_id):
        """End a run early; repeated calls remain safe and idempotent."""
        with self._lock:
            state = self._get_run(run_id)
            payload = self._quit_state(state)
            if not state.recorded:
                self._record_final_score(state)
            return payload

    def leaders(self, game=None, limit=10, player=None):
        """Return leaderboard entries filtered by game or player."""
        game_slug = None
        if game is not None:
            game_slug = _normalise(game)
            if game_slug not in _CATALOG_BY_SLUG:
                raise UnknownGameError(game)
        if player is not None:
            if not isinstance(player, str) or not player.strip():
                raise ValueError('player must be a non-empty string')
            player = player.strip()[:MAX_PLAYER_LENGTH]
        stored_game = (
            '{}{}'.format(SCORE_GAME_PREFIX, game_slug)
            if game_slug is not None
            else None
        )
        with self._lock:
            entries = self._leaderboard.top(
                limit=limit,
                game=stored_game,
                player=player,
                game_prefix=(
                    None if stored_game is not None
                    else SCORE_GAME_PREFIX
                ),
            )
        return [
            self._public_score_entry(entry)
            for entry in entries
        ]

    @staticmethod
    def _public_score_entry(entry):
        public = dict(entry)
        stored_game = str(public.get('game', ''))
        if stored_game.startswith(SCORE_GAME_PREFIX):
            public['game'] = stored_game[len(SCORE_GAME_PREFIX):]
        return public

    @staticmethod
    def _validate_rng(rng):
        methods = ('choice', 'randint', 'randrange', 'sample', 'shuffle')
        if any(not callable(getattr(rng, name, None)) for name in methods):
            raise TypeError('random_factory must return a random-like object')

    @staticmethod
    def _validated_run_owner(game_slug, player):
        slug = _normalise(game_slug)
        if slug not in _CATALOG_BY_SLUG:
            raise UnknownGameError(game_slug)
        if not isinstance(player, str) or not player.strip():
            raise ValueError('player must be a non-empty string')
        return slug, player.strip()[:MAX_PLAYER_LENGTH]

    def _new_rng(self):
        rng = self._random_factory()
        self._validate_rng(rng)
        return rng

    def _get_run(self, run_id):
        try:
            return self._runs[run_id]
        except (KeyError, TypeError):
            raise UnknownRunError(run_id)

    @staticmethod
    def _validate_start_level(game_slug, start_level):
        if isinstance(start_level, bool) or not isinstance(start_level, int):
            raise TypeError('start_level must be an integer')
        max_level = max_level_for(game_slug)
        if not 1 <= start_level <= max_level:
            raise ValueError(
                'start_level must be between 1 and {}'.format(max_level),
            )

    def _answer_state(self, state, round_id, answer):
        if state.ended:
            raise RunEndedError(state.run_id)

        active_round = state.round
        current_round_id = active_round['public']['round_id']
        if round_id != current_round_id:
            raise StaleRoundError(
                state.run_id,
                round_id,
                current_round_id,
            )

        submitted, canonical, timed_out = self._validate_answer(
            answer,
            active_round,
        )
        correct = not timed_out and (
            canonical == _normalise(active_round['expected_answer'])
        )
        level_before, leveled_up = self._apply_answer_outcome(
            state,
            correct,
        )

        result = self._answer_result(
            active_round,
            current_round_id,
            submitted,
            correct,
            timed_out,
            level_before,
            state.level,
            leveled_up,
        )
        if state.lives <= 0:
            state.ended = True
            state.round = None
        else:
            state.round = self._make_round(state)

        payload = self._public_run(state)
        payload['result'] = result
        return payload

    @staticmethod
    def _apply_answer_outcome(state, correct):
        level_before = state.level
        if not correct:
            state.lives -= 1
            return level_before, False

        state.score += 1
        state.level_progress += 1
        if state.level_progress < CORRECT_PER_LEVEL:
            return level_before, False

        state.level_progress = 0
        if state.level >= max_level_for(state.game_slug):
            return level_before, False

        state.level += 1
        return level_before, True

    @staticmethod
    def _answer_result(
            active_round,
            round_id,
            submitted,
            correct,
            timed_out,
            level_before,
            level_after,
            leveled_up,
    ):
        return {
            'round_id': round_id,
            'correct': correct,
            'submitted_answer': submitted,
            'expected_answer': str(active_round['expected_answer']),
            'source_slug': active_round['source_slug'],
            'timed_out': timed_out,
            'level_before': level_before,
            'level_after': level_after,
            'leveled_up': leveled_up,
            'review': copy.deepcopy(active_round.get('review', {})),
        }

    def _quit_state(self, state):
        if not state.ended:
            state.ended = True
            state.quit_early = True
            state.round = None
        return self._public_run(state)

    def _record_final_score(self, state):
        if state.recorded:
            return
        if state.ranked:
            score_prefix = '{}:'.format(state.score_ruleset)
            self._leaderboard.record(
                state.player,
                '{}{}'.format(score_prefix, state.game_slug),
                state.score,
            )
        state.recorded = True

    def _make_room_for_run(self):
        """Bound memory while retaining active and recent runs when possible."""
        while len(self._runs) >= self._max_runs:
            completed_id = next((
                run_id for run_id, state in self._runs.items()
                if state.ended
            ), None)
            oldest_id = completed_id or next(iter(self._runs))
            del self._runs[oldest_id]

    @staticmethod
    def _validate_answer(answer, active_round):
        if answer is None:
            raise InvalidAnswerError(answer, active_round['choices'])
        submitted = str(answer).strip()
        if not submitted or _normalise(submitted) in {'q', 'quit'}:
            raise InvalidAnswerError(answer, active_round['choices'])
        if submitted == TIMEOUT_ANSWER:
            return submitted, submitted, True

        canonical = _normalise(submitted)
        aliases = active_round['aliases']
        canonical = _normalise(aliases.get(canonical, canonical))
        choices = active_round['choices']
        if choices and canonical not in {
                _normalise(choice) for choice in choices}:
            raise InvalidAnswerError(answer, choices)
        return submitted, canonical, False

    @staticmethod
    def _public_run(state):
        game = _CATALOG_BY_SLUG[state.game_slug]
        public_round = None
        if state.round is not None:
            public_round = copy.deepcopy(state.round['public'])
        return {
            'run_id': state.run_id,
            'game': state.game_slug,
            'game_name': game['name'],
            'player': state.player,
            'score': state.score,
            'lives': state.lives,
            'max_lives': MAX_LIVES,
            'level': state.level,
            'level_progress': state.level_progress,
            'level_goal': CORRECT_PER_LEVEL,
            'max_level': max_level_for(state.game_slug),
            'ranked': state.ranked,
            'timing_mode': state.timing_mode,
            'ended': state.ended,
            'quit_early': state.quit_early,
            'round': public_round,
        }

    def _make_round(self, state):
        if state.game_slug == CULMINATION_SLUG:
            source_slug, cycle_position = self._next_culmination_game(state)
            cycle_total = len(_CORE_SLUGS)
        else:
            source_slug = state.game_slug
            cycle_position = None
            cycle_total = None

        source_level = min(state.level, max_level_for(source_slug))
        generated = self._generate_nonrepeating_round(
            state,
            source_slug,
            source_level,
        )
        source = _CATALOG_BY_SLUG[source_slug]
        choices = list(generated.get('choices', []))
        preview_ms = int(generated.get('preview_ms', 0))
        base_time_limit_ms = int(generated.get(
            'time_limit_ms',
            time_limit_ms(source_slug, source_level),
        ))
        round_time_limit_ms = self._scaled_time_limit(
            base_time_limit_ms,
            state.timing_mode,
        )
        public = {
            'round_id': _new_id(),
            'source_slug': source_slug,
            'source_name': source['name'],
            'source_category': source['category'],
            'kind': generated['kind'],
            'prompt': str(generated['prompt']),
            'rules': source['rules'],
            'data': copy.deepcopy(generated.get('data', {})),
            'choices': choices,
            'preview_ms': preview_ms,
            'level': state.level,
            'difficulty_label': difficulty_label(source_level),
            'time_limit_ms': round_time_limit_ms,
            'hidden_prompt': generated.get('hidden_prompt'),
            'cycle_position': cycle_position,
            'cycle_total': cycle_total,
            'source_level': source_level,
        }
        return {
            'public': public,
            'expected_answer': str(generated['expected_answer']),
            'aliases': dict(generated.get('aliases', {})),
            'choices': choices,
            'source_slug': source_slug,
            'review': copy.deepcopy(generated.get('review', {})),
        }

    def _generate_nonrepeating_round(self, state, source_slug, level):
        """Avoid accidental recent question repeats without changing rules."""
        if source_slug == brain_verbal_memory.SLUG:
            return self._generate_source_round(state, source_slug, level)

        checkpoint = self._generation_checkpoint(state)
        recent = state.recent_content.setdefault(source_slug, [])
        generated = None
        signature = None
        for attempt in range(ROUND_GENERATION_ATTEMPTS):
            if attempt:
                self._restore_generation_checkpoint(state, checkpoint)
            generated = self._generate_source_round(
                state,
                source_slug,
                level,
            )
            signature = self._round_content_signature(
                source_slug,
                generated,
            )
            if signature not in recent:
                break

        recent.append(signature)
        del recent[:-RECENT_CONTENT_LIMIT]
        return generated

    @staticmethod
    def _generation_checkpoint(state):
        return {
            'truth_bags': copy.deepcopy(state.truth_bags),
        }

    @staticmethod
    def _restore_generation_checkpoint(state, checkpoint):
        state.truth_bags = copy.deepcopy(checkpoint['truth_bags'])

    @staticmethod
    def _round_content_signature(source_slug, generated):
        if source_slug == brain_word_scramble.SLUG:
            payload = {'answer': generated['expected_answer']}
        elif source_slug == brain_number_memory.SLUG:
            payload = {'number': generated['prompt']}
        elif source_slug == brain_prime.SLUG:
            payload = {'number': generated['data']['number']}
        elif source_slug == brain_gcd.SLUG:
            payload = {
                'numbers': sorted(generated['data']['numbers']),
            }
        else:
            payload = {
                'prompt': generated['prompt'],
                'data': RunStore._content_only_data(generated),
            }
        serialised = json.dumps(
            payload,
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=False,
        )
        return blake2s(
            serialised.encode('utf-8'),
            digest_size=16,
        ).hexdigest()

    @staticmethod
    def _content_only_data(generated):
        public_data = copy.deepcopy(generated.get('data', {}))
        for decorative_key in (
                'spin_axis',
                'spin_phase_deg',
                'spin_speed_deg_s'):
            public_data.pop(decorative_key, None)
        for item in public_data.get('items', ()):
            if isinstance(item, dict):
                item.pop('spin_phase_deg', None)
                item.pop('spin_speed_deg_s', None)
        return public_data

    @staticmethod
    def _scaled_time_limit(base_time_limit_ms, timing_mode):
        if timing_mode == 'self-paced':
            return 0
        if timing_mode == 'relaxed':
            return base_time_limit_ms * 2
        return base_time_limit_ms

    @staticmethod
    def _next_culmination_game(state):
        if not state.game_bag:
            state.game_bag = list(_CORE_SLUGS)
            state.rng.shuffle(state.game_bag)
            boundary_repeat = all((
                state.last_source_slug is not None,
                len(state.game_bag) > 1,
                state.game_bag[0] == state.last_source_slug,
            ))
            if boundary_repeat:
                state.game_bag[0], state.game_bag[1] = (
                    state.game_bag[1],
                    state.game_bag[0],
                )
            state.cycle_position = 0

        source_slug = state.game_bag.pop(0)
        state.last_source_slug = source_slug
        state.cycle_position += 1
        return source_slug, state.cycle_position

    def _generate_source_round(self, state, source_slug, level=None):
        if level is None:
            level = min(state.level, max_level_for(source_slug))
        generators = {
            brain_even.SLUG: self._generate_even,
            brain_calc.SLUG: self._generate_calc,
            brain_gcd.SLUG: self._generate_gcd,
            brain_progression.SLUG: self._generate_progression,
            brain_prime.SLUG: self._generate_prime,
            brain_number_memory.SLUG: self._generate_number_memory,
            brain_verbal_memory.SLUG: self._generate_verbal_memory,
            brain_motion_direction.SLUG: self._generate_motion_direction,
            brain_symbol_match.SLUG: self._generate_symbol_match,
            brain_word_scramble.SLUG: self._generate_word_scramble,
            brain_memory_matrix.SLUG: self._generate_memory_matrix,
            brain_pinball_recall.SLUG: self._generate_pinball_recall,
        }
        return generators[source_slug](state, level)

    @staticmethod
    def _generate_motion_direction(state, level=None):
        effective_level = state.level if level is None else level
        return brain_motion_direction.generate_round(
            state.rng,
            effective_level,
        )

    @staticmethod
    def _generate_memory_matrix(state, level=None):
        effective_level = state.level if level is None else level
        return brain_memory_matrix.generate_round(
            state.rng,
            effective_level,
        )

    @staticmethod
    def _generate_pinball_recall(state, level=None):
        effective_level = state.level if level is None else level
        generated = brain_pinball_recall.generate_round(
            state.rng,
            effective_level,
        )
        generated['review']['explanation'] = (
            'The ball exited at {} along the highlighted path.'
        ).format(generated['expected_answer'])
        return generated

    @staticmethod
    def _next_balanced_truth(state, source_slug, level=None):
        effective_level = state.level if level is None else level
        key = '{}:{}'.format(source_slug, effective_level)
        bag = state.truth_bags.setdefault(key, [])
        if not bag:
            bag.extend([True] * 5)
            bag.extend([False] * 5)
            state.rng.shuffle(bag)
        return bag.pop()

    @staticmethod
    def _next_content(state, key, values):
        """Draw without replacement from a persisted, shuffled content bag."""
        bag = state.content_bags.setdefault(key, [])
        if not bag:
            bag.extend(values)
            state.rng.shuffle(bag)
        return bag.pop()

    @staticmethod
    def _generate_even(state, level=None):
        level = state.level if level is None else level
        wants_even = RunStore._next_balanced_truth(
            state,
            brain_even.SLUG,
            level,
        )
        desired_parity = 0 if wants_even else 1
        generators = (
            None,
            RunStore._even_level_one,
            RunStore._even_level_two,
            RunStore._even_level_three,
            RunStore._even_level_four,
            RunStore._even_level_five,
        )
        expression, data = generators[level](
            state,
            desired_parity,
        )

        return {
            'kind': 'choice',
            'prompt': 'Is {} even?'.format(expression),
            'expected_answer': 'yes' if wants_even else 'no',
            'data': data,
            'choices': ['yes', 'no'],
            'aliases': brain_even.ANSWER_ALIASES,
            'review': {
                'parity': 'even' if wants_even else 'odd',
                'explanation': '{} has an {} result.'.format(
                    expression,
                    'even' if wants_even else 'odd',
                ),
            },
        }

    @staticmethod
    def _even_level_one(state, desired_parity):
        number = _number_with_parity(
            state.rng,
            0,
            99,
            desired_parity,
        )
        return str(number), {'number': number}

    @staticmethod
    def _even_level_two(state, desired_parity):
        digits = state.rng.randint(3, 6)
        number = _number_with_parity(
            state.rng,
            10 ** (digits - 1),
            (10 ** digits) - 1,
            desired_parity,
        )
        return str(number), {'number': number, 'digits': digits}

    @staticmethod
    def _even_level_three(state, desired_parity):
        left = state.rng.randint(10, 999)
        right_parity = (left % 2) ^ desired_parity
        right = _number_with_parity(
            state.rng,
            10,
            999,
            right_parity,
        )
        operation = state.rng.choice(('+', '-'))
        if operation == '-':
            left, right = max(left, right), min(left, right)
        expression = '{} {} {}'.format(left, operation, right)
        return expression, {
            'expression': expression,
            'operands': [left, right],
            'operators': [operation],
        }

    @staticmethod
    def _even_level_four(state, desired_parity):
        left = state.rng.randint(10, 99)
        right = state.rng.randint(10, 99)
        product_parity = (left * right) % 2
        final_parity = product_parity ^ desired_parity
        final = _number_with_parity(
            state.rng,
            10,
            999,
            final_parity,
        )
        operation = state.rng.choice(('+', '-'))
        if operation == '-' and (left * right) < final:
            operation = '+'
        expression = '{} × {} {} {}'.format(
            left,
            right,
            operation,
            final,
        )
        return expression, {
            'expression': expression,
            'operands': [left, right, final],
            'operators': ['×', operation],
        }

    @staticmethod
    def _even_level_five(state, desired_parity):
        first = state.rng.randint(10, 99)
        second = state.rng.randint(10, 99)
        third = state.rng.randint(10, 99)
        fourth = state.rng.randint(10, 99)
        base_value = (first * second) + (third * fourth)
        final_parity = (base_value % 2) ^ desired_parity
        final = _number_with_parity(
            state.rng,
            10,
            999,
            final_parity,
        )
        operation = state.rng.choice(('+', '-'))
        if operation == '-' and base_value < final:
            operation = '+'
        expression = '({} × {}) + ({} × {}) {} {}'.format(
            first,
            second,
            third,
            fourth,
            operation,
            final,
        )
        return expression, {
            'expression': expression,
            'operands': [first, second, third, fourth, final],
            'operators': ['×', '+', '×', operation],
        }

    @staticmethod
    def _generate_calc(state, level=None):
        level = state.level if level is None else level
        generators = (
            None,
            RunStore._calc_level_one,
            RunStore._calc_level_two,
            RunStore._calc_level_three,
            RunStore._calc_level_four,
            RunStore._calc_level_five,
        )
        expression, answer, template = generators[level](state)
        return {
            'kind': 'number',
            'prompt': expression,
            'expected_answer': str(answer),
            'data': {
                'expression': expression,
                'template': template,
            },
            'review': {
                'explanation': '{} = {}.'.format(expression, answer),
            },
        }

    @staticmethod
    def _calc_level_one(state):
        operation = state.rng.choice(('+', '-'))
        left = state.rng.randint(0, 20)
        right = state.rng.randint(0, 20)
        if operation == '-':
            left, right = max(left, right), min(left, right)
        answer = left + right if operation == '+' else left - right
        expression = '{} {} {}'.format(left, operation, right)
        return expression, answer, 'one_step'

    @staticmethod
    def _calc_level_two(state):
        operation = state.rng.choice((
            '+', '+', '+',
            '-', '-', '-',
            '×', '×',
            '÷', '÷',
        ))
        if operation == '+':
            left = state.rng.randint(0, 100)
            right = state.rng.randint(0, 100 - left)
            answer = left + right
        elif operation == '-':
            first = state.rng.randint(0, 100)
            second = state.rng.randint(0, 100)
            left, right = max(first, second), min(first, second)
            answer = left - right
        elif operation == '×':
            left = state.rng.randint(2, 10)
            right = state.rng.randint(2, 10)
            answer = left * right
        else:
            right = state.rng.randint(2, 10)
            answer = state.rng.randint(2, 10)
            left = right * answer
        expression = '{} {} {}'.format(left, operation, right)
        return expression, answer, 'one_step'

    @staticmethod
    def _calc_level_three(state):
        generators = {
            'add_subtract': RunStore._calc_three_add_subtract,
            'multiply': RunStore._calc_three_multiply,
            'exact_division': RunStore._calc_three_divide,
        }
        template = state.rng.choice(tuple(generators))
        expression, answer = generators[template](state)
        return expression, answer, template

    @staticmethod
    def _calc_three_add_subtract(state):
        operation = state.rng.choice(('+', '-'))
        first = state.rng.randint(10, 999)
        second = state.rng.randint(10, 999)
        if operation == '-':
            first, second = max(first, second), min(first, second)
        answer = (
            first + second if operation == '+'
            else first - second
        )
        return '{} {} {}'.format(first, operation, second), answer

    @staticmethod
    def _calc_three_multiply(state):
        first = state.rng.randint(10, 99)
        second = state.rng.randint(2, 9)
        return '{} × {}'.format(first, second), first * second

    @staticmethod
    def _calc_three_divide(state):
        divisor = state.rng.randint(2, 12)
        answer = state.rng.randint(10, 99)
        return '{} ÷ {}'.format(divisor * answer, divisor), answer

    @staticmethod
    def _calc_level_four(state):
        generators = {
            'sum_then_multiply': RunStore._calc_four_sum_multiply,
            'product_then_adjust': RunStore._calc_four_product_adjust,
            'sum_then_divide': RunStore._calc_four_sum_divide,
        }
        template = state.rng.choice(tuple(generators))
        expression, answer = generators[template](state)
        return expression, answer, template

    @staticmethod
    def _calc_four_sum_multiply(state):
        first = state.rng.randint(5, 50)
        second = state.rng.randint(5, 50)
        factor = state.rng.randint(2, 12)
        expression = '({} + {}) × {}'.format(first, second, factor)
        return expression, (first + second) * factor

    @staticmethod
    def _calc_four_product_adjust(state):
        first = state.rng.randint(10, 99)
        second = state.rng.randint(2, 12)
        product = first * second
        operation = state.rng.choice(('+', '-'))
        adjustment = state.rng.randint(0, min(product, 99))
        answer = (
            product + adjustment
            if operation == '+'
            else product - adjustment
        )
        expression = '{} × {} {} {}'.format(
            first,
            second,
            operation,
            adjustment,
        )
        return expression, answer

    @staticmethod
    def _calc_four_sum_divide(state):
        divisor = state.rng.randint(2, 12)
        answer = state.rng.randint(10, 99)
        total = divisor * answer
        first = state.rng.randint(1, total - 1)
        second = total - first
        expression = '({} + {}) ÷ {}'.format(first, second, divisor)
        return expression, answer

    @staticmethod
    def _calc_level_five(state):
        generators = {
            'two_products': RunStore._calc_five_two_products,
            'exact_three_step': RunStore._calc_five_exact,
            'product_adjust_twice': RunStore._calc_five_adjust_twice,
        }
        template = state.rng.choice(tuple(generators))
        expression, answer = generators[template](state)
        return expression, answer, template

    @staticmethod
    def _calc_five_two_products(state):
        first = state.rng.randint(11, 29)
        second = state.rng.randint(11, 29)
        third = state.rng.randint(11, 29)
        fourth = state.rng.randint(11, 29)
        first_product = first * second
        second_product = third * fourth
        operation = state.rng.choice(('+', '-'))
        if operation == '-' and second_product > first_product:
            first, third = third, first
            second, fourth = fourth, second
            first_product, second_product = second_product, first_product
        answer = (
            first_product + second_product
            if operation == '+'
            else first_product - second_product
        )
        expression = '({} × {}) {} ({} × {})'.format(
            first,
            second,
            operation,
            third,
            fourth,
        )
        return expression, answer

    @staticmethod
    def _calc_five_exact(state):
        divisor = state.rng.randint(2, 12)
        quotient = state.rng.randint(10, 99)
        factor = state.rng.randint(2, 12)
        total = divisor * quotient
        first = state.rng.randint(1, total - 1)
        second = total - first
        expression = '(({} + {}) × {}) ÷ {}'.format(
            first,
            second,
            factor,
            divisor,
        )
        return expression, quotient * factor

    @staticmethod
    def _calc_five_adjust_twice(state):
        first = state.rng.randint(11, 29)
        second = state.rng.randint(11, 29)
        product = first * second
        addition = state.rng.randint(10, 99)
        subtraction = state.rng.randint(
            0,
            min(product + addition, 99),
        )
        expression = '({} × {} + {}) - {}'.format(
            first,
            second,
            addition,
            subtraction,
        )
        return expression, product + addition - subtraction

    @staticmethod
    def _generate_gcd(state, level=None):
        level = state.level if level is None else level
        generators = (
            None,
            RunStore._gcd_level_one,
            RunStore._gcd_level_two,
            RunStore._gcd_level_three,
            RunStore._gcd_level_four,
            RunStore._gcd_level_five,
        )
        first, second = generators[level](state)
        if state.rng.choice((True, False)):
            first, second = second, first
        answer = gcd(first, second)
        return {
            'kind': 'number',
            'prompt': '{} {}'.format(first, second),
            'expected_answer': str(answer),
            'data': {'numbers': [first, second]},
            'review': {
                'explanation': 'The GCD of {} and {} is {}.'.format(
                    first,
                    second,
                    answer,
                ),
            },
        }

    @staticmethod
    def _gcd_level_one(state):
        common = state.rng.randint(2, 12)
        return common, common * state.rng.randint(2, 8)

    @staticmethod
    def _gcd_with_coprime_factors(
            state,
            common,
            factor_minimum,
            factor_maximum,
    ):
        first_factor, second_factor = _coprime_pair(
            state.rng,
            factor_minimum,
            factor_maximum,
        )
        return common * first_factor, common * second_factor

    @staticmethod
    def _gcd_level_two(state):
        common = state.rng.randint(2, 10)
        return RunStore._gcd_with_coprime_factors(
            state,
            common,
            2,
            9,
        )

    @staticmethod
    def _gcd_level_three(state):
        common = (
            1 if state.rng.randrange(4) == 0
            else state.rng.randint(2, 20)
        )
        return RunStore._gcd_with_coprime_factors(
            state,
            common,
            5,
            20,
        )

    @staticmethod
    def _gcd_level_four(state):
        common = (
            1 if state.rng.randrange(100) < 35
            else state.rng.randint(2, 30)
        )
        return RunStore._gcd_with_coprime_factors(
            state,
            common,
            10,
            50,
        )

    @staticmethod
    def _gcd_level_five(state):
        common = (
            1 if state.rng.randrange(100) < 40
            else state.rng.randint(2, 50)
        )
        if state.rng.randrange(4) == 0:
            first_factor, second_factor = state.rng.choice((
                (34, 55),
                (55, 89),
            ))
            return common * first_factor, common * second_factor
        return RunStore._gcd_with_coprime_factors(
            state,
            common,
            30,
            100,
        )

    @staticmethod
    def _generate_progression(state, level=None):
        level = state.level if level is None else level
        generators = (
            None,
            RunStore._progression_level_one,
            RunStore._progression_level_two,
            RunStore._progression_level_three,
            RunStore._progression_level_four,
            RunStore._progression_level_five,
        )
        (
            sequence,
            hidden_index,
            pattern,
            pattern_label,
        ) = generators[level](state)

        answer = sequence[hidden_index]
        visible = [str(value) for value in sequence]
        visible[hidden_index] = '..'
        return {
            'kind': 'number',
            'prompt': ' '.join(visible),
            'expected_answer': str(answer),
            'data': {
                'sequence': visible,
                'hidden_index': hidden_index,
                'pattern': pattern,
                'pattern_label': pattern_label,
            },
            'review': {
                'hidden_index': hidden_index,
                'pattern': pattern,
                'explanation': '{}; the missing term is {}.'.format(
                    pattern_label,
                    answer,
                ),
            },
        }

    @staticmethod
    def _progression_level_one(state):
        length = 5
        initial = state.rng.randint(0, 20)
        difference = state.rng.randint(1, 5)
        sequence = [
            initial + (difference * index)
            for index in range(length)
        ]
        hidden_index = state.rng.randrange(1, length - 1)
        return sequence, hidden_index, 'arithmetic', 'Ascending arithmetic'

    @staticmethod
    def _progression_level_two(state):
        length = 6
        magnitude = state.rng.randint(2, 12)
        descending = state.rng.choice((True, False))
        maximum_initial = 200 - (magnitude * (length - 1))
        initial = state.rng.randint(0, maximum_initial)
        if descending:
            initial += magnitude * (length - 1)
            difference = -magnitude
            label = 'Descending arithmetic'
        else:
            difference = magnitude
            label = 'Ascending arithmetic'
        sequence = [
            initial + (difference * index)
            for index in range(length)
        ]
        hidden_index = state.rng.randrange(1, length - 1)
        return sequence, hidden_index, 'arithmetic', label

    @staticmethod
    def _progression_level_three(state):
        length = state.rng.choice((5, 6))
        initial = state.rng.randint(1, 5)
        ratio = state.rng.randint(2, 3)
        sequence = [
            initial * (ratio ** index)
            for index in range(length)
        ]
        hidden_index = state.rng.randrange(1, length - 1)
        return sequence, hidden_index, 'geometric', 'Geometric'

    @staticmethod
    def _progression_level_four(state):
        length = 8
        first_initial = state.rng.randint(0, 30)
        second_initial = state.rng.randint(0, 30)
        first_difference = state.rng.randint(2, 12)
        second_difference = state.rng.randint(2, 12)
        sequence = []
        for index in range(length // 2):
            sequence.extend((
                first_initial + (first_difference * index),
                second_initial + (second_difference * index),
            ))
        hidden_index = state.rng.randrange(2, length - 2)
        return (
            sequence,
            hidden_index,
            'interleaved_arithmetic',
            'Two interleaved arithmetic sequences',
        )

    @staticmethod
    def _progression_level_five(state):
        length = state.rng.randint(7, 9)
        initial = state.rng.randint(0, 20)
        difference = state.rng.randint(1, 10)
        second_difference = state.rng.randint(1, 5)
        sequence = [initial]
        for _index in range(1, length):
            sequence.append(sequence[-1] + difference)
            difference += second_difference
        hidden_index = state.rng.randrange(2, length - 2)
        return (
            sequence,
            hidden_index,
            'constant_second_difference',
            'Constant second difference',
        )

    @staticmethod
    def _generate_prime(state, level=None):
        level = state.level if level is None else level
        is_prime = RunStore._next_balanced_truth(
            state,
            brain_prime.SLUG,
            level,
        )
        number = RunStore._next_content(
            state,
            'prime:{}:{}'.format(level, int(is_prime)),
            _PRIME_POOLS[level][is_prime],
        )
        if is_prime:
            explanation = (
                '{} has no divisors other than 1 and itself.'
            ).format(number)
            factor = None
        else:
            factor = _smallest_prime_factor(number)
            explanation = '{} = {} × {}.'.format(
                number,
                factor,
                number // factor,
            )
        return {
            'kind': 'choice',
            'prompt': 'Is {} prime?'.format(number),
            'expected_answer': 'yes' if is_prime else 'no',
            'data': {'number': number},
            'choices': ['yes', 'no'],
            'aliases': brain_prime.ANSWER_ALIASES,
            'review': {
                'is_prime': is_prime,
                'factor': factor,
                'explanation': explanation,
            },
        }

    @staticmethod
    def _generate_number_memory(state, level=None):
        level = state.level if level is None else level
        digits = number_memory_digits(
            level,
            state.level_progress,
        )
        lower_bound = 10 ** (digits - 1)
        upper_bound = (10 ** digits) - 1
        number = str(state.rng.randint(lower_bound, upper_bound))
        return {
            'kind': 'memory',
            'prompt': number,
            'expected_answer': number,
            'data': {'digits': digits},
            'preview_ms': number_memory_preview_ms(digits),
            'time_limit_ms': 0,
            'hidden_prompt': brain_number_memory.HIDDEN_QUESTION,
            'review': {
                'explanation': 'The number was {}.'.format(number),
            },
        }

    @staticmethod
    def _generate_verbal_memory(state, level=None):
        level = state.level if level is None else level
        level_index = level - 1
        history_window = VERBAL_HISTORY_WINDOWS[level_index]
        configured_lag = VERBAL_REPEAT_LAGS[level_index]
        minimum_lag = configured_lag
        if state.game_slug == CULMINATION_SLUG:
            warmup_lag = max(1, (len(state.word_history) + 1) // 2)
            minimum_lag = min(configured_lag, warmup_lag)
        seen_percentage = VERBAL_SEEN_PERCENTAGES[level_index]
        repeat_words = RunStore._eligible_repeat_words(
            state.word_history,
            history_window,
            minimum_lag,
        )
        ask_seen = RunStore._next_verbal_truth(
            state,
            seen_percentage,
            level,
        )
        if ask_seen and not repeat_words:
            RunStore._defer_verbal_truth(state, ask_seen, level)
            ask_seen = False
        if ask_seen:
            word = state.rng.choice(repeat_words)
            prior_lag = next(
                len(state.word_history) - index
                for index in range(len(state.word_history) - 1, -1, -1)
                if state.word_history[index] == word
            )
            explanation = '"{}" appeared {} prompt{} ago.'.format(
                word,
                prior_lag,
                '' if prior_lag == 1 else 's',
            )
        else:
            word = RunStore._choose_new_word(state)
            prior_lag = None
            explanation = (
                '"{}" had not appeared earlier in this run.'
            ).format(word)

        answer = 'yes' if ask_seen else 'no'
        state.seen_words.add(word)
        state.word_history.append(word)
        return {
            'kind': 'choice',
            'prompt': 'Have you seen "{}" before?'.format(word),
            'expected_answer': answer,
            'data': {
                'word': word,
                'history_window': (
                    history_window
                    if history_window is not None
                    else 'all'
                ),
                'minimum_repeat_lag': minimum_lag,
                'configured_repeat_lag': configured_lag,
                'seen_probability_percent': seen_percentage,
            },
            'choices': ['yes', 'no'],
            'aliases': brain_verbal_memory.ANSWER_ALIASES,
            'review': {
                'was_seen': ask_seen,
                'prior_lag': prior_lag,
                'explanation': explanation,
            },
        }

    @staticmethod
    def _next_verbal_truth(state, seen_percentage, level=None):
        effective_level = state.level if level is None else level
        key = 'verbal-memory:{}'.format(effective_level)
        bag = state.truth_bags.setdefault(key, [])
        if not bag:
            seen_count = (seen_percentage * 20) // 100
            bag.extend([True] * seen_count)
            bag.extend([False] * (20 - seen_count))
            state.rng.shuffle(bag)
        return bag.pop()

    @staticmethod
    def _defer_verbal_truth(state, truth, level=None):
        effective_level = state.level if level is None else level
        key = 'verbal-memory:{}'.format(effective_level)
        state.truth_bags.setdefault(key, []).insert(0, truth)

    @staticmethod
    def _eligible_repeat_words(history, history_window, minimum_lag):
        stop = len(history) - minimum_lag + 1
        if stop <= 0:
            return ()
        start = 0
        if history_window is not None:
            start = max(0, len(history) - history_window)
        recently_shown = set(history[stop:])
        eligible = [
            word for word in history[start:stop]
            if word not in recently_shown
        ]
        return tuple(dict.fromkeys(reversed(eligible)))

    @staticmethod
    def _choose_new_word(state):
        while True:
            bag = state.content_bags.setdefault('verbal-memory:new', [])
            if not bag:
                batch_start = state.new_word_index
                batch_size = 64
                bag.extend(
                    RunStore._verbal_term_for_index(index)
                    for index in range(
                        batch_start,
                        batch_start + batch_size,
                    )
                )
                state.new_word_index += batch_size
                state.rng.shuffle(bag)
            word = bag.pop()
            if word not in state.seen_words:
                return word

    @staticmethod
    def _verbal_term_for_index(index):
        """Map every non-negative index to a unique common-word phrase."""
        nouns = brain_verbal_memory.WORDS
        quotient, noun_index = divmod(index, len(nouns))
        descriptors = []
        while quotient or not descriptors:
            quotient, descriptor_index = divmod(
                quotient,
                len(_VERBAL_DESCRIPTORS),
            )
            descriptors.append(_VERBAL_DESCRIPTORS[descriptor_index])
        words = list(reversed(descriptors))
        words.append(nouns[noun_index])
        return ' '.join(words)

    @staticmethod
    def _generate_direction_focus(state, level=None):
        level = state.level if level is None else level
        if level >= 9:
            return RunStore._generate_spatial_direction(state, level)

        level_index = level - 1
        item_count = DIRECTION_ITEM_COUNTS[level_index]
        difference = DIRECTION_DIFFERENCES_DEG[level_index]
        target = state.rng.choice(tuple(_DIRECTION_ANGLES))
        target_angle = _DIRECTION_ANGLES[target]

        if level <= 2:
            items = RunStore._direction_orientation_items(
                state,
                level,
                item_count,
                target_angle,
                difference,
            )
            feature_count = 1
            instruction = 'Which way does the odd arrow point?'
            prompt = 'Find the one arrow pointing in a different direction.'
            task_mode = 'orientation'
        elif level <= 4:
            items = RunStore._direction_conjunction_items(
                state,
                item_count,
                target_angle,
                difference,
                feature_count=2,
            )
            feature_count = 2
            instruction = (
                'Find the only direction-and-frame combination. '
                'Which way does it point?'
            )
            prompt = instruction
            task_mode = 'two_feature_conjunction'
        else:
            items = RunStore._direction_conjunction_items(
                state,
                item_count,
                target_angle,
                difference,
                feature_count=3,
            )
            feature_count = 3
            instruction = (
                'Find the only direction, frame, and dot combination. '
                'Which way does it point?'
            )
            prompt = instruction
            task_mode = 'three_feature_conjunction'

        state.rng.shuffle(items)
        target_indices = [
            index
            for index, item in enumerate(items)
            if item.pop('_review_target', False)
        ]
        if len(target_indices) != 1:
            raise AssertionError('direction review target must be unique')
        target_index = target_indices[0]
        rotations = [item['rotation_deg'] for item in items]
        accessible_sequence = [
            item['accessible_label']
            for item in items
        ]
        return {
            'kind': 'direction',
            'prompt': prompt,
            'expected_answer': target,
            'data': {
                'arrows': [
                    RunStore._arrow_for_angle(rotation)
                    for rotation in rotations
                ],
                'rotations': rotations,
                'accessible_sequence': accessible_sequence,
                'items': items,
                'item_count': item_count,
                'grid_columns': isqrt(item_count - 1) + 1,
                'target_difference_deg': difference,
                'orientation_step_deg': (
                    90 if feature_count >= 2 else difference
                ),
                'distractor_orientation_count': len(set(
                    rotation
                    for rotation in rotations
                    if rotation != target_angle
                )),
                'feature_count': feature_count,
                'task_mode': task_mode,
                'instruction': instruction,
                'accessible_instruction': instruction,
            },
            'choices': list(_DIRECTION_ANGLES),
            'aliases': brain_direction_focus.ANSWER_ALIASES,
            'review': {
                'target_index': target_index,
                'explanation': (
                    'Item {} is the unique target: {}.'
                ).format(
                    target_index + 1,
                    accessible_sequence[target_index],
                ),
            },
        }

    @staticmethod
    def _direction_orientation_items(
            state,
            level,
            item_count,
            target_angle,
            difference,
    ):
        orientation_count = (1, 1, 2, 2)[level - 1]
        if orientation_count == 1:
            sign = state.rng.choice((-1, 1))
            distractor_angles = (
                (target_angle + (sign * difference)) % 360,
            )
        else:
            distractor_angles = (
                (target_angle - difference) % 360,
                (target_angle + difference) % 360,
            )
        rotations = [
            distractor_angles[index % orientation_count]
            for index in range(item_count - 1)
        ]
        rotations.append(target_angle)
        items = [
            RunStore._direction_item(rotation, 'square', 'none')
            for rotation in rotations
        ]
        items[-1]['_review_target'] = True
        return items

    @staticmethod
    def _direction_conjunction_items(  # noqa: C901
            state,
            item_count,
            target_angle,
            difference,
            feature_count,
    ):
        if difference != 90:
            raise ValueError('conjunction directions must be 90° apart')
        other_angles = [
            (target_angle + offset) % 360
            for offset in (90, 180, 270)
        ]
        state.rng.shuffle(other_angles)
        angles = [target_angle] + other_angles
        target_frame = state.rng.choice(('round', 'square'))
        alternate_frame = (
            'square' if target_frame == 'round' else 'round'
        )
        target_marker = (
            'none'
            if feature_count == 2
            else state.rng.choice(('dot', 'none'))
        )
        alternate_marker = (
            'none' if target_marker == 'dot' else 'dot'
        )
        if feature_count == 2:
            templates = {
                16: ((1, 3), [(2, 2), (2, 2), (2, 2)]),
                24: ((1, 5), [(3, 3), (4, 2), (4, 2)]),
                36: ((1, 8), [(5, 4), (6, 3), (6, 3)]),
            }
            target_row, non_target_rows = templates[item_count]
            state.rng.shuffle(non_target_rows)
            count_rows = [
                target_row,
                *non_target_rows,
            ]
            items = []
            for direction_index, (target_count, alternate_count) in (
                    enumerate(count_rows)):
                angle = angles[direction_index]
                target_items = [
                    RunStore._direction_item(
                        angle,
                        target_frame,
                        target_marker,
                    )
                    for _index in range(target_count)
                ]
                if direction_index == 0:
                    target_items[0]['_review_target'] = True
                items.extend(target_items)
                items.extend(
                    RunStore._direction_item(
                        angle,
                        alternate_frame,
                        target_marker,
                    )
                    for _index in range(alternate_count)
                )
        else:
            if item_count == 24:
                non_target_rows = [
                    (0, 2, 2, 2),
                    (0, 3, 3, 0),
                    (6, 0, 0, 0),
                ]
                state.rng.shuffle(non_target_rows)
                count_rows = [
                    (1, 0, 0, 5),
                    *non_target_rows,
                ]
                counts = {
                    (
                        direction,
                        cell // 2,
                        cell % 2,
                    ): count
                    for direction, row in enumerate(count_rows)
                    for cell, count in enumerate(row)
                }
            else:
                counts = {
                    (direction, frame, marker): 2
                    for direction in range(4)
                    for frame in range(2)
                    for marker in range(2)
                }
                counts[(0, 0, 0)] = 1
                for key in (
                    (0, 0, 1),
                    (0, 1, 0),
                    (1, 0, 0),
                    (2, 0, 1),
                    (3, 1, 0),
                ):
                    counts[key] += 1
            frames = (target_frame, alternate_frame)
            markers = (target_marker, alternate_marker)
            items = []
            for indices, count in counts.items():
                direction_index, frame_index, marker_index = indices
                generated = [
                    RunStore._direction_item(
                        angles[direction_index],
                        frames[frame_index],
                        markers[marker_index],
                    )
                    for _index in range(count)
                ]
                if indices == (0, 0, 0):
                    generated[0]['_review_target'] = True
                items.extend(generated)

        if len(items) != item_count:
            raise AssertionError('direction conjunction size mismatch')
        return items

    @staticmethod
    def _generate_spatial_direction(state, level):  # noqa: C901
        direction_names = tuple(_SPATIAL_DIRECTIONS)
        item_count = DIRECTION_ITEM_COUNTS[level - 1]
        occurrences = item_count // len(direction_names)
        target_direction = state.rng.choice(direction_names)
        direction_pool = [
            direction
            for direction in direction_names
            for _index in range(occurrences)
        ]
        direction_pool.remove(target_direction)
        state.rng.shuffle(direction_pool)

        if level == 9:
            profiles = ['triangular', 'square', 'octagonal']
            state.rng.shuffle(profiles)
            head_styles = ['narrow', 'wide']
            state.rng.shuffle(head_styles)
            target_features = (
                profiles[0],
                head_styles[0],
                'long',
            )
            non_target_rows = [(5, 3), (6, 2)]
            state.rng.shuffle(non_target_rows)
            count_rows = (
                (1, 7),
                *non_target_rows,
            )
            remaining_features = []
            feature_counts = []
            for profile_index, row in enumerate(count_rows):
                for head_index, count in enumerate(row):
                    features = (
                        profiles[profile_index],
                        head_styles[head_index],
                        'long',
                    )
                    if features == target_features:
                        continue
                    remaining_features.append(features)
                    feature_counts.append(count)
            feature_count = 2
            instruction = (
                'One arrow has a unique profile and head width. '
                'Which direction is it pointing?'
            )
        else:
            profiles = ['triangular', 'square', 'octagonal']
            state.rng.shuffle(profiles)
            head_styles = ['narrow', 'wide']
            state.rng.shuffle(head_styles)
            shaft_styles = ['short', 'long']
            state.rng.shuffle(shaft_styles)
            target_features = (
                profiles[0],
                head_styles[0],
                shaft_styles[0],
            )
            count_rows = (
                (1, 2, 2, 3),
                (2, 3, 3, 0),
                (2, 2, 2, 2),
            )
            remaining_features = []
            feature_counts = []
            for profile_index, row in enumerate(count_rows):
                for cell_index, count in enumerate(row):
                    features = (
                        profiles[profile_index],
                        head_styles[cell_index // 2],
                        shaft_styles[cell_index % 2],
                    )
                    if features == target_features:
                        continue
                    if count:
                        remaining_features.append(features)
                        feature_counts.append(count)
            feature_count = 3
            instruction = (
                'One arrow has a unique profile, head width, and shaft '
                'length. Which direction is it pointing?'
            )

        feature_pool = []
        for features, count in zip(remaining_features, feature_counts):
            feature_pool.extend([features] * count)
        state.rng.shuffle(feature_pool)

        target_item = RunStore._spatial_direction_item(
            state,
            target_direction,
            target_features,
        )
        target_item['_review_target'] = True
        items = [target_item]
        items.extend(
            RunStore._spatial_direction_item(
                state,
                direction,
                features,
            )
            for direction, features in zip(direction_pool, feature_pool)
        )
        if len(items) != item_count:
            raise AssertionError('spatial direction size mismatch')
        state.rng.shuffle(items)
        target_indices = [
            index
            for index, item in enumerate(items)
            if item.pop('_review_target', False)
        ]
        if len(target_indices) != 1:
            raise AssertionError('spatial direction target must be unique')
        target_index = target_indices[0]
        choices = list(direction_names)
        return {
            'kind': 'direction',
            'prompt': instruction,
            'expected_answer': target_direction,
            'data': {
                'render_mode': 'direction_3d',
                'items': items,
                'item_count': item_count,
                'grid_columns': 6,
                'feature_count': feature_count,
                'task_mode': (
                    'spatial_profile_head'
                    if level == 9
                    else 'spatial_profile_head_shaft'
                ),
                'instruction': instruction,
                'accessible_instruction': instruction,
                'accessible_sequence': [
                    item['accessible_label']
                    for item in items
                ],
                'direction_counts': {
                    direction: occurrences
                    for direction in direction_names
                },
                'animation': 'longitudinal_rotation',
            },
            'choices': choices,
            'aliases': brain_direction_focus.ANSWER_ALIASES,
            'review': {
                'target_index': target_index,
                'explanation': (
                    'Item {} is the unique 3D target: {}.'
                ).format(
                    target_index + 1,
                    items[target_index]['accessible_label'],
                ),
            },
        }

    @staticmethod
    def _spatial_direction_item(state, direction, features):
        profile, head_style, shaft_style = features
        direction_data = _SPATIAL_DIRECTIONS[direction]
        return {
            'direction': direction,
            'direction_vector': list(direction_data['vector']),
            'glyph': direction_data['glyph'],
            'profile': profile,
            'head_style': head_style,
            'shaft_style': shaft_style,
            'spin_phase_deg': state.rng.randrange(360),
            'spin_speed_deg_s': state.rng.choice(
                (-1, 1),
            ) * state.rng.randint(7, 13),
            'accessible_label': (
                '{} profile, {} head, {} shaft, arrow pointing {}'
            ).format(
                profile,
                head_style,
                shaft_style,
                direction_data['label'],
            ),
        }

    @staticmethod
    def _direction_item(rotation, frame, marker):
        direction_label = RunStore._accessible_arrow_label(rotation)
        frame_label = '{} frame'.format(frame)
        marker_label = (
            'with corner dot' if marker == 'dot' else 'without corner dot'
        )
        return {
            'glyph': '↑',
            'rotation_deg': rotation,
            'frame': frame,
            'marker': marker,
            'accessible_label': '{}, {}, {}'.format(
                direction_label,
                frame_label,
                marker_label,
            ),
        }

    @staticmethod
    def _arrow_for_angle(rotation):
        arrows = ('↑', '↗', '→', '↘', '↓', '↙', '←', '↖')
        return arrows[int((rotation + 22.5) // 45) % len(arrows)]

    @staticmethod
    def _accessible_arrow_label(rotation):
        cardinal_labels = {
            0: 'arrow pointing up',
            90: 'arrow pointing right',
            180: 'arrow pointing down',
            270: 'arrow pointing left',
        }
        return cardinal_labels.get(
            rotation,
            'arrow rotated {} degrees clockwise from up'.format(rotation),
        )

    @staticmethod
    def _generate_symbol_match(state, level=None):
        level = state.level if level is None else level
        if level >= 9:
            return RunStore._generate_spatial_symbol_match(state, level)
        return RunStore._generate_planar_symbol_match(state, level)

    @staticmethod
    def _generate_planar_symbol_match(state, level):
        sequence_length = SYMBOL_SEQUENCE_LENGTHS[level - 1]
        matches = RunStore._next_balanced_truth(
            state,
            brain_symbol_match.SLUG,
            level,
        )

        if level <= 3:
            left_tokens, right_tokens = RunStore._basic_symbol_sequences(
                state,
                level,
                sequence_length,
                matches,
            )
            instruction = 'Do these symbol sequences match exactly?'
            comparison_rule = 'exact'
            transform_degrees = 0
            pattern_columns = None
        elif level <= 6:
            left_tokens, right_tokens = RunStore._arrow_symbol_sequences(
                state,
                level,
                sequence_length,
                matches,
            )
            instruction = 'Do these arrow sequences match exactly?'
            comparison_rule = 'exact'
            transform_degrees = 0
            pattern_columns = None
        elif level == 7:
            transform_degrees = state.rng.choice((90, 180, 270))
            left_tokens, right_tokens = (
                RunStore._rotated_arrow_sequences(
                    state,
                    sequence_length,
                    transform_degrees,
                    matches,
                )
            )
            instruction = (
                'After rotating every left arrow {}° clockwise, '
                'do the sequences match?'
            ).format(transform_degrees)
            comparison_rule = 'global_rotation'
            pattern_columns = None
        else:
            transform_degrees = state.rng.choice((90, 180, 270))
            left_tokens, right_tokens = RunStore._rotated_arrow_grids(
                state,
                transform_degrees,
                matches,
            )
            instruction = (
                'After rotating the entire left grid {}° clockwise, '
                'do the grids match?'
            ).format(transform_degrees)
            comparison_rule = 'grid_rotation'
            pattern_columns = 3

        review = RunStore._symbol_review(
            left_tokens,
            right_tokens,
            comparison_rule,
            transform_degrees,
        )
        if review['matches'] != matches:
            raise AssertionError('symbol review does not match answer')
        left_symbols = [token['symbol'] for token in left_tokens]
        right_symbols = [token['symbol'] for token in right_tokens]
        data = {
            'symbols': [left_symbols, right_symbols],
            'left_symbols': left_symbols,
            'right_symbols': right_symbols,
            'sequence_length': sequence_length,
            'left_tokens': left_tokens,
            'right_tokens': right_tokens,
            'comparison_rule': comparison_rule,
            'transform_degrees': transform_degrees,
            'instruction': instruction,
        }
        if pattern_columns is not None:
            data['pattern_columns'] = pattern_columns
        return {
            'kind': 'choice',
            'prompt': instruction,
            'expected_answer': 'yes' if matches else 'no',
            'data': data,
            'choices': ['yes', 'no'],
            'aliases': brain_symbol_match.ANSWER_ALIASES,
            'review': review,
        }

    @staticmethod
    def _generate_spatial_symbol_match(state, level):  # noqa: C901
        cube_count = SYMBOL_SEQUENCE_LENGTHS[level - 1]
        matches = RunStore._next_balanced_truth(
            state,
            brain_symbol_match.SLUG,
            level,
        )
        comparison_rule = (
            'polycube_rotation'
            if level == 9
            else 'polycube_chirality'
        )
        require_chiral = level == 10
        mutation = None
        for _attempt in range(128):
            left_source = RunStore._random_polycube(
                state,
                cube_count,
                require_chiral=require_chiral,
            )
            if matches:
                right_source = left_source
                break
            if level == 9:
                mutation = RunStore._mutated_polycube(
                    state,
                    left_source,
                )
                if mutation is None:
                    continue
                right_source, mutated_cube = mutation
            else:
                right_source = RunStore._normalise_polycube(
                    (-x, y, z)
                    for x, y, z in left_source
                )
                mutated_cube = None
                left_canonical = RunStore._polycube_canonical(left_source)
                right_canonical = RunStore._polycube_canonical(right_source)
                if left_canonical == right_canonical:
                    continue
            break
        else:
            raise AssertionError('could not generate a spatial symbol round')

        left_rotation = state.rng.choice(_CUBE_ROTATIONS)
        right_rotation = state.rng.choice(_CUBE_ROTATIONS)
        left_cubes = RunStore._rotate_polycube(
            left_source,
            left_rotation,
        )
        right_cubes = RunStore._rotate_polycube(
            right_source,
            right_rotation,
        )
        if matches:
            mismatch_indices = []
            explanation = (
                'The two solids are congruent under a proper 3D rotation.'
            )
        elif level == 9:
            mismatch_index = RunStore._rotated_cube_index(
                right_source,
                mutated_cube,
                right_rotation,
            )
            mismatch_indices = [mismatch_index]
            explanation = (
                'The highlighted cube changes the solid, so no rotation '
                'can make the pair match.'
            )
        else:
            mismatch_indices = list(range(len(right_cubes)))
            explanation = (
                'The right solid is a mirror image, not a proper rotation '
                'of the left solid.'
            )

        left_canonical = RunStore._polycube_canonical(left_cubes)
        right_canonical = RunStore._polycube_canonical(right_cubes)
        canonical_matches = left_canonical == right_canonical
        if canonical_matches != matches:
            raise AssertionError('spatial symbol answer is inconsistent')

        instruction = (
            'Can one solid be rotated in 3D to match the other exactly?'
            if level == 9
            else (
                'Are these the same chiral solid under rotation, '
                'not reflection?'
            )
        )
        data = {
            'render_mode': 'polycube_3d',
            'left_cubes': [list(cube) for cube in left_cubes],
            'right_cubes': [list(cube) for cube in right_cubes],
            'shape_size': cube_count,
            'sequence_length': cube_count,
            'comparison_rule': comparison_rule,
            'transform_degrees': 0,
            'instruction': instruction,
            'spin_axis': list(state.rng.choice((
                (1, 1, 0),
                (0, 1, 1),
                (1, 0, 1),
                (-1, 1, 0),
            ))),
            'spin_phase_deg': state.rng.randrange(360),
            'spin_speed_deg_s': state.rng.choice(
                (-1, 1),
            ) * state.rng.randint(7, 11),
            'accessible_left': RunStore._polycube_accessible_label(
                left_cubes,
            ),
            'accessible_right': RunStore._polycube_accessible_label(
                right_cubes,
            ),
        }
        return {
            'kind': 'choice',
            'prompt': instruction,
            'expected_answer': 'yes' if matches else 'no',
            'data': data,
            'choices': ['yes', 'no'],
            'aliases': brain_symbol_match.ANSWER_ALIASES,
            'review': {
                'matches': matches,
                'mismatch_indices': mismatch_indices,
                'comparison_rule': comparison_rule,
                'transform_degrees': 0,
                'explanation': explanation,
            },
        }

    @staticmethod
    def _normalise_polycube(cubes):
        cubes = tuple(tuple(int(value) for value in cube) for cube in cubes)
        if not cubes:
            return ()
        minima = tuple(
            min(cube[axis] for cube in cubes)
            for axis in range(3)
        )
        return tuple(sorted(
            tuple(cube[axis] - minima[axis] for axis in range(3))
            for cube in cubes
        ))

    @staticmethod
    def _apply_cube_rotation(cube, rotation):
        return tuple(
            sum(rotation[row][column] * cube[column] for column in range(3))
            for row in range(3)
        )

    @staticmethod
    def _rotate_polycube(cubes, rotation):
        return RunStore._normalise_polycube(
            RunStore._apply_cube_rotation(cube, rotation)
            for cube in cubes
        )

    @staticmethod
    def _polycube_canonical(cubes):
        return min(
            RunStore._rotate_polycube(cubes, rotation)
            for rotation in _CUBE_ROTATIONS
        )

    @staticmethod
    def _polycube_connected(cubes):
        cube_set = set(cubes)
        if not cube_set:
            return False
        pending = [next(iter(cube_set))]
        visited = set()
        while pending:
            cube = pending.pop()
            if cube in visited:
                continue
            visited.add(cube)
            for offset in _CUBE_NEIGHBOURS:
                neighbour = tuple(
                    cube[axis] + offset[axis]
                    for axis in range(3)
                )
                if neighbour in cube_set and neighbour not in visited:
                    pending.append(neighbour)
        return visited == cube_set

    @staticmethod
    def _random_polycube(  # noqa: C901
            state,
            cube_count,
            require_chiral=False,
    ):
        for _attempt in range(512):
            cubes = {(0, 0, 0)}
            while len(cubes) < cube_count:
                anchor = state.rng.choice(tuple(cubes))
                offset = state.rng.choice(_CUBE_NEIGHBOURS)
                cubes.add(tuple(
                    anchor[axis] + offset[axis]
                    for axis in range(3)
                ))
            normalised = RunStore._normalise_polycube(cubes)
            spans = [
                max(cube[axis] for cube in normalised)
                for axis in range(3)
            ]
            if any(span == 0 for span in spans):
                continue
            orientations = {
                RunStore._rotate_polycube(normalised, rotation)
                for rotation in _CUBE_ROTATIONS
            }
            if len(orientations) < 12:
                continue
            if require_chiral:
                mirrored = RunStore._normalise_polycube(
                    (-x, y, z)
                    for x, y, z in normalised
                )
                normal_canonical = RunStore._polycube_canonical(normalised)
                mirror_canonical = RunStore._polycube_canonical(mirrored)
                if normal_canonical == mirror_canonical:
                    continue
            return normalised
        raise AssertionError('could not generate an asymmetric polycube')

    @staticmethod
    def _mutated_polycube(state, cubes):  # noqa: C901
        candidates = []
        cube_set = set(cubes)
        source_canonical = RunStore._polycube_canonical(cubes)
        removable = list(cube_set)
        state.rng.shuffle(removable)
        for removed in removable:
            remaining = cube_set - {removed}
            if not RunStore._polycube_connected(remaining):
                continue
            anchors = list(remaining)
            state.rng.shuffle(anchors)
            offsets = list(_CUBE_NEIGHBOURS)
            state.rng.shuffle(offsets)
            for anchor in anchors:
                for offset in offsets:
                    added = tuple(
                        anchor[axis] + offset[axis]
                        for axis in range(3)
                    )
                    if added in remaining:
                        continue
                    candidate = RunStore._normalise_polycube(
                        remaining | {added},
                    )
                    candidate_canonical = (
                        RunStore._polycube_canonical(candidate)
                    )
                    if any((
                        candidate == cubes,
                        candidate_canonical == source_canonical,
                    )):
                        continue
                    removed_minima = tuple(
                        min(cube[axis] for cube in remaining | {added})
                        for axis in range(3)
                    )
                    normalised_added = tuple(
                        added[axis] - removed_minima[axis]
                        for axis in range(3)
                    )
                    candidates.append((candidate, normalised_added))
        return state.rng.choice(candidates) if candidates else None

    @staticmethod
    def _rotated_cube_index(cubes, focused_cube, rotation):
        raw = [
            RunStore._apply_cube_rotation(cube, rotation)
            for cube in cubes
        ]
        minima = tuple(
            min(cube[axis] for cube in raw)
            for axis in range(3)
        )
        focused = RunStore._apply_cube_rotation(
            focused_cube,
            rotation,
        )
        focused = tuple(
            focused[axis] - minima[axis]
            for axis in range(3)
        )
        return sorted(
            tuple(cube[axis] - minima[axis] for axis in range(3))
            for cube in raw
        ).index(focused)

    @staticmethod
    def _polycube_accessible_label(cubes):
        return 'cubes at {}'.format(', '.join(
            '({}, {}, {})'.format(*cube)
            for cube in cubes
        ))

    @staticmethod
    def _symbol_review(
            left_tokens,
            right_tokens,
            comparison_rule,
            transform_degrees,
    ):
        expected, actual = RunStore._symbol_review_values(
            left_tokens,
            right_tokens,
            comparison_rule,
            transform_degrees,
        )
        mismatch_indices = [
            index
            for index, pair in enumerate(zip(expected, actual))
            if pair[0] != pair[1]
        ]
        matches = not mismatch_indices
        explanation = RunStore._symbol_review_explanation(
            comparison_rule,
            transform_degrees,
            mismatch_indices,
        )
        return {
            'matches': matches,
            'mismatch_indices': mismatch_indices,
            'comparison_rule': comparison_rule,
            'transform_degrees': transform_degrees,
            'explanation': explanation,
        }

    @staticmethod
    def _symbol_review_values(
            left_tokens,
            right_tokens,
            comparison_rule,
            transform_degrees,
    ):
        if comparison_rule == 'exact':
            expected = [
                token['symbol']
                for token in left_tokens
            ]
            actual = [
                token['symbol']
                for token in right_tokens
            ]
        elif comparison_rule == 'global_rotation':
            expected = [
                (token['rotation_deg'] + transform_degrees) % 360
                for token in left_tokens
            ]
            actual = [
                token['rotation_deg']
                for token in right_tokens
            ]
        elif comparison_rule == 'grid_rotation':
            expected = RunStore._rotate_arrow_grid(
                [
                    token['rotation_deg']
                    for token in left_tokens
                ],
                transform_degrees // 90,
            )
            actual = [
                token['rotation_deg']
                for token in right_tokens
            ]
        else:
            raise ValueError(
                'Unknown symbol comparison rule: {}'.format(
                    comparison_rule,
                ),
            )
        return expected, actual

    @staticmethod
    def _symbol_review_explanation(
            comparison_rule,
            transform_degrees,
            mismatch_indices,
    ):
        if not mismatch_indices:
            if comparison_rule == 'exact':
                return 'Every position matches exactly.'
            if comparison_rule == 'global_rotation':
                return (
                    'Every arrow matches after a {}° clockwise rotation.'
                ).format(transform_degrees)
            return (
                'Every cell matches after rotating the whole grid '
                '{}° clockwise.'
            ).format(transform_degrees)

        position_labels = ', '.join(
            str(index + 1)
            for index in mismatch_indices
        )
        noun = 'Position' if len(mismatch_indices) == 1 else 'Positions'
        return '{} {} did not match the rule.'.format(
            noun,
            position_labels,
        )

    @staticmethod
    def _basic_symbol_sequences(state, level, sequence_length, matches):
        left = [
            state.rng.choice(_SYMBOL_STANDARD_TOKENS)
            for _index in range(sequence_length)
        ]
        right = list(left)
        if not matches:
            mismatch_index = state.rng.randrange(sequence_length)
            _kind, right[mismatch_index] = RunStore._symbol_mismatch(
                state,
                left[mismatch_index],
                level,
            )
        return (
            [RunStore._public_symbol_token(symbol) for symbol in left],
            [RunStore._public_symbol_token(symbol) for symbol in right],
        )

    @staticmethod
    def _arrow_symbol_sequences(state, level, sequence_length, matches):
        angle_step = {
            4: 90,
            5: 45,
            6: 15,
        }[level]
        angle_pool = tuple(range(0, 360, angle_step))
        if level == 6:
            start = state.rng.choice(angle_pool)
            left_angles = [
                (start + (index * angle_step)) % 360
                for index in range(sequence_length)
            ]
        else:
            left_angles = []
            while len(left_angles) < sequence_length:
                cycle = list(angle_pool)
                state.rng.shuffle(cycle)
                left_angles.extend(cycle)
            left_angles = left_angles[:sequence_length]
        state.rng.shuffle(left_angles)
        right_angles = list(left_angles)
        if not matches:
            candidates = [
                (index, (angle + angle_step) % 360)
                for index, angle in enumerate(left_angles)
                if (angle + angle_step) % 360 in left_angles
            ]
            mismatch_index, replacement = state.rng.choice(candidates)
            right_angles[mismatch_index] = replacement
        return (
            [
                RunStore._symbol_arrow_token(angle)
                for angle in left_angles
            ],
            [
                RunStore._symbol_arrow_token(angle)
                for angle in right_angles
            ],
        )

    @staticmethod
    def _rotated_arrow_sequences(
            state,
            sequence_length,
            transform_degrees,
            matches,
    ):
        angle_pool = tuple(range(0, 360, 45))
        left_angles = [
            state.rng.choice(angle_pool)
            for _index in range(sequence_length)
        ]
        right_angles = [
            (angle + transform_degrees) % 360
            for angle in left_angles
        ]
        if not matches:
            mismatch_index = state.rng.randrange(sequence_length)
            adjustment = state.rng.choice((-45, 45))
            changed_angle = right_angles[mismatch_index] + adjustment
            right_angles[mismatch_index] = changed_angle % 360
        return (
            [
                RunStore._symbol_arrow_token(angle)
                for angle in left_angles
            ],
            [
                RunStore._symbol_arrow_token(angle)
                for angle in right_angles
            ],
        )

    @staticmethod
    def _rotated_arrow_grids(state, transform_degrees, matches):
        angle_pool = tuple(range(0, 360, 45))
        left_angles = [
            state.rng.choice(angle_pool)
            for _index in range(9)
        ]
        right_angles = RunStore._rotate_arrow_grid(
            left_angles,
            transform_degrees // 90,
        )
        if not matches:
            mismatch_index = state.rng.randrange(len(right_angles))
            adjustment = state.rng.choice((-45, 45))
            changed_angle = right_angles[mismatch_index] + adjustment
            right_angles[mismatch_index] = changed_angle % 360
        return (
            [
                RunStore._symbol_arrow_token(angle)
                for angle in left_angles
            ],
            [
                RunStore._symbol_arrow_token(angle)
                for angle in right_angles
            ],
        )

    @staticmethod
    def _rotate_arrow_grid(angles, quarter_turns):
        size = 3
        rotated = list(angles)
        for _turn in range(quarter_turns):
            next_grid = [None] * len(rotated)
            for row in range(size):
                for column in range(size):
                    next_row = column
                    next_column = size - 1 - row
                    next_grid[(next_row * size) + next_column] = (
                        rotated[(row * size) + column] + 90
                    ) % 360
            rotated = next_grid
        return rotated

    @staticmethod
    def _symbol_arrow_token(rotation):
        return {
            'symbol': 'arrow-{:03d}'.format(rotation),
            'glyph': '↑',
            'shape': 'arrow',
            'fill': 'solid',
            'rotation_deg': rotation,
            'internal_mark': 'none',
            'accessible_label': (
                RunStore._accessible_arrow_label(rotation)
            ),
        }

    @staticmethod
    def _public_symbol_token(symbol):
        if isinstance(symbol, dict):
            return dict(symbol)
        token = dict(_SYMBOL_TOKENS[symbol])
        token['symbol'] = symbol
        return token

    @staticmethod
    def _symbol_mismatch(state, left_symbol, level=None):
        level = state.level if level is None else level
        feature_rules = {
            1: ('shape_and_fill', ('shape', 'fill'), ()),
            2: ('shape', ('shape',), ('fill',)),
            3: ('fill', ('fill',), ('shape',)),
        }
        mismatch_kind, different_fields, matching_fields = (
            feature_rules[level]
        )
        candidates = [
            symbol
            for symbol in _SYMBOL_STANDARD_TOKENS
            if RunStore._symbol_features_match(
                left_symbol,
                symbol,
                different_fields,
                matching_fields,
            )
        ]
        return mismatch_kind, state.rng.choice(candidates)

    @staticmethod
    def _symbol_features_match(
            left_symbol,
            candidate_symbol,
            different_fields,
            matching_fields,
    ):
        left = _SYMBOL_TOKENS[left_symbol]
        candidate = _SYMBOL_TOKENS[candidate_symbol]
        differences_match = all(
            candidate[field] != left[field]
            for field in different_fields
        )
        similarities_match = all(
            candidate[field] == left[field]
            for field in matching_fields
        )
        return differences_match and similarities_match

    @staticmethod
    def _generate_word_scramble(state, level=None):
        level = state.level if level is None else level
        answer = RunStore._next_content(
            state,
            'word-scramble:{}'.format(level),
            _SCRAMBLE_WORDS_BY_LEVEL[level],
        )
        scrambled = state.rng.choice(
            _SCRAMBLE_DERANGEMENTS[(level, answer)],
        )
        moved_positions, preserved_bigrams = _scramble_metrics(
            answer,
            scrambled,
        )
        hint = None
        if level == 1:
            hint = 'Starts with {}'.format(answer[0].upper())
        prompt = 'Unscramble: {}'.format(scrambled)
        if hint is not None:
            prompt = '{}. Hint: {}.'.format(prompt, hint)
        return {
            'kind': 'text',
            'prompt': prompt,
            'expected_answer': answer,
            'data': {
                'scrambled': scrambled,
                'letters': list(scrambled),
                'word_length': len(answer),
                'hint': hint,
                'moved_positions': moved_positions,
                'preserved_bigrams': preserved_bigrams,
            },
            'review': {
                'explanation': '{} unscrambles to {}.'.format(
                    scrambled.upper(),
                    answer.upper(),
                ),
            },
        }
