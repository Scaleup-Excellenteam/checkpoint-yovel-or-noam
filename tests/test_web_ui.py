"""Tests for serving the React web client and for the browser origin allowlist."""

import asyncio
import json
import sys
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
import websockets

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "server"))

import server


@pytest.fixture
def web_server(tmp_path, monkeypatch):
    """Serve a small stand-in for web/dist so the tests do not need a Node build."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("export default 1;", encoding="utf-8")
    (dist / "secrets.txt").write_text("not a web file", encoding="utf-8")
    monkeypatch.setattr(server, "WEB_DIST", dist)

    server.DB_PATH = tmp_path / "chat.db"
    server.init_database()
    http_server = ThreadingHTTPServer(("127.0.0.1", 0), server.RestRequestHandler)
    thread = Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    yield http_server.server_port
    http_server.shutdown()
    http_server.server_close()
    thread.join()


def get(port, path):
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def test_root_serves_the_built_page_with_browser_security_headers(web_server):
    status, headers, body = get(web_server, "/")

    assert status == 200
    assert b"<div id=root>" in body
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cache-Control"] == "no-store"
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert f"ws://127.0.0.1:{server.CHAT_PORT}" in headers["Content-Security-Policy"]


def test_hashed_assets_are_cached_and_other_files_are_not(web_server):
    _, asset_headers, _ = get(web_server, "/assets/index-abc123.js")

    assert asset_headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert asset_headers["Content-Type"] == "text/javascript; charset=utf-8"


def test_health_tells_the_browser_which_websocket_port_to_use(web_server):
    status, _, body = get(web_server, "/health?cache=no")

    assert status == 200
    assert json.loads(body)["websocket_port"] == server.CHAT_PORT


def test_path_traversal_and_unlisted_file_types_are_refused(web_server):
    assert get(web_server, "/%2e%2e/%2e%2e/server/server.py")[0] == 404
    assert get(web_server, "/secrets.txt")[0] == 404
    assert get(web_server, "/does-not-exist.js")[0] == 404


def test_resolve_web_file_stays_inside_the_build_directory(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("page", encoding="utf-8")
    (tmp_path / "outside.html").write_text("secret", encoding="utf-8")
    monkeypatch.setattr(server, "WEB_DIST", dist)

    assert server.resolve_web_file("/") == dist / "index.html"
    assert server.resolve_web_file("/../outside.html") is None
    assert server.resolve_web_file("/missing.html") is None


def test_root_explains_itself_when_the_ui_was_never_built(tmp_path, monkeypatch):
    """A teammate who skips `npm run build` gets a clear answer, not a bare 404."""
    monkeypatch.setattr(server, "WEB_DIST", tmp_path / "never-built")
    http_server = ThreadingHTTPServer(("127.0.0.1", 0), server.RestRequestHandler)
    thread = Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    try:
        assert get(http_server.server_port, "/")[0] == 503
    finally:
        http_server.shutdown()
        http_server.server_close()
        thread.join()


def test_forwarded_address_is_ignored_unless_a_trusted_proxy_sent_it(monkeypatch):
    """A caller must not be able to pick its own address and skip the limits."""
    monkeypatch.setattr(server, "TRUST_PROXY", False)
    assert server.real_client_ip("203.0.113.7", "198.51.100.1") == "203.0.113.7"

    monkeypatch.setattr(server, "TRUST_PROXY", True)
    # The header only counts when the connection really came from the proxy.
    assert server.real_client_ip("203.0.113.7", "198.51.100.1") == "203.0.113.7"
    assert server.real_client_ip("127.0.0.1", "198.51.100.1") == "198.51.100.1"
    assert server.real_client_ip("127.0.0.1", None) == "127.0.0.1"
    assert server.real_client_ip("127.0.0.1", "   ") == "127.0.0.1"


def test_forged_forwarded_entries_lose_to_the_address_the_proxy_saw(monkeypatch):
    """The proxy appends what it saw, so only the last entry can be believed."""
    monkeypatch.setattr(server, "TRUST_PROXY", True)
    forged = "1.2.3.4, 203.0.113.9"

    assert server.real_client_ip("127.0.0.1", forged) == "203.0.113.9"


def test_wildcard_bind_is_recognised_for_the_two_computer_demo():
    """The LAN address is only advertised when the operator opened the server up."""
    assert server.binds_every_interface("0.0.0.0") is True
    assert server.binds_every_interface("::") is True
    assert server.binds_every_interface("127.0.0.1") is False
    assert server.binds_every_interface("localhost") is False


def test_websocket_accepts_the_web_ui_origin_and_refuses_a_foreign_one(tmp_path):
    """The browser sends an Origin header, so the CLI and the UI must both work."""
    server.DB_PATH = tmp_path / "chat.db"
    server.init_database()
    server.active_tokens.clear()
    allowed_origin = f"http://localhost:{server.REST_PORT}"
    assert allowed_origin in server.ALLOWED_WEB_ORIGINS

    async def scenario():
        async with websockets.serve(
            server.chat,
            "127.0.0.1",
            0,
            origins=[None, *server.ALLOWED_WEB_ORIGINS],
        ) as web_socket_server:
            port = web_socket_server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}"

            # A browser connection carrying an allowed Origin completes the handshake.
            browser = await websockets.connect(uri, additional_headers={"Origin": allowed_origin})
            assert (await browser.recv()).startswith("Anti-Bot passed:")
            await browser.send(json.dumps({"token": server.create_token("yovel")}))
            await browser.send(json.dumps({"room": "general"}))
            assert (await browser.recv()).startswith("Welcome yovel!")
            await browser.close()

            # The CLI client sends no Origin header at all and still connects.
            cli = await websockets.connect(uri)
            assert (await cli.recv()).startswith("Anti-Bot passed:")
            await cli.close()

            # Any other website is still rejected before the chat handler runs.
            with pytest.raises(websockets.exceptions.InvalidStatus) as rejected:
                await websockets.connect(uri, additional_headers={"Origin": "http://evil.example"})
            assert rejected.value.response.status_code == 403

    asyncio.run(scenario())
