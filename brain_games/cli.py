import sys

from brain_games.engine import ask_player_name
from brain_games.engine import run
from brain_games.games import brain_calc
from brain_games.games import brain_even
from brain_games.games import brain_gcd
from brain_games.games import brain_prime
from brain_games.games import brain_progression
from brain_games.leaderboard import Leaderboard
from brain_games.ui import clear_screen
from brain_games.ui import render_leaderboard
from brain_games.ui import render_panel


GAMES = (
    ('1', brain_even),
    ('2', brain_calc),
    ('3', brain_gcd),
    ('4', brain_progression),
    ('5', brain_prime),
)


def welcome_user(input_func=input, output=sys.stdout):
    """Keep the original greeting available for library users."""
    print('Welcome to the Brain Games!', file=output)
    name = ask_player_name(input_func, output)
    print('Hello, {}!'.format(name), file=output)
    return name


def _menu_lines(player_name, message=''):
    lines = [
        'Player: {}'.format(player_name),
        'Three mistakes end a run. Every correct answer scores 1.',
        '',
    ]
    for number, game in GAMES:
        lines.append('  {}. {}'.format(number, game.NAME))
    lines.extend([
        '  6. Leaderboard',
        '  7. Quit',
    ])
    if message:
        lines.extend(['', message])
    return lines


def _pause(input_func):
    try:
        input_func('Press Enter to return to the game hub...')
    except (EOFError, KeyboardInterrupt):
        pass


def _clear_if_requested(clear, output):
    if clear:
        clear_screen(output)


def _read_choice(input_func, output):
    try:
        return input_func('Choose an option: ').strip().casefold()
    except (EOFError, KeyboardInterrupt):
        print('', file=output)
        return '7'


def _find_game(choice):
    return next(
        (game for number, game in GAMES if number == choice),
        None,
    )


def _show_all_leaders(board, input_func, output, clear):
    _clear_if_requested(clear, output)
    render_leaderboard(
        board.top(limit=10),
        'ALL-GAME LEADERBOARD',
        output,
    )
    _pause(input_func)


def _show_goodbye(player_name, output, clear):
    _clear_if_requested(clear, output)
    render_panel(
        'THANKS FOR PLAYING',
        ['See you next time, {}!'.format(player_name)],
        output,
    )


def main(
        input_func=input,
        output=sys.stdout,
        leaderboard=None,
        clear=True):
    """Launch the terminal game hub."""
    board = leaderboard or Leaderboard()
    _clear_if_requested(clear, output)
    render_panel(
        'BRAIN GAMES ARCADE',
        [
            'Five endless games. Three lives per run.',
            'Set a high score and climb the leaderboard!',
        ],
        output,
    )
    player_name = ask_player_name(input_func, output)
    message = ''

    while True:
        _clear_if_requested(clear, output)
        render_panel(
            'BRAIN GAMES ARCADE',
            _menu_lines(player_name, message),
            output,
        )
        message = ''
        choice = _read_choice(input_func, output)
        selected_game = _find_game(choice)
        if selected_game is not None:
            run(
                selected_game,
                player_name=player_name,
                leaderboard=board,
                input_func=input_func,
                output=output,
                clear=clear,
            )
            _pause(input_func)
        elif choice in {'6', 'l', 'leaderboard'}:
            _show_all_leaders(board, input_func, output, clear)
        elif choice in {'7', 'q', 'quit', 'exit'}:
            _show_goodbye(player_name, output, clear)
            return
        else:
            message = "Choose 1-7, or enter 'q' to quit."


if __name__ == '__main__':
    main()
