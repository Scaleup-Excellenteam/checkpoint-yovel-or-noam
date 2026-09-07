"""Tests for reading settings from .env and from the environment."""

import importlib
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "server"))

import server


def test_env_int_keeps_the_default_for_unusable_values(monkeypatch):
    """A typo in .env must not silently switch a limit off."""
    monkeypatch.setattr(server, "config_warnings", [])

    monkeypatch.delenv("CHAT_TEST_LIMIT", raising=False)
    assert server.env_int("CHAT_TEST_LIMIT", 20) == 20

    monkeypatch.setenv("CHAT_TEST_LIMIT", "50")
    assert server.env_int("CHAT_TEST_LIMIT", 20) == 50

    monkeypatch.setenv("CHAT_TEST_LIMIT", "not-a-number")
    assert server.env_int("CHAT_TEST_LIMIT", 20) == 20

    # Zero or negative would disable a limit entirely, so the default wins.
    monkeypatch.setenv("CHAT_TEST_LIMIT", "0")
    assert server.env_int("CHAT_TEST_LIMIT", 20) == 20

    assert len(server.config_warnings) == 2


def test_env_file_does_not_override_a_real_environment_variable(tmp_path, monkeypatch):
    """A value set by systemd or PowerShell must beat the file on disk."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# a comment\n"
        "\n"
        "CHAT_MAX_CONNECTIONS=11\n"
        'CHAT_PUBLIC_ORIGIN="https://quoted.example"\n'
        "CHAT_BIND_HOST=from-the-file\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "BASE_DIR", tmp_path)
    monkeypatch.setenv("CHAT_BIND_HOST", "from-the-environment")
    monkeypatch.delenv("CHAT_MAX_CONNECTIONS", raising=False)
    monkeypatch.delenv("CHAT_PUBLIC_ORIGIN", raising=False)

    server.load_env_file()

    assert server.os.environ["CHAT_MAX_CONNECTIONS"] == "11"
    assert server.os.environ["CHAT_PUBLIC_ORIGIN"] == "https://quoted.example"
    assert server.os.environ["CHAT_BIND_HOST"] == "from-the-environment"


def test_settings_reach_the_running_limits(monkeypatch):
    """Reimport the module to prove the constants really come from settings."""
    monkeypatch.setenv("CHAT_MAX_CONNECTIONS", "7")
    monkeypatch.setenv("CHAT_MAX_CONNECTIONS_PER_IP", "2")
    monkeypatch.setenv("CHAT_MAX_MESSAGE_LENGTH", "140")

    reloaded = importlib.reload(server)
    try:
        assert reloaded.MAX_CONNECTIONS == 7
        assert reloaded.MAX_CONNECTIONS_PER_IP == 2
        assert reloaded.MAX_MESSAGE_LENGTH == 140
    finally:
        for name in ("CHAT_MAX_CONNECTIONS", "CHAT_MAX_CONNECTIONS_PER_IP", "CHAT_MAX_MESSAGE_LENGTH"):
            monkeypatch.delenv(name, raising=False)
        importlib.reload(server)


def test_a_message_limit_above_the_frame_size_is_reported(monkeypatch):
    """Such a message would be dropped as an oversized frame with no clear reason."""
    monkeypatch.setenv("CHAT_MAX_MESSAGE_LENGTH", str(server.MAX_JSON_BODY_BYTES + 1))

    reloaded = importlib.reload(server)
    try:
        assert any("frame limit" in warning for warning in reloaded.config_warnings)
    finally:
        monkeypatch.delenv("CHAT_MAX_MESSAGE_LENGTH", raising=False)
        importlib.reload(server)


@pytest.mark.parametrize(
    "setting",
    ["CHAT_MAX_CONNECTIONS", "CHAT_MAX_MESSAGES_PER_WINDOW", "VIRUSTOTAL_API_KEY"],
)
def test_example_file_documents_every_setting(setting):
    """A setting nobody can find is a setting nobody can use."""
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert setting in example
