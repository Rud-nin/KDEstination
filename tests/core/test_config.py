import io
import logging
import stat
from pathlib import Path

import pytest

from notification_service.core.config import (
    POLL_INTERVAL_SECONDS,
    Config,
    ConfigError,
    load_config,
)
from notification_service.core.logging import (
    REDACTED_URL,
    RedactUrlFilter,
    configure_logging,
    redact_url,
)
from notification_service.core.paths import (
    AppPaths,
    default_paths,
    ensure_private_directories,
)

VALID_CONFIG = """\
[teams_activity]
url = "https://teams.microsoft.com/v2/?tenant=example"
"""


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_valid_config(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, VALID_CONFIG))

    assert config == Config(teams_activity_url="https://teams.microsoft.com/v2/?tenant=example")
    assert config.poll_interval_seconds == POLL_INTERVAL_SECONDS == 30


def test_poll_interval_is_not_configurable(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        Config(teams_activity_url="https://teams.microsoft.com", poll_interval_seconds=5)  # type: ignore[call-arg]


def test_missing_config_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="configuration file not found.*config.toml.example"):
        load_config(tmp_path / "config.toml")


def test_invalid_toml_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(write_config(tmp_path, "url ="))


def test_missing_section_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"\[teams_activity\]"):
        load_config(write_config(tmp_path, ""))


@pytest.mark.parametrize(
    "text",
    [
        "[other]\nurl = \"https://teams.microsoft.com\"\n",
        "[teams_activity]\nurl = \"https://teams.microsoft.com\"\ntimeout = 5\n",
    ],
)
def test_unknown_keys_are_rejected(tmp_path: Path, text: str) -> None:
    with pytest.raises(ConfigError, match="unknown"):
        load_config(write_config(tmp_path, text))


@pytest.mark.parametrize(
    "value",
    [
        '""',
        '"not a url"',
        '"ftp://teams.microsoft.com"',
        '"https:///item"',
        '"https://:443/item"',
        '"https://teams.microsoft.com:notaport/item"',
        "123",
    ],
)
def test_invalid_activity_urls_are_rejected(tmp_path: Path, value: str) -> None:
    with pytest.raises(ConfigError, match="teams_activity.url"):
        load_config(write_config(tmp_path, f"[teams_activity]\nurl = {value}\n"))


def test_default_paths_use_home_fallbacks(tmp_path: Path) -> None:
    home = tmp_path / "home"
    paths = default_paths({"HOME": str(home)})

    assert paths.config_file == home / ".config" / "private-notify" / "config.toml"
    assert paths.state_dir == home / ".local" / "state" / "private-notify"
    assert paths.cache_dir == home / ".cache" / "private-notify"
    assert paths.profile_dir == paths.state_dir / "browser-profile"


def test_default_paths_prefer_absolute_xdg_overrides(tmp_path: Path) -> None:
    home = tmp_path / "home"
    paths = default_paths(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        }
    )

    assert paths.config_file == tmp_path / "config" / "private-notify" / "config.toml"
    assert paths.state_dir == tmp_path / "state" / "private-notify"
    assert paths.cache_dir == tmp_path / "cache" / "private-notify"


def test_relative_xdg_overrides_are_ignored(tmp_path: Path) -> None:
    paths = default_paths({"HOME": str(tmp_path / "home"), "XDG_STATE_HOME": "relative/state"})

    assert paths.state_dir == tmp_path / "home" / ".local" / "state" / "private-notify"


def test_private_directories_are_created_with_0700(tmp_path: Path) -> None:
    paths = AppPaths(
        config_file=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
        profile_dir=tmp_path / "state" / "browser-profile",
    )

    ensure_private_directories(paths)

    for directory in (paths.state_dir, paths.cache_dir, paths.profile_dir):
        assert directory.is_dir()
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_private_directories_tighten_existing_permissions(tmp_path: Path) -> None:
    paths = AppPaths(
        config_file=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
        profile_dir=tmp_path / "state" / "browser-profile",
    )
    for directory in (paths.state_dir, paths.cache_dir):
        directory.mkdir(mode=0o755)

    ensure_private_directories(paths)

    for directory in (paths.state_dir, paths.cache_dir, paths.profile_dir):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://teams.microsoft.com/v2/?access_token=secret#fragment",
            "https://teams.microsoft.com/v2/",
        ),
        (
            "https://user:pass@teams.microsoft.com:8443/path?token=secret",
            "https://teams.microsoft.com:8443/path",
        ),
        ("https://[2001:db8::1]:8443/path?q=1", "https://[2001:db8::1]:8443/path"),
        ("not-a-url", REDACTED_URL),
        ("https://:443/path", REDACTED_URL),
    ],
)
def test_redact_url(url: str, expected: str) -> None:
    assert redact_url(url) == expected


def test_log_filter_redacts_message_and_arguments() -> None:
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "opened %s and %s",
        (
            "https://teams.microsoft.com/api?access_token=secret",
            "https://teams.microsoft.com/x?id_token=secret",
        ),
        None,
    )

    assert RedactUrlFilter().filter(record)
    message = record.getMessage()
    assert "secret" not in message
    assert "access_token" not in message
    assert "id_token" not in message
    assert "https://teams.microsoft.com/api" in message


def test_configure_logging_redacts_before_writing(capsys: pytest.CaptureFixture[str]) -> None:
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    try:
        configure_logging()
        logging.getLogger("test").warning("activity at %s", "https://teams.microsoft.com/x?token=secret")
        assert "secret" not in capsys.readouterr().err
    finally:
        root.handlers[:] = original_handlers
        root.setLevel(original_level)


def test_exception_tracebacks_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    try:
        configure_logging()
        try:
            raise RuntimeError(
                "request failed for https://teams.microsoft.com/x?access_token=secret"
            )
        except RuntimeError:
            logging.getLogger("test").exception("provider failed")

        output = capsys.readouterr().err
        assert "provider failed" in output
        assert "RuntimeError" in output
        assert "secret" not in output
        assert "access_token" not in output
    finally:
        root.handlers[:] = original_handlers
        root.setLevel(original_level)


def test_existing_handlers_are_redacted_before_emit() -> None:
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    buffer = io.StringIO()
    existing = logging.StreamHandler(buffer)
    existing.setFormatter(logging.Formatter("EXISTING %(message)s"))
    root.addHandler(existing)
    try:
        configure_logging()
        logging.getLogger("test").warning(
            "activity at https://teams.microsoft.com/x?token=secret"
        )

        output = buffer.getvalue()
        assert "EXISTING" in output
        assert "https://teams.microsoft.com/x" in output
        assert "secret" not in output
        assert "token" not in output
    finally:
        root.handlers[:] = original_handlers
        root.setLevel(original_level)
