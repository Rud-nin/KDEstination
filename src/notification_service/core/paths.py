"""XDG paths and private directory creation."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "private-notify"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Filesystem locations owned by the service."""

    config_file: Path
    state_dir: Path
    cache_dir: Path
    profile_dir: Path


def _xdg_dir(env: Mapping[str, str], variable: str, fallback: Path) -> Path:
    value = env.get(variable, "")
    if value and Path(value).is_absolute():
        return Path(value)
    return fallback


def default_paths(env: Mapping[str, str] | None = None) -> AppPaths:
    """Resolve paths from XDG variables, falling back to the home defaults."""
    environment = os.environ if env is None else env
    home = Path(environment.get("HOME") or Path.home())

    state_dir = _xdg_dir(environment, "XDG_STATE_HOME", home / ".local" / "state")
    cache_dir = _xdg_dir(environment, "XDG_CACHE_HOME", home / ".cache")
    config_dir = _xdg_dir(environment, "XDG_CONFIG_HOME", home / ".config")

    state = state_dir / APP_NAME
    return AppPaths(
        config_file=config_dir / APP_NAME / "config.toml",
        state_dir=state,
        cache_dir=cache_dir / APP_NAME,
        profile_dir=state / "browser-profile",
    )


def ensure_private_directories(paths: AppPaths) -> None:
    """Create the service directories, tightening existing ones to 0700."""
    for directory in (paths.state_dir, paths.cache_dir, paths.profile_dir):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
