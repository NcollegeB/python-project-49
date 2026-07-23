"""Server-side game engine for the browser interface.

The terminal games predate the web application and some of them keep session
state in module globals.  This module deliberately owns all state per run so
that concurrent browser sessions cannot affect one another.
"""

import copy
import random
import threading
import uuid

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


class _RunState:
    """Private mutable state for one browser run."""

    def __init__(self, run_id, game_slug, player, rng):
        self.run_id = run_id
        self.game_slug = game_slug
        self.player = player
        self.rng = rng
        self.score = 0
        self.lives = MAX_LIVES
        self.ended = False
        self.quit_early = False
        self.recorded = False
        self.round = None
        self.digit_count = brain_number_memory.MIN_DIGITS
        self.seen_words = set()
        self.new_word_index = 0
        self.game_bag = []
        self.last_source_slug = None
        self.cycle_position = None


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

    def create(self, game_slug, player):
        """Create a run and return its first public round."""
        slug, clean_player = self._validated_run_owner(game_slug, player)
        with self._lock:
            state = _RunState(
                _new_id(),
                slug,
                clean_player,
                self._new_rng(),
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
        with self._lock:
            return self._leaderboard.top(
                limit=limit,
                game=game_slug,
                player=player,
            )

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

        submitted, canonical = self._validate_answer(
            answer,
            active_round,
        )
        correct = (
            canonical == _normalise(active_round['expected_answer'])
        )
        if correct:
            state.score += 1
        else:
            state.lives -= 1

        self._record_source_result(
            state,
            active_round['source_slug'],
            correct,
        )
        result = self._answer_result(
            active_round,
            current_round_id,
            submitted,
            correct,
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
    def _answer_result(active_round, round_id, submitted, correct):
        return {
            'round_id': round_id,
            'correct': correct,
            'submitted_answer': submitted,
            'expected_answer': str(active_round['expected_answer']),
            'source_slug': active_round['source_slug'],
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
        self._leaderboard.record(
            state.player,
            state.game_slug,
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
    def _record_source_result(state, source_slug, correct):
        if source_slug != brain_number_memory.SLUG:
            return
        change = 1 if correct else -1
        state.digit_count = min(
            brain_number_memory.MAX_DIGITS,
            max(
                brain_number_memory.MIN_DIGITS,
                state.digit_count + change,
            ),
        )

    @staticmethod
    def _validate_answer(answer, active_round):
        if answer is None:
            raise InvalidAnswerError(answer, active_round['choices'])
        submitted = str(answer).strip()
        if not submitted or _normalise(submitted) in {'q', 'quit'}:
            raise InvalidAnswerError(answer, active_round['choices'])

        canonical = _normalise(submitted)
        aliases = active_round['aliases']
        canonical = _normalise(aliases.get(canonical, canonical))
        choices = active_round['choices']
        if choices and canonical not in {
                _normalise(choice) for choice in choices}:
            raise InvalidAnswerError(answer, choices)
        return submitted, canonical

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
    def _generate_even(state):
        number = state.rng.randint(0, brain_even.MAX_VALUE)
        answer = 'yes' if brain_even.is_even(number) else 'no'
        return {
            'kind': 'choice',
            'prompt': 'Is {} even?'.format(number),
            'expected_answer': answer,
            'data': {'number': number},
            'choices': ['yes', 'no'],
            'aliases': brain_even.ANSWER_ALIASES,
        }

    @staticmethod
    def _generate_calc(state):
        left = state.rng.randint(0, brain_calc.CALC_MAX_VALUE)
        right = state.rng.randint(0, brain_calc.CALC_MAX_VALUE)
        operation = state.rng.choice(('+', '*', '-'))
        if operation == '+':
            answer = left + right
            shown_left, shown_right = left, right
        elif operation == '*':
            answer = left * right
            shown_left, shown_right = left, right
        else:
            shown_left, shown_right = max(left, right), min(left, right)
            answer = shown_left - shown_right
        expression = '{} {} {}'.format(
            shown_left,
            operation,
            shown_right,
        )
        return {
            'kind': 'number',
            'prompt': expression,
            'expected_answer': str(answer),
            'data': {
                'expression': expression,
                'operation': operation,
                'operands': [shown_left, shown_right],
            },
        }

    @staticmethod
    def _generate_gcd(state):
        first = state.rng.randint(1, brain_gcd.MAX_VALUE)
        second = state.rng.randint(1, brain_gcd.MAX_VALUE)
        answer = brain_gcd.get_gcd(first, second)
        return {
            'kind': 'number',
            'prompt': '{} {}'.format(first, second),
            'expected_answer': str(answer),
            'data': {'numbers': [first, second]},
        }

    @staticmethod
    def _generate_progression(state):
        initial = state.rng.randint(0, brain_progression.MAX_VALUE)
        length = state.rng.randint(
            brain_progression.MIN_SEQUENCE_LENGTH,
            brain_progression.MAX_SEQUENCE_LENGTH,
        )
        difference = state.rng.randint(1, brain_progression.DIFFERENCE)
        sequence = brain_progression.get_sequence(
            initial,
            difference,
            length,
        )
        hidden_index = state.rng.randrange(len(sequence))
        answer = sequence[hidden_index]
        visible = list(sequence)
        visible[hidden_index] = '..'
        return {
            'kind': 'number',
            'prompt': ' '.join(visible),
            'expected_answer': answer,
            'data': {
                'sequence': visible,
                'hidden_index': hidden_index,
            },
        }

    @staticmethod
    def _generate_prime(state):
        number = state.rng.randint(0, brain_prime.MAX_VALUE)
        answer = 'yes' if brain_prime.is_prime(number) else 'no'
        return {
            'kind': 'choice',
            'prompt': 'Is {} prime?'.format(number),
            'expected_answer': answer,
            'data': {'number': number},
            'choices': ['yes', 'no'],
            'aliases': brain_prime.ANSWER_ALIASES,
        }

    @staticmethod
    def _generate_number_memory(state):
        digits = state.digit_count
        if digits == 1:
            lower_bound = 0
        else:
            lower_bound = 10 ** (digits - 1)
        upper_bound = (10 ** digits) - 1
        number = str(state.rng.randint(lower_bound, upper_bound))
        return {
            'kind': 'memory',
            'prompt': number,
            'expected_answer': number,
            'data': {'digits': digits},
            'preview_ms': int(
                brain_number_memory.PREVIEW_SECONDS * 1000,
            ),
            'hidden_prompt': brain_number_memory.HIDDEN_QUESTION,
        }

    @staticmethod
    def _generate_verbal_memory(state):
        ask_seen = bool(state.seen_words) and state.rng.choice((True, False))
        if ask_seen:
            word = state.rng.choice(tuple(sorted(state.seen_words)))
            answer = 'yes'
        else:
            word = RunStore._choose_new_word(state)
            answer = 'no'
        state.seen_words.add(word)
        return {
            'kind': 'choice',
            'prompt': 'Have you seen "{}" before?'.format(word),
            'expected_answer': answer,
            'data': {'word': word},
            'choices': ['yes', 'no'],
            'aliases': brain_verbal_memory.ANSWER_ALIASES,
        }

    @staticmethod
    def _choose_new_word(state):
        index = state.new_word_index
        state.new_word_index += 1
        components = []
        word_count = len(brain_verbal_memory.WORDS)
        while True:
            index, remainder = divmod(index, word_count)
            components.append(brain_verbal_memory.WORDS[remainder])
            if index == 0:
                break
            index -= 1
        return '-'.join(reversed(components))

    @staticmethod
    def _generate_direction_focus(state):
        directions = tuple(brain_direction_focus.DIRECTIONS)
        target = state.rng.choice(directions)
        distractors = tuple(
            direction for direction in directions
            if direction != target
        )
        distractor = state.rng.choice(distractors)
        target_index = state.rng.randrange(
            brain_direction_focus.ARROW_COUNT,
        )
        arrows = [
            brain_direction_focus.DIRECTIONS[distractor]
        ] * brain_direction_focus.ARROW_COUNT
        arrows[target_index] = brain_direction_focus.DIRECTIONS[target]
        return {
            'kind': 'direction',
            'prompt': 'Find the odd arrow: {}'.format('  '.join(arrows)),
            'expected_answer': target,
            'data': {'arrows': arrows},
            'choices': list(directions),
            'aliases': brain_direction_focus.ANSWER_ALIASES,
        }

    @staticmethod
    def _generate_symbol_match(state):
        left = state.rng.choice(brain_symbol_match.SYMBOLS)
        matches = state.rng.choice((True, False))
        if matches:
            right = left
        else:
            alternatives = tuple(
                symbol for symbol in brain_symbol_match.SYMBOLS
                if symbol != left
            )
            right = state.rng.choice(alternatives)
        return {
            'kind': 'choice',
            'prompt': 'Symbols: {}  |  {}. Same?'.format(left, right),
            'expected_answer': 'yes' if matches else 'no',
            'data': {'symbols': [left, right]},
            'choices': ['yes', 'no'],
            'aliases': brain_symbol_match.ANSWER_ALIASES,
        }

    @staticmethod
    def _generate_word_scramble(state):
        answer = state.rng.choice(brain_word_scramble.WORDS)
        scrambled = RunStore._scramble_word(state.rng, answer)
        return {
            'kind': 'text',
            'prompt': 'Unscramble: {}'.format(scrambled),
            'expected_answer': answer,
            'data': {'scrambled': scrambled},
        }

    @staticmethod
    def _scramble_word(rng, word):
        for _attempt in range(12):
            scrambled = ''.join(rng.sample(word, len(word)))
            if scrambled != word:
                return scrambled
        return word[1:] + word[:1]
