import sys

from brain_games.engine import ask_player_name
from brain_games.engine import run
from brain_games.games import brain_calc
from brain_games.games import brain_even
from brain_games.games import brain_direction_focus
from brain_games.games import brain_gcd
from brain_games.games import brain_number_memory
from brain_games.games import brain_prime
from brain_games.games import brain_progression
from brain_games.games import brain_symbol_match
from brain_games.games import brain_verbal_memory
from brain_games.games import brain_word_scramble
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
    ('6', brain_number_memory),
    ('7', brain_verbal_memory),
    ('8', brain_direction_focus),
    ('9', brain_symbol_match),
    ('10', brain_word_scramble),
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
        lines.append(
            '  {}. {} [{}]'.format(
                number,
                game.NAME,
                getattr(game, 'CATEGORY', 'General'),
            )
        )
    lines.extend([
        '  L. Leaderboard',
        '  Q. Quit',
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
        return 'q'


def _find_game(choice):
    normalised_choice = str(choice).strip().casefold()
    for number, game in GAMES:
        choices = {
            number,
            game.NAME.casefold(),
            game.SLUG.casefold(),
        }
        if normalised_choice in choices:
            return game
    return None


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
            'Ten endless games. Three lives per run.',
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
        elif choice in {'l', 'leaderboard', 'leaders'}:
            _show_all_leaders(board, input_func, output, clear)
        elif choice in {'q', 'quit', 'exit'}:
            _show_goodbye(player_name, output, clear)
            return
        else:
            message = 'Choose 1-10, L for leaders, or Q to quit.'


if __name__ == '__main__':
    main()
