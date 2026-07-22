from dataclasses import dataclass
import sys

from brain_games.leaderboard import Leaderboard
from brain_games.ui import clear_screen
from brain_games.ui import render_game
from brain_games.ui import render_leaderboard
from brain_games.ui import render_panel


MAX_VALUE = 100
MAX_LIVES = 3


@dataclass(frozen=True)
class GameResult:
    player: str
    game: str
    score: int
    lives: int
    quit_early: bool = False


def _game_name(game):
    return getattr(game, 'NAME', game.__name__.split('.')[-1].title())


def _game_slug(game):
    default = game.__name__.split('.')[-1].replace('brain_', '')
    return getattr(game, 'SLUG', default)


def _normalise_answer(answer):
    return str(answer).strip().casefold()


def _clear_if_requested(clear, output):
    if clear:
        clear_screen(output)


def _read_answer(input_func, output):
    try:
        answer = input_func('Your answer (q to leave): ')
    except (EOFError, KeyboardInterrupt):
        print('', file=output)
        return '', True
    return answer, _normalise_answer(answer) in {'q', 'quit'}


def ask_player_name(input_func=input, output=sys.stdout):
    """Ask for a display name and return a safe, non-empty value."""
    while True:
        try:
            name = input_func('Player name: ').strip()
        except (EOFError, KeyboardInterrupt):
            print('', file=output)
            return 'Player'
        if name:
            return name[:24]
        print('Please enter a name.', file=output)


def play_game(
        game,
        player_name,
        input_func=input,
        output=sys.stdout,
        clear=True):
    """Play until three answers are missed, returning the final result."""
    score = 0
    lives = MAX_LIVES
    feedback = 'Answer correctly to earn one point.'
    quit_early = False

    while lives > 0:
        question, expected_answer = game.get_question_and_answer()
        _clear_if_requested(clear, output)
        render_game(
            _game_name(game),
            game.RULES,
            str(question),
            score,
            lives,
            feedback,
            output,
        )

        user_answer, quit_early = _read_answer(input_func, output)
        if quit_early:
            break

        if _normalise_answer(user_answer) == _normalise_answer(
                expected_answer):
            score += 1
            feedback = 'Correct! You earned 1 point.'
        else:
            lives -= 1
            feedback = (
                "'{}' is incorrect. The answer was '{}'."
                .format(user_answer, expected_answer)
            )

    _clear_if_requested(clear, output)
    heading = 'RUN ENDED' if quit_early else 'GAME OVER'
    render_panel(
        heading,
        [
            '{} played {}'.format(player_name, _game_name(game)),
            feedback,
            '',
            'Final score: {}'.format(score),
            'Lives remaining: {}/{}'.format(lives, MAX_LIVES),
        ],
        output,
    )
    return GameResult(
        player=player_name,
        game=_game_slug(game),
        score=score,
        lives=lives,
        quit_early=quit_early,
    )


def run(
        game,
        player_name=None,
        leaderboard=None,
        input_func=input,
        output=sys.stdout,
        clear=True):
    """Run one game, save the score, and show that game's leaders."""
    if player_name is None:
        _clear_if_requested(clear, output)
        render_panel('BRAIN GAMES', ['Three lives. One point per answer.'],
                     output)
        player_name = ask_player_name(input_func, output)

    result = play_game(
        game,
        player_name,
        input_func=input_func,
        output=output,
        clear=clear,
    )
    board = leaderboard or Leaderboard()
    try:
        board.record(result.player, result.game, result.score)
    except OSError:
        render_panel(
            'LEADERBOARD UNAVAILABLE',
            ['Your score could not be saved.'],
            output,
        )
    else:
        render_leaderboard(
            board.top(limit=5, game=result.game),
            '{} LEADERS'.format(_game_name(game).upper()),
            output,
        )
    return result
