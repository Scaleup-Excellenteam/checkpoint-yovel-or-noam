"""Tests for how the server logs: rotation, settings, and what stays out."""

import gzip
import json
import logging
import sys
from http.server import BaseHTTPRequestHandler
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "server"))

import server


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Rate-limit history is shared, so leave it as it was found."""
    server.request_history.clear()
    yield
    server.request_history.clear()

@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    """Point logging at a temporary folder and give the root logger back after."""
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    directory = tmp_path / "logs"
    monkeypatch.setattr(server, "LOG_DIR", directory)
    monkeypatch.setattr(server, "LOG_PATH", directory / "app.log")
    yield directory
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    for handler in saved_handlers:
        root.addHandler(handler)
    root.setLevel(saved_level)


def read_log(directory):
    for handler in logging.getLogger().handlers:
        handler.flush()
    return (directory / "app.log").read_text(encoding="utf-8")


def test_logging_writes_to_the_terminal_and_a_rotating_file(log_dir):
    server.setup_logging()

    handlers = logging.getLogger().handlers
    assert any(isinstance(h, TimedRotatingFileHandler) for h in handlers)
    assert any(type(h) is logging.StreamHandler for h in handlers)

    rotating = next(h for h in handlers if isinstance(h, TimedRotatingFileHandler))
    assert rotating.when == "MIDNIGHT"
    assert rotating.backupCount == server.LOG_RETENTION_DAYS
    assert 7 <= server.LOG_RETENTION_DAYS <= 14

    server.logger.info("hello from the test")
    written = read_log(log_dir)
    # Timestamp, severity, and the logger name all have to be there.
    assert "INFO" in written and "tspo.chat" in written and "hello from the test" in written


def test_the_log_directory_is_created_automatically(log_dir):
    assert not log_dir.exists()

    server.setup_logging()

    assert log_dir.is_dir()


def test_level_and_directory_come_from_the_environment(monkeypatch, tmp_path):
    """The settings are read at import, so reimport the module to check them."""
    import importlib

    monkeypatch.setenv("CHAT_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("CHAT_LOG_DIR", str(tmp_path / "somewhere-else"))
    monkeypatch.setenv("CHAT_LOG_RETENTION_DAYS", "7")
    monkeypatch.setenv("CHAT_LOG_COMPRESS", "off")
    reloaded = importlib.reload(server)
    try:
        assert reloaded.LOG_LEVEL == logging.WARNING
        assert reloaded.LOG_DIR == tmp_path / "somewhere-else"
        assert reloaded.LOG_PATH == tmp_path / "somewhere-else" / "app.log"
        assert reloaded.LOG_RETENTION_DAYS == 7
        assert reloaded.LOG_COMPRESS is False
    finally:
        for name in ("CHAT_LOG_LEVEL", "CHAT_LOG_DIR", "CHAT_LOG_RETENTION_DAYS", "CHAT_LOG_COMPRESS"):
            monkeypatch.delenv(name, raising=False)
        importlib.reload(server)


def test_an_unusable_log_level_falls_back_and_says_so(monkeypatch):
    import importlib

    monkeypatch.setenv("CHAT_LOG_LEVEL", "CHATTY")
    reloaded = importlib.reload(server)
    try:
        assert reloaded.LOG_LEVEL == logging.INFO
        assert any("CHAT_LOG_LEVEL" in warning for warning in reloaded.config_warnings)
    finally:
        monkeypatch.delenv("CHAT_LOG_LEVEL", raising=False)
        importlib.reload(server)


def test_a_rotated_log_is_compressed_and_the_original_removed(tmp_path):
    source = tmp_path / "app.log.2026-09-06"
    source.write_text("yesterday\n", encoding="utf-8")

    server.compress_rotated_log(str(source), server.name_rotated_log(str(source)))

    compressed = tmp_path / "app.log.2026-09-06.gz"
    assert compressed.is_file()
    assert not source.exists()
    with gzip.open(compressed, "rt", encoding="utf-8") as opened:
        assert opened.read() == "yesterday\n"


def test_a_failed_compression_keeps_the_log_rather_than_losing_it(tmp_path):
    source = tmp_path / "app.log.2026-09-06"
    source.write_text("yesterday\n", encoding="utf-8")
    unwritable = tmp_path / "no-such-folder" / "app.log.2026-09-06.gz"

    server.compress_rotated_log(str(source), str(unwritable))

    assert (tmp_path / "app.log.2026-09-06").read_text(encoding="utf-8") == "yesterday\n"


def test_a_broken_log_directory_does_not_stop_the_server(tmp_path, monkeypatch):
    """A file where the folder should be makes mkdir fail."""
    blocked = tmp_path / "not-a-folder"
    blocked.write_text("in the way", encoding="utf-8")
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    monkeypatch.setattr(server, "LOG_DIR", blocked)
    monkeypatch.setattr(server, "LOG_PATH", blocked / "app.log")
    try:
        server.setup_logging()  # must not raise
        server.logger.info("still running")
        assert any(type(h) is logging.StreamHandler for h in root.handlers)
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_level)


def test_logging_never_raises_even_on_a_bad_format(log_dir):
    server.setup_logging()

    server.logger.info("two placeholders %s %s", "only-one-value")  # must not raise

    assert logging.raiseExceptions is False


def test_user_supplied_values_cannot_forge_extra_log_lines():
    forged = "bob\n2026-01-01 00:00:00 ERROR tspo.chat Server compromised"

    cleaned = server.log_safe(forged)

    assert "\n" in forged and "\n" not in cleaned
    assert server.log_safe("x" * 200).endswith("...")
    assert len(server.log_safe("x" * 200)) <= server.MAX_LOGGED_VALUE_LENGTH + 3


def test_passwords_and_tokens_never_reach_the_log(log_dir, tmp_path, monkeypatch):
    """Drive real signup, failed login, and successful login, then read the log."""
    monkeypatch.setattr(server, "LOG_LEVEL", logging.DEBUG)
    server.setup_logging()
    server.DB_PATH = tmp_path / "chat.db"
    server.init_database()
    server.active_tokens.clear()

    http_server = server.ChatHTTPServer(("127.0.0.1", 0), server.RestRequestHandler)
    thread = Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{http_server.server_port}"
    secret = "correct-horse-battery-staple"

    def post(path, payload):
        request = Request(f"{base}{path}", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request) as response:
            return json.loads(response.read())

    try:
        post("/signup", {"username": "logtester", "password": secret})
        with pytest.raises(HTTPError):
            post("/login", {"username": "logtester", "password": "the-wrong-password"})
        token = post("/login", {"username": "logtester", "password": secret})["token"]
    finally:
        http_server.shutdown()
        http_server.server_close()
        thread.join()

    written = read_log(log_dir)
    assert secret not in written
    assert "the-wrong-password" not in written
    assert token not in written
    # The events themselves are still recorded.
    assert "Login failed: user=logtester" in written
    assert "Login succeeded: user=logtester" in written


def test_message_text_is_not_logged_but_its_size_is(log_dir, tmp_path, monkeypatch):
    import asyncio
    from test_dlp import FakeWebSocket

    monkeypatch.setattr(server, "LOG_LEVEL", logging.DEBUG)
    server.setup_logging()
    server.DB_PATH = tmp_path / "chat.db"
    server.init_database()
    secret_text = "the-pizza-order-nobody-should-log"
    websocket = FakeWebSocket([
        json.dumps({"token": server.create_token("logger1")}),
        json.dumps({"room": "general"}),
        secret_text,
    ])

    async def no_broadcast(*args):
        return None

    monkeypatch.setattr(server, "broadcast_to_room", no_broadcast)
    asyncio.run(server.chat(websocket))

    written = read_log(log_dir)
    assert secret_text not in written
    assert f"size={len(secret_text)}" in written
    assert "room=general" in written
