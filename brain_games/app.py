"""Flask application for the BrainHacker web interface."""

import os
import secrets
from datetime import timedelta

from flask import Blueprint
from flask import abort
from flask import current_app
from flask import Flask
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import session
from flask import url_for
from werkzeug.exceptions import RequestEntityTooLarge

from brain_games.accounts import AccountStore
from brain_games.accounts import AccountValidationError
from brain_games.accounts import DuplicateAccountError
from brain_games.benchmarks import all_benchmarks
from brain_games.benchmarks import benchmark_for
from brain_games.benchmarks import UnknownBenchmarkError
from brain_games.persistence import build_database_stores
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
CATALOG_BY_SLUG = {game['slug']: game for game in GAME_CATALOG}
SESSION_USER_KEY = 'brainhacker_username'
CSRF_SESSION_KEY = 'brainhacker_csrf_token'
ACCOUNT_PLAYER_PREFIX = 'account:'

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


def _accounts():
    return current_app.extensions['brain_games_account_store']


def _account_player(account):
    return '{}{}'.format(ACCOUNT_PLAYER_PREFIX, account['account_id'])


def _lookup_account(username):
    try:
        return _accounts().get(username)
    except AccountValidationError:
        return None


def _account_from_player(player):
    if not isinstance(player, str):
        return None
    if not player.startswith(ACCOUNT_PLAYER_PREFIX):
        return None
    account_id = player[len(ACCOUNT_PLAYER_PREFIX):]
    return _accounts().get_by_id(account_id)


def _lookup_accounts_many(usernames=(), account_ids=()):
    accounts = _accounts()
    lookup_many = getattr(accounts, 'lookup_many', None)
    if callable(lookup_many):
        return lookup_many(
            usernames=usernames,
            account_ids=account_ids,
        )
    return _lookup_accounts_individually(
        accounts,
        usernames,
        account_ids,
    )


def _lookup_accounts_individually(accounts, usernames, account_ids):
    return {
        'by_username': _lookup_usernames_individually(accounts, usernames),
        'by_id': _lookup_ids_individually(accounts, account_ids),
    }


def _lookup_usernames_individually(accounts, usernames):
    by_username = {}
    for username in usernames:
        try:
            account = accounts.get(username)
        except AccountValidationError:
            continue
        if account is not None:
            by_username[account['username']] = account
    return by_username


def _lookup_ids_individually(accounts, account_ids):
    by_id = {}
    for account_id in account_ids:
        account = accounts.get_by_id(account_id)
        if account is not None:
            by_id[account['account_id']] = account
    return by_id


def _public_run(payload):
    public = dict(payload)
    player = public.get('player')
    if isinstance(player, str) and player.startswith(ACCOUNT_PLAYER_PREFIX):
        account = _account_from_player(player)
        public['player'] = (
            account['username'] if account is not None else 'signed-in player'
        )
    return public


def _current_user():
    username = session.get(SESSION_USER_KEY)
    if not isinstance(username, str):
        return None
    try:
        account = _accounts().get(username)
    except AccountValidationError:
        account = None
    if account is None:
        session.pop(SESSION_USER_KEY, None)
    return account


def _csrf_token():
    token = session.get(CSRF_SESSION_KEY)
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def _has_valid_csrf():
    expected = session.get(CSRF_SESSION_KEY)
    supplied = request.form.get('csrf_token')
    checks = (
        isinstance(expected, str),
        isinstance(supplied, str),
        bool(expected),
    )
    return all(checks) and secrets.compare_digest(expected, supplied)


def _auth_form(template, error=None, status=200):
    return render_template(
        template,
        error=error,
        form={'username': request.form.get('username', '').strip()},
    ), status


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
    private_page = request.path in {
        '/login', '/register', '/logout', '/player', '/stats',
    }
    if any((
        request.path.startswith('/api/'),
        private_page,
        SESSION_USER_KEY in session,
    )):
        response.headers['Cache-Control'] = 'no-store'
    return response


@routes.app_context_processor
def _template_context():
    return {
        'current_user': _current_user(),
        'csrf_token': _csrf_token(),
    }


@routes.get('/')
@routes.get('/play/<slug>')
def index(slug=None):
    if slug is not None and slug not in GAME_SLUGS:
        abort(404)
    return render_template('index.html', initial_game=slug)


