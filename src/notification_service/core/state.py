"""Durable, atomically written deduplication state."""

import copy
import json
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

from .events import Event

STATE_VERSION = 1
RETENTION_DAYS = 30

type JSONValue = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]


class StateError(Exception):
    """The state file is unreadable or does not contain valid state."""


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise StateError(f"invalid delivered timestamp: {value!r}") from error
    if parsed.utcoffset() is None:
        raise StateError(f"delivered timestamp is not timezone-aware: {value!r}")
    return parsed


def _reject_constant(value: str) -> NoReturn:
    raise StateError(f"invalid JSON constant: {value}")


def _decode(raw: str) -> tuple[dict[str, dict[str, str]], dict[str, JSONValue]]:
    try:
        data: Any = json.loads(raw, parse_constant=_reject_constant)
    except json.JSONDecodeError as error:
        raise StateError(f"corrupt state JSON: {error}") from error

    if not isinstance(data, dict):
        raise StateError("state root must be a JSON object")
    if data.get("version") != STATE_VERSION:
        raise StateError(f"unsupported state version: {data.get('version')!r}")
    for section in ("seen", "checkpoints"):
        if section not in data:
            raise StateError(f"state is missing the {section!r} section")

    raw_seen = data["seen"]
    if not isinstance(raw_seen, dict):
        raise StateError("state 'seen' must be a JSON object")

    seen: dict[str, dict[str, str]] = {}
    for provider_id, entries in raw_seen.items():
        if not isinstance(provider_id, str) or not isinstance(entries, dict):
            raise StateError("state 'seen' must map provider IDs to objects")
        provider_seen: dict[str, str] = {}
        for key, delivered_at in entries.items():
            if not isinstance(key, str) or not isinstance(delivered_at, str):
                raise StateError("state 'seen' entries must map keys to timestamps")
            _parse_timestamp(delivered_at)
            provider_seen[key] = delivered_at
        seen[provider_id] = provider_seen

    checkpoints = data["checkpoints"]
    if not isinstance(checkpoints, dict) or not all(
        isinstance(provider_id, str) for provider_id in checkpoints
    ):
        raise StateError("state 'checkpoints' must map provider IDs to values")

    return seen, checkpoints


class StateStore:
    """Persist delivered event keys and provider checkpoints in one JSON file.

    The first successful delivery is recorded only when ``mark_delivered`` is
    called; keys older than the retention window are pruned on access.
    """

    def __init__(
        self,
        path: Path,
        *,
        retention_days: int = RETENTION_DAYS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = path
        self._retention = timedelta(days=retention_days)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._loaded = False
        self._seen: dict[str, dict[str, str]] = {}
        self._checkpoints: dict[str, JSONValue] = {}

    def has_seen(self, event: Event) -> bool:
        """Return whether this provider/key pair was already delivered."""
        self._ensure_loaded()
        delivered_at = self._seen.get(event.provider_id, {}).get(event.key)
        if delivered_at is None:
            return False
        return _parse_timestamp(delivered_at) > self._now() - self._retention

    def mark_delivered(self, event: Event) -> None:
        """Record an event as delivered and persist the change."""
        self._ensure_loaded()
        now = self._now()
        seen = {provider: dict(entries) for provider, entries in self._seen.items()}
        seen.setdefault(event.provider_id, {})[event.key] = now.isoformat()
        self._prune_seen(seen, now)
        self._write(seen, self._checkpoints)
        self._seen = seen

    def prune(self) -> None:
        """Remove delivered keys older than the retention window."""
        self._ensure_loaded()
        seen = {provider: dict(entries) for provider, entries in self._seen.items()}
        if self._prune_seen(seen, self._now()):
            self._write(seen, self._checkpoints)
            self._seen = seen

    def get_checkpoint(self, provider_id: str) -> JSONValue:
        """Return a provider's last stored checkpoint, or None."""
        self._ensure_loaded()
        if provider_id not in self._checkpoints:
            return None
        return copy.deepcopy(self._checkpoints[provider_id])

    def set_checkpoint(self, provider_id: str, checkpoint: JSONValue) -> None:
        """Replace a provider checkpoint and persist it."""
        if not provider_id.strip():
            raise ValueError("provider_id must be a non-empty string")
        self._ensure_loaded()
        now = self._now()
        seen = {provider: dict(entries) for provider, entries in self._seen.items()}
        self._prune_seen(seen, now)
        checkpoints = copy.deepcopy(self._checkpoints)
        checkpoints[provider_id] = copy.deepcopy(checkpoint)
        self._write(seen, checkpoints)
        self._seen = seen
        self._checkpoints = checkpoints

    def _now(self) -> datetime:
        now = self._clock()
        if now.utcoffset() is None:
            raise StateError("clock must return a timezone-aware datetime")
        return now.astimezone(UTC)

    def _prune_seen(self, seen: dict[str, dict[str, str]], now: datetime) -> bool:
        cutoff = now - self._retention
        removed = False
        for provider_id in list(seen):
            kept = {
                key: delivered_at
                for key, delivered_at in seen[provider_id].items()
                if _parse_timestamp(delivered_at) > cutoff
            }
            removed = removed or len(kept) != len(seen[provider_id])
            if kept:
                seen[provider_id] = kept
            else:
                del seen[provider_id]
        return removed

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._load()
            self._loaded = True

    def _load(self) -> None:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as error:
            raise StateError(f"cannot read state file {self._path}: {error}") from error

        try:
            seen, checkpoints = _decode(raw)
        except StateError as error:
            raise StateError(f"invalid state file {self._path}: {error}") from error
        self._seen = seen
        self._checkpoints = checkpoints

    def _write(
        self, seen: dict[str, dict[str, str]], checkpoints: dict[str, JSONValue]
    ) -> None:
        try:
            payload = json.dumps(
                {"version": STATE_VERSION, "seen": seen, "checkpoints": checkpoints},
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
        except (TypeError, ValueError) as error:
            raise StateError(f"cannot serialize state: {error}") from error
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self._path.name}.", suffix=".tmp", dir=self._path.parent
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.chmod(0o600)
            os.replace(temp_path, self._path)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise

        directory_fd = os.open(self._path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
