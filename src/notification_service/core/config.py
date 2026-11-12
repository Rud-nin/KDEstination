"""Minimal TOML configuration for the v1 runtime."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from .paths import default_paths

POLL_INTERVAL_SECONDS: Final = 30


class ConfigError(Exception):
    """Configuration is missing, unreadable, or invalid."""


@dataclass(frozen=True, slots=True)
class Config:
    """Validated settings for the service."""

    teams_activity_url: str
    poll_interval_seconds: int = field(default=POLL_INTERVAL_SECONDS, init=False)


def _validate_activity_url(url: object) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ConfigError("teams_activity.url must be a non-empty string")

    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ConfigError("teams_activity.url must be an absolute http(s) URL")
    try:
        _ = parts.port
    except ValueError:
        raise ConfigError("teams_activity.url has an invalid port") from None
    return url


def _parse(text: str) -> Config:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"invalid TOML: {error}") from error

    unknown = set(data) - {"teams_activity"}
    if unknown:
        raise ConfigError(f"unknown configuration keys: {', '.join(sorted(unknown))}")

    section = data.get("teams_activity")
    if not isinstance(section, dict):
        raise ConfigError("missing [teams_activity] section")

    unknown = set(section) - {"url"}
    if unknown:
        raise ConfigError(
            f"unknown teams_activity keys: {', '.join(sorted(unknown))}"
        )

    return Config(teams_activity_url=_validate_activity_url(section.get("url")))


def load_config(path: Path | None = None) -> Config:
    """Load the configuration file, or raise an actionable ConfigError."""
    config_file = default_paths().config_file if path is None else path

    try:
        text = config_file.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ConfigError(
            f"configuration file not found: {config_file}; "
            "copy config.toml.example to this path and set the Teams URL"
        ) from error
    except OSError as error:
        raise ConfigError(f"cannot read configuration file {config_file}: {error}") from error

    return _parse(text)