@routes.get('/stats')
def statistics():
    rows = _score_rows(_current_user())

    return render_template(
        'stats.html',
        benchmarks=rows,
        personal_stats=rows,
    )


def _score_rows(user):
    personal_bests = {}
    if user is not None:
        entries = _store().leaders(
            player=_account_player(user),
            limit=100,
        )
        personal_bests = {
            entry['game']: entry
            for entry in entries
        }

    rows = []
    for baseline in all_benchmarks():
        entry = personal_bests.get(baseline['slug'])
        row = benchmark_for(
            baseline['slug'],
            entry['score'] if entry is not None else None,
        )
        row['category'] = CATALOG_BY_SLUG[baseline['slug']]['category']
        row['personal_score'] = (
            entry['score'] if entry is not None else None
        )
        row['played_at'] = (
            entry['played_at'] if entry is not None else None
        )
        rows.append(row)
    return rows


@routes.get('/player')
def player():
    user = _current_user()
    rows = _score_rows(user)
    return render_template(
        'player.html',
        score_rows=rows,
        played_count=sum(
            row['personal_score'] is not None
            for row in rows
        ),
    )


@routes.route('/login', methods=('GET', 'POST'))
def login():
    if request.method == 'GET':
        if _current_user() is not None:
            return redirect(url_for('brain_games.player'))
        return _auth_form('login.html')

    if not _has_valid_csrf():
        return _auth_form(
            'login.html',
            'Your form expired. Refresh the page and try again.',
            400,
        )

    account = _accounts().authenticate(
        request.form.get('username', ''),
        request.form.get('password', ''),
    )
    if account is None:
        return _auth_form(
            'login.html',
            'That username and password do not match.',
            401,
        )

    session.clear()
    session[SESSION_USER_KEY] = account['username']
    session.permanent = True
    return redirect(url_for('brain_games.player'))


@routes.route('/register', methods=('GET', 'POST'))
def register():
    if request.method == 'GET':
        if _current_user() is not None:
            return redirect(url_for('brain_games.player'))
        return _auth_form('register.html')

    if not _has_valid_csrf():
        return _auth_form(
            'register.html',
            'Your form expired. Refresh the page and try again.',
            400,
        )

    account, error = _create_account_from_form()
    if error is not None:
        return error

    session.clear()
    session[SESSION_USER_KEY] = account['username']
    session.permanent = True
    return redirect(url_for('brain_games.player'))


def _create_account_from_form():
    password = request.form.get('password', '')
    if password != request.form.get('confirm_password', ''):
        return None, _auth_form(
            'register.html',
            'The password confirmation does not match.',
            400,
        )
    try:
        account = _accounts().create(
            request.form.get('username', ''),
            password,
        )
    except DuplicateAccountError:
        return None, _auth_form(
            'register.html',
            'That username is already registered.',
            409,
        )
    except AccountValidationError as error:
        return None, _auth_form('register.html', str(error), 400)
    return account, None


@routes.post('/logout')
def logout():
    if not _has_valid_csrf():
        abort(400)
    session.clear()
    return redirect(url_for('brain_games.index'))


@routes.get('/healthz')
def health():
    return jsonify({'status': 'ok'})


@routes.get('/api/games')
def games():
    return jsonify({'games': game_catalog()})


@routes.get('/api/me')
def me():
    account = _current_user()
    return jsonify({
        'authenticated': account is not None,
        'user': account,
    })


@routes.get('/api/benchmarks')
def benchmarks():
    return jsonify({'benchmarks': all_benchmarks()})


@routes.get('/api/benchmarks/<slug>')
def benchmark(slug):
    score, error = _parse_score(request.args.get('score'))
    if error is not None:
        return error
    try:
        return jsonify(benchmark_for(slug, score))
    except UnknownBenchmarkError as error:
        return _error_response('unknown_game', str(error), 404)


def _parse_score(raw_score):
    if raw_score is None:
        return None, None
    try:
        score = int(raw_score)
    except (TypeError, ValueError):
        score = -1
    if score < 0:
        return None, _error_response(
            'invalid_request',
            'score must be a non-negative integer.',
            400,
        )
    return score, None


