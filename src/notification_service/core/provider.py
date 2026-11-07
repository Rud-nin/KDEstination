"""Lifecycle contract implemented by every notification provider."""

from typing import Protocol

from .events import Event


class Provider(Protocol):
    """A source of unread events polled by the runtime.

    Implementations own their resources: ``start`` prepares them, ``poll``
    returns currently unread events, and ``stop`` releases everything opened
    by ``start``. Failures are reported as exceptions; the scheduler decides
    how to retry.
    """

    async def start(self) -> None:
        """Acquire the resources needed for polling."""
        ...

    async def poll(self) -> list[Event]:
        """Return the unread events observed at poll time."""
        ...

    async def stop(self) -> None:
        """Release all resources acquired by ``start``."""
        ...
