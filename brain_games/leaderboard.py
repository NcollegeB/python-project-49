"""Persistent leaderboard storage for the terminal games."""

import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Union

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None


DATA_DIR_ENV = 'BRAIN_GAMES_DATA_DIR'
LEADERBOARD_FILENAME = 'leaderboard.json'
SCHEMA_VERSION = 1


def get_default_path() -> Path:
    """Return the leaderboard path, honoring the data-directory override."""
    configured_directory = os.getenv(DATA_DIR_ENV)
    if configured_directory:
        data_directory = Path(configured_directory).expanduser()
    else:
        data_directory = Path.home() / '.brain_games'
    return data_directory / LEADERBOARD_FILENAME


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _score_lock(path: Path):
    """Serialise score updates where advisory file locking is available."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + '.lock')
    with lock_path.open('a', encoding='utf-8') as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _entry_key(entry: Dict[str, object]):
    return (
        str(entry['player']).casefold(),
        str(entry['game']).casefold(),
    )


def _normalise_entry(value: object) -> Optional[Dict[str, object]]:
    if not isinstance(value, dict):
        return None

    player = value.get('player')
    game = value.get('game')
    score = value.get('score')
    played_at = value.get('played_at')
    if not isinstance(player, str) or not player.strip():
        return None
    if not isinstance(game, str) or not game.strip():
        return None
    if isinstance(score, bool) or not isinstance(score, int) or score < 0:
        return None
    if not isinstance(played_at, str) or not played_at:
        return None

    return {
        'player': player.strip(),
        'game': game.strip(),
        'score': score,
        'played_at': played_at,
    }


def _preferred_entry(
        current: Dict[str, object],
        candidate: Dict[str, object],
) -> Dict[str, object]:
    current_score = int(current['score'])
    candidate_score = int(candidate['score'])
    if candidate_score > current_score:
        return candidate
    if candidate_score < current_score:
        return current

    current_tie_breaker = (
        str(current['played_at']),
        str(current['player']),
        str(current['game']),
    )
    candidate_tie_breaker = (
        str(candidate['played_at']),
        str(candidate['player']),
        str(candidate['game']),
    )
    if candidate_tie_breaker < current_tie_breaker:
        return candidate
    return current


def _best_entries(raw_entries):
    keyed_entries = {}
    for raw_entry in raw_entries:
        entry = _normalise_entry(raw_entry)
        if entry is None:
            continue
        key = _entry_key(entry)
        current = keyed_entries.get(key)
        if current is None:
            keyed_entries[key] = entry
        else:
            keyed_entries[key] = _preferred_entry(current, entry)
    return list(keyed_entries.values())


def _filter_entries(entries, field, value):
    if value is None:
        return entries
    if not isinstance(value, str):
        raise TypeError('{} must be a string or None'.format(field))
    key = value.strip().casefold()
    return [
        entry for entry in entries
        if str(entry[field]).casefold() == key
    ]


class Leaderboard:
    """Store each player's best score for every game in a JSON file."""

    def __init__(self, path: Optional[Union[str, os.PathLike]] = None):
        self.path = Path(path).expanduser() if path else get_default_path()

    def record(self, player: str, game: str, score: int) -> Dict[str, object]:
        """Record a score and return the retained best entry."""
        entry = self._new_entry(player, game, score)
        with _score_lock(self.path):
            entries = self._load_entries()
            keyed_entries = {_entry_key(item): item for item in entries}
            key = _entry_key(entry)
            current = keyed_entries.get(key)

            if current is None:
                keyed_entries[key] = entry
            else:
                keyed_entries[key] = _preferred_entry(current, entry)

            retained_entry = keyed_entries[key]
            if current is None or retained_entry is not current:
                self._write_entries(list(keyed_entries.values()))
        return dict(retained_entry)

    def top(
            self,
            limit: int = 10,
            game: Optional[str] = None,
            player: Optional[str] = None,
    ) -> List[Dict[str, object]]:
        """Return high scores, optionally restricted by game or player."""
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError('limit must be an integer')
        if limit <= 0:
            return []

        entries = self._load_entries()
        entries = _filter_entries(entries, 'game', game)
        entries = _filter_entries(entries, 'player', player)

        entries.sort(key=self._sort_key)
        return [dict(entry) for entry in entries[:limit]]

    @staticmethod
    def _new_entry(player: str, game: str, score: int) -> Dict[str, object]:
        if not isinstance(player, str) or not player.strip():
            raise ValueError('player must be a non-empty string')
        if not isinstance(game, str) or not game.strip():
            raise ValueError('game must be a non-empty string')
        if isinstance(score, bool) or not isinstance(score, int) or score < 0:
            raise ValueError('score must be a non-negative integer')
        return {
            'player': player.strip(),
            'game': game.strip(),
            'score': score,
            'played_at': _utc_timestamp(),
        }

    @staticmethod
    def _sort_key(entry: Dict[str, object]):
        return (
            -int(entry['score']),
            str(entry['player']).casefold(),
            str(entry['game']).casefold(),
            str(entry['player']),
            str(entry['game']),
            str(entry['played_at']),
        )

    def _load_entries(self) -> List[Dict[str, object]]:
        try:
            with self.path.open(encoding='utf-8') as leaderboard_file:
                payload = json.load(leaderboard_file)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return []

        if not isinstance(payload, dict):
            return []
        raw_entries = payload.get('entries')
        if not isinstance(raw_entries, list):
            return []

        return _best_entries(raw_entries)

    def _write_entries(self, entries: List[Dict[str, object]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=f'.{self.path.name}.',
            suffix='.tmp',
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, 'w', encoding='utf-8') as output:
                json.dump(
                    {
                        'version': SCHEMA_VERSION,
                        'entries': sorted(entries, key=self._sort_key),
                    },
                    output,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                output.write('\n')
                output.flush()
                os.fsync(output.fileno())
            os.replace(str(temporary_path), str(self.path))
        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