@routes.post('/api/runs')
def create_run():
    payload, error = _request_payload(('game',))
    if error:
        return error
    player, identity_error = _run_player(payload)
    if identity_error is not None:
        return identity_error
    if not _is_text(payload['game']) or not _is_text(player):
        return _error_response(
            'invalid_request',
            'game and player must be non-empty strings.',
            400,
        )
    return jsonify(
        _public_run(_store().create(payload['game'], player)),
    ), 201


def _run_player(payload):
    account = _current_user()
    if account is not None:
        return _account_player(account), None

    player = payload.get('player')
    reserved_namespace = isinstance(player, str)
    if reserved_namespace:
        reserved_namespace = player.casefold().startswith(
            ACCOUNT_PLAYER_PREFIX,
        )
    if reserved_namespace:
        return None, _error_response(
            'reserved_player',
            'That player name is reserved for signed-in accounts.',
            403,
        )
    reserved_account = _lookup_account(player)
    if reserved_account is not None:
        return None, _error_response(
            'reserved_player',
            'Sign in to save a score under that registered username.',
            403,
        )
    return player, None


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
    return jsonify(_public_run(_store().answer(
        run_id,
        payload['round_id'],
        payload['answer'],
    )))


@routes.post('/api/runs/<run_id>/quit')
def quit_run(run_id):
    return jsonify(_public_run(_store().quit(run_id)))


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
    stored_player = _leaderboard_player(player)
    stored_entries = _store().leaders(
        game=game,
        limit=max(100, limit),
        player=stored_player,
    )
    entries = _public_leaders(stored_entries)[:limit]
    return jsonify({'entries': entries})


def _leaderboard_player(player):
    if player is None:
        return None
    account = _lookup_account(player)
    if account is None:
        return player
    return _account_player(account)


def _public_leaders(entries):
    entries = list(entries)
    usernames = set()
    account_ids = set()
    for entry in entries:
        player = str(entry.get('player', ''))
        if player.startswith(ACCOUNT_PLAYER_PREFIX):
            account_ids.add(player[len(ACCOUNT_PLAYER_PREFIX):])
        else:
            usernames.add(player)
    accounts = _lookup_accounts_many(
        usernames=usernames,
        account_ids=account_ids,
    )

    public_entries = []
    for entry in entries:
        public = _public_leader(entry, accounts)
        if public is not None:
            public_entries.append(public)
    return public_entries


def _public_leader(entry, accounts):
    public = dict(entry)
    player = str(public.get('player', ''))
    if player.startswith(ACCOUNT_PLAYER_PREFIX):
        account_id = player[len(ACCOUNT_PLAYER_PREFIX):]
        account = accounts['by_id'].get(account_id)
        if account is None:
            return None
        public['player'] = account['username']
        return public
    if player.strip().casefold() in accounts['by_username']:
        return None
    return public


def _secure_cookie_default():
    configured = os.getenv(
        'BRAIN_GAMES_SECURE_COOKIES',
        '',
    ).casefold() in {
        '1', 'true', 'yes', 'on',
    }
    return _is_vercel() or configured


def _is_vercel():
    return bool(os.getenv('VERCEL'))


def _secret_key():
    configured = os.getenv('BRAIN_GAMES_SECRET_KEY')
    if configured:
        return configured
    if _secure_cookie_default():
        raise RuntimeError(
            'BRAIN_GAMES_SECRET_KEY is required with secure cookies.',
        )
    return secrets.token_hex(32)


def _default_web_stores():
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        return build_database_stores(database_url)
    if _is_vercel():
        raise RuntimeError(
            'DATABASE_URL is required for durable Vercel storage.',
        )
    return RunStore(), AccountStore()


def create_app(test_config=None, run_store=None, account_store=None):
    """Build the BrainHacker web application."""
    application = Flask(__name__)
    application.config.from_mapping(
        JSON_SORT_KEYS=False,
        MAX_CONTENT_LENGTH=16 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        SECRET_KEY=_secret_key(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=_secure_cookie_default(),
    )
    if test_config:
        application.config.update(test_config)

    if run_store is None and account_store is None:
        store, accounts = _default_web_stores()
    else:
        store = run_store if run_store is not None else RunStore()
        accounts = (
            account_store
            if account_store is not None
            else AccountStore()
        )
    application.extensions['brain_games_run_store'] = store
    application.extensions['brain_games_account_store'] = accounts

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
