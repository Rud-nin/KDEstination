"""Core contracts shared by notification providers and the runtime."""

from .events import Event, Urgency
from .provider import Provider

__all__ = ["Event", "Provider", "Urgency"]
