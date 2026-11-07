"""Immutable, provider-agnostic notification events."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import urlsplit


class Urgency(StrEnum):
    """Delivery-agnostic importance of an event."""

    LOW = "low"
    NORMAL = "normal"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class Event:
    """A single unread item observed by a provider.

    ``provider_id`` and ``key`` identify the event across restarts; ``key``
    must stay stable for as long as the source item exists.
    """

    provider_id: str
    key: str
    title: str
    body: str
    source_url: str
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    urgency: Urgency | None = None

    def __post_init__(self) -> None:
        for name in ("provider_id", "key"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")

        if not isinstance(self.observed_at, datetime) or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be a timezone-aware datetime")

        parts = urlsplit(self.source_url) if isinstance(self.source_url, str) else None
        if parts is None or parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("source_url must be an absolute http(s) URL")
        try:
            _ = parts.port
        except ValueError:
            raise ValueError("source_url must be an absolute http(s) URL") from None

        if self.urgency is not None and not isinstance(self.urgency, Urgency):
            raise ValueError("urgency must be an Urgency value or None")
