import asyncio
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

import pytest

from notification_service.core.events import Event, Urgency
from notification_service.core.provider import Provider


def make_event(**overrides: Any) -> Event:
    fields: dict[str, Any] = {
        "provider_id": "teams_activity",
        "key": "activity:123",
        "title": "New mention",
        "body": "You were mentioned in a channel",
        "source_url": "https://teams.example.com/activity/123",
        "observed_at": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    }
    fields.update(overrides)
    return Event(**fields)


def test_event_preserves_fields_and_defaults() -> None:
    event = make_event()

    assert event.provider_id == "teams_activity"
    assert event.key == "activity:123"
    assert event.title == "New mention"
    assert event.body == "You were mentioned in a channel"
    assert event.source_url == "https://teams.example.com/activity/123"
    assert event.observed_at == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert event.urgency is None


def test_event_is_immutable() -> None:
    event = make_event()

    with pytest.raises(FrozenInstanceError):
        event.key = "other"  # type: ignore[misc]


def test_event_accepts_urgency() -> None:
    assert make_event(urgency=Urgency.CRITICAL).urgency is Urgency.CRITICAL


@pytest.mark.parametrize("field_name", ["provider_id", "key"])
@pytest.mark.parametrize("value", ["", "   ", 123])
def test_event_rejects_invalid_identity_fields(field_name: str, value: object) -> None:
    with pytest.raises(ValueError, match=field_name):
        make_event(**{field_name: value})


@pytest.mark.parametrize(
    "source_url",
    [
        "",
        "not a url",
        "ftp://teams.example.com/item",
        "https:///item",
        "https://:443/item",
        "https://user@:443/item",
        "https://teams.example.com:notaport/item",
        "https://teams.example.com:99999/item",
        123,
    ],
)
def test_event_rejects_malformed_source_url(source_url: object) -> None:
    with pytest.raises(ValueError, match="source_url"):
        make_event(source_url=source_url)


def test_event_rejects_naive_observed_at() -> None:
    with pytest.raises(ValueError, match="observed_at"):
        make_event(observed_at=datetime(2026, 1, 1, 12, 0))


class _OffsetlessTzInfo(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return None


def test_event_rejects_tzinfo_without_offset() -> None:
    offsetless = datetime(2026, 1, 1, 12, 0, tzinfo=_OffsetlessTzInfo())

    with pytest.raises(ValueError, match="observed_at"):
        make_event(observed_at=offsetless)


def test_event_rejects_unknown_urgency() -> None:
    with pytest.raises(ValueError, match="urgency"):
        make_event(urgency="urgent")


class FakeProvider:
    def __init__(self, events: list[Event]) -> None:
        self.events = events
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def poll(self) -> list[Event]:
        return self.events

    async def stop(self) -> None:
        self.stopped = True


def test_fake_provider_satisfies_contract() -> None:
    event = make_event()
    fake = FakeProvider([event])
    provider: Provider = fake

    async def exercise() -> list[Event]:
        await provider.start()
        events = await provider.poll()
        await provider.stop()
        return events

    assert asyncio.run(exercise()) == [event]
    assert fake.started
    assert fake.stopped
