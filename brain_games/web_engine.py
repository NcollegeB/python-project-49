"""Server-side game engine for the browser interface.

The terminal games predate the web application and some of them keep session
state in module globals.  This module deliberately owns all state per run so
that concurrent browser sessions cannot affect one another.
"""

import copy
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
from brain_games.difficulty import MAX_LEVEL
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
from brain_games.games import brain_number_memory
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
SCORE_RULESET = 'r2'
SCORE_GAME_PREFIX = '{}:'.format(SCORE_RULESET)
TIMING_MODES = ('standard', 'relaxed', 'self-paced')


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
        brain_direction_focus,
        'Spot the one arrow pointing in a different direction.',
        '→',
    ),
    _catalog_entry(
        brain_symbol_match,
        'Quickly decide whether two symbols match.',
        '◇',
    ),
    _catalog_entry(
        brain_word_scramble,
        'Rearrange shuffled letters into the original word.',
        'ABC',
    ),
    {
        'slug': CULMINATION_SLUG,
        'name': 'Culmination Test',
        'category': 'Mixed',
        'rules': (
            'Every round comes from a different BrainHacker test.'
        ),
        'description': 'Take on all ten challenges in shuffled cycles.',
        'icon': '★',
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
    ):
        self.run_id = run_id
        self.game_slug = game_slug
        self.player = player
        self.rng = rng
        self.ranked = ranked
        self.timing_mode = timing_mode
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
        ranked = ranked and clean_timing_mode == 'standard'
        with self._lock:
            state = _RunState(
                _new_id(),
                slug,
                clean_player,
                self._new_rng(),
                ranked,
                clean_timing_mode,
            )
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
        if state.level >= MAX_LEVEL:
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
            self._leaderboard.record(
                state.player,
                '{}{}'.format(SCORE_GAME_PREFIX, state.game_slug),
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
            'max_level': MAX_LEVEL,
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

        generated = self._generate_source_round(state, source_slug)
        source = _CATALOG_BY_SLUG[source_slug]
        choices = list(generated.get('choices', []))
        preview_ms = int(generated.get('preview_ms', 0))
        base_time_limit_ms = int(generated.get(
            'time_limit_ms',
            time_limit_ms(source_slug, state.level),
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
            'difficulty_label': difficulty_label(state.level),
            'time_limit_ms': round_time_limit_ms,
            'hidden_prompt': generated.get('hidden_prompt'),
            'cycle_position': cycle_position,
            'cycle_total': cycle_total,
        }
        return {
            'public': public,
            'expected_answer': str(generated['expected_answer']),
            'aliases': dict(generated.get('aliases', {})),
            'choices': choices,
            'source_slug': source_slug,
        }

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

    def _generate_source_round(self, state, source_slug):
        generators = {
            brain_even.SLUG: self._generate_even,
            brain_calc.SLUG: self._generate_calc,
            brain_gcd.SLUG: self._generate_gcd,
            brain_progression.SLUG: self._generate_progression,
            brain_prime.SLUG: self._generate_prime,
            brain_number_memory.SLUG: self._generate_number_memory,
            brain_verbal_memory.SLUG: self._generate_verbal_memory,
            brain_direction_focus.SLUG: self._generate_direction_focus,
            brain_symbol_match.SLUG: self._generate_symbol_match,
            brain_word_scramble.SLUG: self._generate_word_scramble,
        }
        return generators[source_slug](state)

    @staticmethod
    def _next_balanced_truth(state, source_slug):
        key = '{}:{}'.format(source_slug, state.level)
        bag = state.truth_bags.setdefault(key, [])
        if not bag:
            bag.extend((True, False))
            state.rng.shuffle(bag)
        return bag.pop()

    @staticmethod
    def _generate_even(state):
        wants_even = RunStore._next_balanced_truth(
            state,
            brain_even.SLUG,
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
        expression, data = generators[state.level](
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
    def _generate_calc(state):
        generators = (
            None,
            RunStore._calc_level_one,
            RunStore._calc_level_two,
            RunStore._calc_level_three,
            RunStore._calc_level_four,
            RunStore._calc_level_five,
        )
        expression, answer, template = generators[state.level](state)
        return {
            'kind': 'number',
            'prompt': expression,
            'expected_answer': str(answer),
            'data': {
                'expression': expression,
                'template': template,
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
    def _generate_gcd(state):
        generators = (
            None,
            RunStore._gcd_level_one,
            RunStore._gcd_level_two,
            RunStore._gcd_level_three,
            RunStore._gcd_level_four,
            RunStore._gcd_level_five,
        )
        first, second = generators[state.level](state)
        if state.rng.choice((True, False)):
            first, second = second, first
        answer = gcd(first, second)
        return {
            'kind': 'number',
            'prompt': '{} {}'.format(first, second),
            'expected_answer': str(answer),
            'data': {'numbers': [first, second]},
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
    def _generate_progression(state):
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
        ) = generators[state.level](state)

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
    def _generate_prime(state):
        is_prime = RunStore._next_balanced_truth(
            state,
            brain_prime.SLUG,
        )
        number = state.rng.choice(_PRIME_POOLS[state.level][is_prime])
        return {
            'kind': 'choice',
            'prompt': 'Is {} prime?'.format(number),
            'expected_answer': 'yes' if is_prime else 'no',
            'data': {'number': number},
            'choices': ['yes', 'no'],
            'aliases': brain_prime.ANSWER_ALIASES,
        }

    @staticmethod
    def _generate_number_memory(state):
        digits = number_memory_digits(
            state.level,
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
        }

    @staticmethod
    def _generate_verbal_memory(state):
        level_index = state.level - 1
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
        )
        if ask_seen and not repeat_words:
            RunStore._defer_verbal_truth(state, ask_seen)
            ask_seen = False
        if ask_seen:
            word = state.rng.choice(repeat_words)
        else:
            word = RunStore._choose_new_word(state)

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
        }

    @staticmethod
    def _next_verbal_truth(state, seen_percentage):
        key = 'verbal-memory:{}'.format(state.level)
        bag = state.truth_bags.setdefault(key, [])
        if not bag:
            seen_count = (seen_percentage * 20) // 100
            bag.extend([True] * seen_count)
            bag.extend([False] * (20 - seen_count))
            state.rng.shuffle(bag)
        return bag.pop()

    @staticmethod
    def _defer_verbal_truth(state, truth):
        key = 'verbal-memory:{}'.format(state.level)
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
            word = RunStore._verbal_term_for_index(
                state.new_word_index,
            )
            state.new_word_index += 1
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
    def _generate_direction_focus(state):
        level_index = state.level - 1
        item_count = DIRECTION_ITEM_COUNTS[level_index]
        difference = DIRECTION_DIFFERENCES_DEG[level_index]
        target = state.rng.choice(tuple(_DIRECTION_ANGLES))
        target_angle = _DIRECTION_ANGLES[target]
        orientation_count = (1, 1, 2, 2, 3)[level_index]
        if orientation_count == 1:
            sign = state.rng.choice((-1, 1))
            distractor_angles = (
                (target_angle + (sign * difference)) % 360,
            )
        elif orientation_count == 2:
            distractor_angles = (
                (target_angle - difference) % 360,
                (target_angle + difference) % 360,
            )
        else:
            third_sign = state.rng.choice((-1, 1))
            third_offset = third_sign * difference * 2
            distractor_angles = (
                (target_angle - difference) % 360,
                (target_angle + difference) % 360,
                (target_angle + third_offset) % 360,
            )

        rotations = [
            distractor_angles[index % orientation_count]
            for index in range(item_count - 1)
        ]
        state.rng.shuffle(rotations)
        target_index = state.rng.randrange(item_count)
        rotations.insert(target_index, target_angle)
        arrows = [
            RunStore._arrow_for_angle(rotation)
            for rotation in rotations
        ]
        accessible_sequence = [
            RunStore._accessible_arrow_label(rotation)
            for rotation in rotations
        ]
        if difference % 45 == 0:
            prompt = 'Find the odd arrow: {}'.format('  '.join(arrows))
        else:
            prompt = 'Find the one arrow pointing in a different direction.'
        return {
            'kind': 'direction',
            'prompt': prompt,
            'expected_answer': target,
            'data': {
                'arrows': arrows,
                'rotations': rotations,
                'accessible_sequence': accessible_sequence,
                'items': [
                    {
                        'glyph': '↑',
                        'rotation_deg': rotation,
                        'accessible_label': accessible_label,
                    }
                    for rotation, accessible_label in zip(
                        rotations,
                        accessible_sequence,
                    )
                ],
                'item_count': item_count,
                'grid_columns': isqrt(item_count - 1) + 1,
                'target_difference_deg': difference,
                'distractor_orientation_count': orientation_count,
            },
            'choices': list(_DIRECTION_ANGLES),
            'aliases': brain_direction_focus.ANSWER_ALIASES,
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
    def _generate_symbol_match(state):
        sequence_length = SYMBOL_SEQUENCE_LENGTHS[state.level - 1]
        if state.level <= 3:
            token_pool = _SYMBOL_STANDARD_TOKENS
        elif state.level == 4:
            token_pool = _SYMBOL_ROTATION_TOKENS
        else:
            token_pool = _SYMBOL_MARK_TOKENS
        left = [
            state.rng.choice(token_pool)
            for _index in range(sequence_length)
        ]
        right = list(left)
        matches = RunStore._next_balanced_truth(
            state,
            brain_symbol_match.SLUG,
        )
        mismatch_index = None
        mismatch_kind = None
        if not matches:
            mismatch_index = state.rng.randrange(sequence_length)
            mismatch_kind, right[mismatch_index] = (
                RunStore._symbol_mismatch(
                    state,
                    left[mismatch_index],
                )
            )
        left_display = ' '.join(left)
        right_display = ' '.join(right)
        return {
            'kind': 'choice',
            'prompt': 'Symbols: {}  |  {}. Same?'.format(
                left_display,
                right_display,
            ),
            'expected_answer': 'yes' if matches else 'no',
            'data': {
                'symbols': [left_display, right_display],
                'left_symbols': left,
                'right_symbols': right,
                'sequence_length': sequence_length,
                'left_tokens': [
                    RunStore._public_symbol_token(symbol)
                    for symbol in left
                ],
                'right_tokens': [
                    RunStore._public_symbol_token(symbol)
                    for symbol in right
                ],
            },
            'choices': ['yes', 'no'],
            'aliases': brain_symbol_match.ANSWER_ALIASES,
        }

    @staticmethod
    def _public_symbol_token(symbol):
        token = dict(_SYMBOL_TOKENS[symbol])
        token['symbol'] = symbol
        return token

    @staticmethod
    def _symbol_mismatch(state, left_symbol):
        if state.level == 4:
            return 'rotation', _SYMBOL_ROTATION_PARTNERS[left_symbol]
        if state.level == 5:
            return 'internal_mark', _SYMBOL_MARK_PARTNERS[left_symbol]

        feature_rules = {
            1: ('shape_and_fill', ('shape', 'fill'), ()),
            2: ('shape', ('shape',), ('fill',)),
            3: ('fill', ('fill',), ('shape',)),
        }
        mismatch_kind, different_fields, matching_fields = (
            feature_rules[state.level]
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
    def _generate_word_scramble(state):
        answer = state.rng.choice(
            _SCRAMBLE_WORDS_BY_LEVEL[state.level],
        )
        scrambled = state.rng.choice(
            _SCRAMBLE_DERANGEMENTS[(state.level, answer)],
        )
        moved_positions, preserved_bigrams = _scramble_metrics(
            answer,
            scrambled,
        )
        hint = None
        if state.level == 1:
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
        }
