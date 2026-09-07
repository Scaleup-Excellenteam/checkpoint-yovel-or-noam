"""Tests for the message writer, session cleanup, broadcasting, and the backlog."""

import asyncio
import json
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen

import pytest
import websockets.exceptions

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "server"))

import server


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Rate-limit history is shared, so leave it as it was found."""
    server.request_history.clear()
    yield
    server.request_history.clear()

# --------------------------------------------------------------------------
# Message writer: WAL, thread safety, clean shutdown
# --------------------------------------------------------------------------

@pytest.fixture
def database(tmp_path):
    server.DB_PATH = tmp_path / "chat.db"
    server.message_writer.close()
    server.init_database()
    yield server.DB_PATH
    server.message_writer.close()


def test_the_database_runs_in_wal_mode_with_normal_syncing(database):
    connection = server.connect_database(database)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        # 1 is NORMAL: no fsync per commit, but still crash-safe.
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1
    finally:
        connection.close()


def test_save_message_returns_the_row_id_and_keeps_one_connection(database):
    first = server.save_message("noam", "general", "hello")
    second = server.save_message("noam", "general", "again")

    assert (first, second) == (1, 2)
    # The point of the change: the same connection is reused, not reopened.
    assert server.message_writer._connection is not None


def test_closing_the_writer_flushes_and_can_be_repeated(database):
    server.save_message("yovel", "general", "before the shutdown")

    server.message_writer.close()
    server.message_writer.close()  # closing twice must be harmless

    with sqlite3.connect(database) as reader:
        rows = reader.execute("SELECT username, content FROM messages").fetchall()
    assert rows == [("yovel", "before the shutdown")]
    assert server.message_writer._connection is None


def test_the_writer_follows_the_database_path_when_it_changes(tmp_path):
    server.DB_PATH = tmp_path / "first.db"
    server.message_writer.close()
    server.init_database()
    server.save_message("a", "general", "one")

    server.DB_PATH = tmp_path / "second.db"
    server.init_database()
    server.save_message("b", "general", "two")
    server.message_writer.close()

    with sqlite3.connect(tmp_path / "second.db") as reader:
        assert reader.execute("SELECT username FROM messages").fetchall() == [("b",)]


def test_many_threads_can_write_at_once(database):
    def write(index):
        return server.save_message("t", "general", f"message {index}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(write, range(120)))

    assert len(set(ids)) == 120
    with sqlite3.connect(database) as reader:
        assert reader.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 120


def test_a_database_failure_is_raised_rather_than_swallowed(database, monkeypatch):
    class Broken:
        def execute(self, *args):
            raise sqlite3.OperationalError("disk I/O error")

        def rollback(self):
            return None

    monkeypatch.setattr(server.message_writer, "_connection_for", lambda path: Broken())

    with pytest.raises(sqlite3.Error):
        server.save_message("noam", "general", "this cannot be stored")


def test_a_message_that_cannot_be_saved_is_not_broadcast(database, monkeypatch):
    """A stored message and a sent message must never disagree."""
    from test_dlp import FakeWebSocket

    broadcast_calls = []

    async def record(*args):
        broadcast_calls.append(args)

    def explode(*args):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(server, "save_message", explode)
    monkeypatch.setattr(server, "broadcast_to_room", record)
    websocket = FakeWebSocket([
        json.dumps({"token": server.create_token("noam")}),
        json.dumps({"room": "general"}),
        "a message the disk refuses",
    ])

    asyncio.run(server.chat(websocket))

    assert broadcast_calls == []
    assert "Message rejected: the server could not save it" in websocket.sent


# --------------------------------------------------------------------------
# Session cleanup
# --------------------------------------------------------------------------

def test_expired_sessions_are_swept_and_live_ones_are_kept():
    server.active_tokens.clear()
    live = server.create_token("still-here")
    server.active_tokens["stale-one"] = server.TokenSession("gone", time.monotonic() - 1)
    server.active_tokens["stale-two"] = server.TokenSession("gone", time.monotonic() - 60)

    removed = server.purge_expired_tokens()

    assert removed == 2
    assert list(server.active_tokens) == [live]
    assert server.get_token_username(live) == "still-here"


def test_the_sweep_runs_on_a_timer_and_stops_on_shutdown(monkeypatch):
    """One task handles every token, and cancelling it ends it cleanly."""
    monkeypatch.setattr(server, "TOKEN_CLEANUP_SECONDS", 0.01)
    server.active_tokens.clear()
    server.active_tokens["stale"] = server.TokenSession("gone", time.monotonic() - 1)

    async def scenario():
        task = asyncio.create_task(server.purge_expired_tokens_periodically())
        await asyncio.sleep(0.05)
        swept = "stale" not in server.active_tokens
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return swept, task.cancelled()

    swept, cancelled = asyncio.run(scenario())
    assert swept is True
    assert cancelled is True


# --------------------------------------------------------------------------
# Broadcasting
# --------------------------------------------------------------------------

class RecordingClient:
    """A room member that can be slow, or already gone."""

    def __init__(self, name, delay=0.0, failure=None):
        self.name = name
        self.delay = delay
        self.failure = failure
        self.received = []
        self.finished_at = None

    async def send(self, message):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.failure is not None:
            raise self.failure
        self.received.append(message)
        self.finished_at = time.perf_counter()


def broadcast_with(members, room="general"):
    server.rooms[room] = set(members)
    server.clients.update(members)
    started = time.perf_counter()
    asyncio.run(server.broadcast_to_room(room, "hello room"))
    elapsed = time.perf_counter() - started
    return elapsed


def test_a_slow_client_does_not_hold_up_the_others():
    slow = RecordingClient("slow", delay=0.30)
    quick_one = RecordingClient("quick-one")
    quick_two = RecordingClient("quick-two")
    try:
        elapsed = broadcast_with([slow, quick_one, quick_two])
    finally:
        server.rooms["general"] = set()
        server.clients.clear()

    # Sequential sending would have taken at least 0.30 s before the second
    # client saw anything; sending together costs one delay in total.
    assert elapsed < 0.45
    assert quick_one.received == ["hello room"] and quick_two.received == ["hello room"]
    assert quick_one.finished_at < slow.finished_at


def test_one_disconnected_client_does_not_stop_the_broadcast(caplog):
    closed = websockets.exceptions.ConnectionClosedError(None, None)
    gone = RecordingClient("gone", failure=closed)
    healthy_one = RecordingClient("healthy-one")
    healthy_two = RecordingClient("healthy-two")
    try:
        with caplog.at_level("INFO", logger="tspo.chat"):
            broadcast_with([gone, healthy_one, healthy_two])
        assert healthy_one.received == ["hello room"]
        assert healthy_two.received == ["hello room"]
        # The unreachable client is forgotten, the others are kept.
        assert gone not in server.rooms["general"]
        assert healthy_one in server.rooms["general"]
        assert "Removed disconnected client" in caplog.text
    finally:
        server.rooms["general"] = set()
        server.clients.clear()


def test_an_unexpected_send_error_is_logged_and_the_rest_still_arrive(caplog):
    broken = RecordingClient("broken", failure=RuntimeError("socket is confused"))
    healthy = RecordingClient("healthy")
    try:
        with caplog.at_level("WARNING", logger="tspo.chat"):
            broadcast_with([broken, healthy])
        assert healthy.received == ["hello room"]
        assert "Broadcast to one client failed" in caplog.text
        assert "RuntimeError" in caplog.text
    finally:
        server.rooms["general"] = set()
        server.clients.clear()


def test_broadcasting_to_an_empty_room_is_harmless():
    server.rooms["general"] = set()

    asyncio.run(server.broadcast_to_room("general", "nobody here"))
    asyncio.run(server.broadcast_to_room("no-such-room", "nor here"))


# --------------------------------------------------------------------------
# Accept queue
# --------------------------------------------------------------------------

def test_the_rest_server_has_a_deep_enough_accept_queue():
    assert server.ChatHTTPServer.request_queue_size == server.HTTP_BACKLOG
    assert server.HTTP_BACKLOG >= 128


def test_thirty_logins_at_once_all_succeed(tmp_path, monkeypatch):
    """Each login hashes for about 0.2 s, which used to overflow the queue."""
    server.DB_PATH = tmp_path / "chat.db"
    server.message_writer.close()
    server.init_database()
    server.active_tokens.clear()
    server.request_history.clear()
    # The point here is the accept queue, not the rate limit, so lift the limit.
    monkeypatch.setattr(server, "MAX_LOGIN_ATTEMPTS_PER_WINDOW", 1000)

    http_server = server.ChatHTTPServer(("127.0.0.1", 0), server.RestRequestHandler)
    thread = Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{http_server.server_port}"

    def post(path, payload):
        request = Request(f"{base}{path}", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=60) as response:
                response.read()
            return None
        except Exception as error:            # noqa: BLE001 - the failure type is the result
            return type(error).__name__

    try:
        assert post("/signup", {"username": "classmate", "password": "bootcamp2026"}) is None
        with ThreadPoolExecutor(max_workers=30) as pool:
            failures = [
                outcome
                for outcome in pool.map(
                    lambda _: post("/login", {"username": "classmate", "password": "bootcamp2026"}),
                    range(30),
                )
                if outcome is not None
            ]
    finally:
        http_server.shutdown()
        http_server.server_close()
        thread.join()

    assert failures == []
