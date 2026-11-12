"""Journald-friendly logging that redacts URLs before they reach a record."""

import logging
import re
from urllib.parse import urlsplit, urlunsplit

REDACTED_URL = "<redacted-url>"
_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def redact_url(url: str) -> str:
    """Strip credentials, query, and fragment while keeping the origin and path."""
    try:
        parts = urlsplit(url)
        _ = parts.port
    except ValueError:
        return REDACTED_URL

    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return REDACTED_URL

    netloc = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _redact_text(value: str) -> str:
    return _URL_PATTERN.sub(lambda match: redact_url(match.group(0)), value)


def _redact_value(value: object) -> object:
    return _redact_text(value) if isinstance(value, str) else value


class RedactUrlFilter(logging.Filter):
    """Remove token-bearing URL parts from log messages and arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact_text(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_value(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: _redact_value(value) for key, value in record.args.items()}
        return True


class RedactingFormatter(logging.Formatter):
    """Format a record, then redact URLs including exception and stack text."""

    def __init__(self, inner: logging.Formatter | None = None) -> None:
        super().__init__()
        self._inner = inner or logging.Formatter()

    def format(self, record: logging.LogRecord) -> str:
        return _redact_text(self._inner.format(record))


def _ensure_redacting(handler: logging.Handler) -> None:
    if not any(isinstance(existing, RedactUrlFilter) for existing in handler.filters):
        handler.addFilter(RedactUrlFilter())
    if not isinstance(handler.formatter, RedactingFormatter):
        handler.setFormatter(RedactingFormatter(handler.formatter))


def configure_logging(level: int = logging.INFO) -> None:
    """Send operational logs to stderr for journald, with URL redaction.

    Handlers configured earlier keep their formatting but are wrapped so they
    also redact records, including traceback text, before emitting.
    """
    handler = logging.StreamHandler()
    formatter = RedactingFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    for existing in root.handlers:
        _ensure_redacting(existing)
