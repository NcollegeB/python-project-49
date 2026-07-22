"""Local Flask application for the Brain Games web interface."""

from flask import Blueprint
from flask import abort
from flask import current_app
from flask import Flask
from flask import jsonify
from flask import render_template
from flask import request
from werkzeug.exceptions import RequestEntityTooLarge

from brain_games.web_engine import InvalidAnswerError
from brain_games.web_engine import GAME_CATALOG
from brain_games.web_engine import RunEndedError
from brain_games.web_engine import RunStore
from brain_games.web_engine import StaleRoundError
from brain_games.web_engine import UnknownGameError
from brain_games.web_engine import UnknownRunError
from brain_games.web_engine import game_catalog


ERROR_STATUS = {
    UnknownGameError: (404, 'unknown_game'),
    UnknownRunError: (404, 'unknown_run'),
    StaleRoundError: (409, 'stale_round'),
    RunEndedError: (409, 'run_ended'),
    InvalidAnswerError: (400, 'invalid_answer'),
}

GAME_SLUGS = frozenset(game['slug'] for game in GAME_CATALOG)

CSP = '; '.join((
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "font-src 'self'",
    "media-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
))

routes = Blueprint('brain_games', __name__)


def _error_response(code, message, status):
    return jsonify({
        'error': code,
        'message': message,
    }), status


def _request_payload(required):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, _error_response(
            'invalid_request',
            'Request body must be a JSON object.',
            400,
        )
    missing = [name for name in required if name not in payload]
    if missing:
        return None, _error_response(
            'invalid_request',
            'Missing required field: {}.'.format(missing[0]),
            400,
        )
    return payload, None


def _parse_limit(raw_limit):
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return None
    if limit < 1 or limit > 100:
        return None
    return limit


def _is_text(value):
    return isinstance(value, str) and bool(value.strip())


def _store():
    return current_app.extensions['brain_games_run_store']


def _handle_engine_error(error):
    status, code = ERROR_STATUS[type(error)]
    return _error_response(code, str(error), status)


def _handle_request_too_large(error):
    if request.path.startswith('/api/'):
        return _error_response(
            'request_too_large',
            'Request body exceeds the 16 KiB limit.',
            413,
        )
    return error


def _add_browser_headers(response):
    response.headers['Content-Security-Policy'] = CSP
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Permissions-Policy'] = (
        'camera=(), geolocation=(), microphone=()'
    )
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@routes.get('/')
@routes.get('/play/<slug>')
def index(slug=None):
    if slug is not None and slug not in GAME_SLUGS:
        abort(404)
    return render_template('index.html', initial_game=slug)


@routes.get('/healthz')
def health():
    return jsonify({'status': 'ok'})


@routes.get('/api/games')
def games():
    return jsonify({'games': game_catalog()})


@routes.post('/api/runs')
def create_run():
    payload, error = _request_payload(('game', 'player'))
    if error:
        return error
    if not _is_text(payload['game']) or not _is_text(payload['player']):
        return _error_response(
            'invalid_request',
            'game and player must be non-empty strings.',
            400,
        )
    return jsonify(
        _store().create(payload['game'], payload['player']),
    ), 201


@routes.post('/api/runs/<run_id>/answers')
def answer_run(run_id):
    payload, error = _request_payload(('round_id', 'answer'))
    if error:
        return error
    if not _is_text(payload['round_id']):
        return _error_response(
            'invalid_request',
            'round_id must be a non-empty string.',
            400,
        )
    return jsonify(_store().answer(
        run_id,
        payload['round_id'],
        payload['answer'],
    ))


@routes.post('/api/runs/<run_id>/quit')
def quit_run(run_id):
    return jsonify(_store().quit(run_id))


@routes.get('/api/leaderboard')
def leaderboard():
    limit = _parse_limit(request.args.get('limit', '10'))
    if limit is None:
        return _error_response(
            'invalid_request',
            'limit must be an integer from 1 through 100.',
            400,
        )
    game = request.args.get('game') or None
    player = request.args.get('player')
    if player is not None and not _is_text(player):
        return _error_response(
            'invalid_request',
            'player must be a non-empty string.',
            400,
        )
    return jsonify({'entries': _store().leaders(
        game=game,
        limit=limit,
        player=player,
    )})


def create_app(test_config=None, run_store=None):
    """Build the local web application without external services."""
    application = Flask(__name__)
    application.config.from_mapping(
        JSON_SORT_KEYS=False,
        MAX_CONTENT_LENGTH=16 * 1024,
    )
    if test_config:
        application.config.update(test_config)

    store = run_store or RunStore()
    application.extensions['brain_games_run_store'] = store

    for error_type in ERROR_STATUS:
        application.register_error_handler(
            error_type,
            _handle_engine_error,
        )
    application.register_error_handler(
        RequestEntityTooLarge,
        _handle_request_too_large,
    )
    application.after_request(_add_browser_headers)
    application.register_blueprint(routes)
    return application


app = create_app()


if __name__ == '__main__':
    app.run()
