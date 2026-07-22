"""Small, dependency-free terminal UI helpers for Brain Games."""

import os
import shutil
import sys
import unicodedata


MAX_PANEL_WIDTH = 72
MIN_PANEL_WIDTH = 40
MAX_LIVES = 3
GAME_LABELS = {
    'calc': 'Calculator',
    'culmination': 'Culmination',
    'even': 'Even or Odd',
    'direction-focus': 'Direction Focus',
    'gcd': 'GCD',
    'number-memory': 'Number Memory',
    'prime': 'Prime Number',
    'progression': 'Progression',
    'symbol-match': 'Symbol Match',
    'verbal-memory': 'Verbal Memory',
    'word-scramble': 'Word Scramble',
}


def _output_stream(output):
    return output if output is not None else sys.stdout


def _is_tty(output):
    try:
        return bool(output.isatty())
    except (AttributeError, OSError):
        return False


def _terminal_width(output):
    """Return a useful terminal width for both real and fake streams."""
    if _is_tty(output):
        try:
            return max(4, os.get_terminal_size(output.fileno()).columns)
        except (AttributeError, OSError, ValueError):
            pass
    return max(4, shutil.get_terminal_size(fallback=(80, 24)).columns)


def _clean_text(value):
    """Turn arbitrary values into one safe, printable terminal line."""
    text = str(value)
    cleaned = []
    for character in text:
        if character in '\n\r\t':
            cleaned.append(' ')
        elif not unicodedata.category(character).startswith('C'):
            cleaned.append(character)
    return ''.join(cleaned)


def _character_width(character):
    if unicodedata.combining(character):
        return 0
    if unicodedata.east_asian_width(character) in {'F', 'W'}:
        return 2
    return 1


def _display_width(text):
    return sum(_character_width(character) for character in text)


def _take_prefix(text, width):
    result = []
    used_width = 0
    for character in text:
        character_width = _character_width(character)
        if used_width + character_width > width:
            break
        if character_width or result:
            result.append(character)
            used_width += character_width
    return ''.join(result)


def _truncate(text, width):
    """Truncate text to a display width without overflowing a panel."""
    if width <= 0:
        return ''
    if _display_width(text) <= width:
        return text
    if width == 1:
        return '…'

    return _take_prefix(text, width - 1) + '…'


def _fit_text(value, width, alignment='left'):
    text = _truncate(_clean_text(value), width)
    remaining = max(0, width - _display_width(text))
    if alignment == 'right':
        return (' ' * remaining) + text
    if alignment == 'center':
        left_padding = remaining // 2
        return ''.join((
            ' ' * left_padding,
            text,
            ' ' * (remaining - left_padding),
        ))
    return text + (' ' * remaining)


def _write(output, text):
    output.write(text)
    try:
        output.flush()
    except (AttributeError, OSError):
        pass


def clear_screen(output=None):
    """Clear a real terminal, leaving redirected and test output untouched."""
    stream = _output_stream(output)
    if not _is_tty(stream):
        return False
    _write(stream, '\033[2J\033[H')
    return True


def render_panel(title, lines, output=None):
    """Render a centered Unicode panel and return the rendered text."""
    stream = _output_stream(output)
    if isinstance(lines, str):
        panel_lines = [lines]
    else:
        panel_lines = list(lines or [])

    clean_title = _clean_text(title)
    clean_lines = [_clean_text(line) for line in panel_lines]
    line_widths = [_display_width(clean_title)]
    line_widths.extend(_display_width(line) for line in clean_lines)
    longest_line = max(line_widths, default=0)

    terminal_width = _terminal_width(stream)
    desired_width = max(MIN_PANEL_WIDTH, longest_line + 4)
    panel_width = min(MAX_PANEL_WIDTH, desired_width, terminal_width)
    panel_width = max(4, panel_width)
    inner_width = panel_width - 2
    text_width = max(0, panel_width - 4)
    margin = ' ' * max(0, (terminal_width - panel_width) // 2)

    top = '┌' + ('─' * inner_width) + '┐'
    divider = '├' + ('─' * inner_width) + '┤'
    bottom = '└' + ('─' * inner_width) + '┘'

    rendered_lines = [top]
    rendered_lines.append(
        '│ ' + _fit_text(clean_title, text_width, 'center') + ' │'
    )
    rendered_lines.append(divider)
    if not clean_lines:
        clean_lines.append('')
    for line in clean_lines:
        rendered_lines.append(
            '│ ' + _fit_text(line, text_width) + ' │'
        )
    rendered_lines.append(bottom)

    rendered = '\n'.join(margin + line for line in rendered_lines) + '\n'
    _write(stream, rendered)
    return rendered


def render_game(
        game_name,
        rules,
        question,
        score,
        lives,
        feedback=None,
        output=None):
    """Render one question together with its score and three-life HUD."""
    try:
        safe_lives = int(lives)
    except (TypeError, ValueError):
        safe_lives = 0
    safe_lives = min(MAX_LIVES, max(0, safe_lives))
    hearts = ('♥' * safe_lives) + ('♡' * (MAX_LIVES - safe_lives))

    lines = [
        rules,
        '',
        'Score: {}    Lives: {}/{} {}'.format(
            score,
            safe_lives,
            MAX_LIVES,
            hearts,
        ),
        '',
        'Question: {}'.format(question),
    ]
    if feedback:
        lines.extend(['', feedback])
    return render_panel(game_name, lines, output)


def _entry_value(entry, *keys, default=''):
    for key in keys:
        if key in entry:
            return entry[key]
    return default


def _leaderboard_row(rank, player, game, score):
    return '{} {} {} {}'.format(
        _fit_text(rank, 2, 'right'),
        _fit_text(player, 14),
        _fit_text(game, 11),
        _fit_text(score, 6, 'right'),
    )


def _game_label(game):
    slug = str(game).strip().casefold()
    return GAME_LABELS.get(
        slug,
        slug.replace('_', ' ').replace('-', ' ').title(),
    )


def render_leaderboard(entries, title='LEADERBOARD', output=None):
    """Render leaderboard entry dictionaries as a compact score table."""
    entries = list(entries or [])
    if not entries:
        return render_panel(title, ['No scores yet.'], output)

    header = _leaderboard_row('#', 'PLAYER', 'GAME', 'SCORE')
    lines = [header, '─' * _display_width(header)]
    for position, entry in enumerate(entries, start=1):
        if not hasattr(entry, 'get'):
            entry = {}
        rank = _entry_value(entry, 'rank', default=position)
        player = _entry_value(
            entry,
            'player',
            'player_name',
            'name',
            default='Player',
        )
        game = _entry_value(entry, 'game', 'game_name', default='—')
        game = _game_label(game)
        score = _entry_value(entry, 'score', default=0)
        lines.append(_leaderboard_row(rank, player, game, score))
    return render_panel(title, lines, output)
