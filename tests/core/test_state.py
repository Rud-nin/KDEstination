import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from notification_service.core import state as state_module
from notification_service.core.events import Event
from notification_service.core.state import StateError, StateStore


def make_event(
    provider_id: str = "teams_activity", key: str = "activity:1"
) -> Event:
    return Event(
        provider_id=provider_id,
        key=key,
        title="New mention",
        body="You were mentioned",
        source_url="https://teams.microsoft.com/activity/1",
    )


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def read_state(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_missing_state_file_reads_empty_and_is_not_created(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = StateStore(path)

    assert not store.has_seen(make_event())
    assert store.get_checkpoint("teams_activity") is None
    assert not path.exists()


def test_mark_delivered_persists_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    clock = FakeClock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    event = make_event()

    store = StateStore(path, clock=clock)
    store.mark_delivered(event)

    assert store.has_seen(event)
    assert StateStore(path, clock=clock).has_seen(event)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_mark_delivered_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = StateStore(path)
    event = make_event()

    store.mark_delivered(event)
    store.mark_delivered(event)

    data = read_state(path)
    seen = data["seen"]
    assert isinstance(seen, dict)
    assert list(seen["teams_activity"]) == ["activity:1"]


def test_seen_keys_are_scoped_per_provider(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")

    store.mark_delivered(make_event(provider_id="provider_a", key="same"))

    assert store.has_seen(make_event(provider_id="provider_a", key="same"))
    assert not store.has_seen(make_event(provider_id="provider_b", key="same"))


def test_checkpoints_round_trip_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    checkpoint: dict[str, state_module.JSONValue] = {"last_id": "abc", "counts": [1, 2]}
    store = StateStore(path)
    store.set_checkpoint("teams_activity", checkpoint)

    checkpoint["last_id"] = "mutated after set"

    restarted = StateStore(path)
    assert restarted.get_checkpoint("teams_activity") == {
        "last_id": "abc",
        "counts": [1, 2],
    }


def test_get_checkpoint_returns_a_copy(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    store.set_checkpoint("teams_activity", {"last_id": "abc"})

    returned = store.get_checkpoint("teams_activity")
    assert isinstance(returned, dict)
    returned["last_id"] = "changed"

    assert store.get_checkpoint("teams_activity") == {"last_id": "abc"}


def test_keys_expire_after_retention_window(tmp_path: Path) -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = StateStore(tmp_path / "state.json", clock=clock)
    event = make_event()
    store.mark_delivered(event)

    clock.advance(timedelta(days=29))
    assert store.has_seen(event)

    clock.advance(timedelta(days=1))
    assert not store.has_seen(event)


def test_prune_removes_expired_keys_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = StateStore(path, clock=clock)
    store.mark_delivered(make_event())

    clock.advance(timedelta(days=31))
    store.prune()

    data = read_state(path)
    assert data["seen"] == {}
    assert not StateStore(path, clock=clock).has_seen(make_event())


def test_prune_keeps_recent_keys(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = StateStore(path, clock=clock)
    event = make_event()
    store.mark_delivered(event)

    clock.advance(timedelta(days=10))
    store.prune()

    assert store.has_seen(event)


def test_checkpoint_write_prunes_expired_keys(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = StateStore(path, clock=clock)
    store.mark_delivered(make_event())

    clock.advance(timedelta(days=31))
    store.set_checkpoint("teams_activity", {"last_id": "abc"})

    data = read_state(path)
    assert data["seen"] == {}
    assert data["checkpoints"] == {"teams_activity": {"last_id": "abc"}}


@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        "[]",
        '{"version": 999, "seen": {}, "checkpoints": {}}',
        '{"version": 1, "seen": [], "checkpoints": {}}',
        '{"version": 1, "seen": {"p": []}, "checkpoints": {}}',
        '{"version": 1, "seen": {"p": {"k": "not-a-date"}}, "checkpoints": {}}',
        '{"version": 1, "seen": {"p": {"k": "2026-01-01T00:00:00"}}, "checkpoints": {}}',
        '{"version": 1, "seen": {}, "checkpoints": []}',
        '{"version": 1, "checkpoints": {}}',
        '{"version": 1, "seen": {}}',
        '{"version": 1, "seen": {}, "checkpoints": {"p": NaN}}',
        '{"version": 1, "seen": {}, "checkpoints": {"p": Infinity}}',
    ],
)
def test_corrupt_state_fails_safely_without_overwriting(tmp_path: Path, text: str) -> None:
    path = tmp_path / "state.json"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(StateError, match="state file"):
        StateStore(path).has_seen(make_event())

    assert path.read_text(encoding="utf-8") == text


def test_write_replaces_the_file_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.json"
    calls: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def recording_replace(src: str | Path, dst: str | Path) -> None:
        calls.append((Path(src), Path(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", recording_replace)

    StateStore(path).mark_delivered(make_event())

    assert len(calls) == 1
    source, destination = calls[0]
    assert destination == path
    assert source.parent == path.parent
    assert not source.exists()
    assert not list(tmp_path.glob(".state.json.*.tmp"))


def test_write_tightens_existing_file_permissions(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"version": 1, "seen": {}, "checkpoints": {}}', encoding="utf-8")
    path.chmod(0o644)

    StateStore(path).mark_delivered(make_event())

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_checkpoints_are_rejected_without_writing(
    tmp_path: Path, value: float
) -> None:
    path = tmp_path / "state.json"
    store = StateStore(path)
    store.mark_delivered(make_event())
    before = path.read_text(encoding="utf-8")

    with pytest.raises(StateError, match="serialize"):
        store.set_checkpoint("teams_activity", value)

    assert path.read_text(encoding="utf-8") == before


def test_missing_parent_directory_is_created_private(tmp_path: Path) -> None:
    directory = tmp_path / "runtime"
    path = directory / "state.json"

    StateStore(path).mark_delivered(make_event())

    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
