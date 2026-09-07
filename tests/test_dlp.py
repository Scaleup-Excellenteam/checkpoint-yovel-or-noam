import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "server"))

import server
from dlp import DLPScanner


def test_dlp_blocks_pineapple_in_both_languages():
    scanner = DLPScanner()

    assert scanner.scan("PINEAPPLE is forbidden").reason_code == "DLP_FORBIDDEN_PINEAPPLE"
    assert scanner.scan("אננס אסור").reason_code == "DLP_FORBIDDEN_PINEAPPLE"


def test_dlp_blocks_secrets_recipe_declarations_and_recipe_structure():
    scanner = DLPScanner()

    assert scanner.scan("TSPO_SECRET_SAUCE=hidden").reason_code == "DLP_EXPLICIT_SECRET"
    assert scanner.scan("המתכון נשאר בכספת").reason_code == "DLP_RECIPE_DECLARATION"
    assert scanner.scan("add sauce and bake").reason_code == "DLP_RECIPE_STRUCTURE"


def test_dlp_allows_normal_pizza_conversation():
    decision = DLPScanner().scan("I like mozzarella, olives, and pepperoni")

    assert decision.allowed is True
    assert decision.reason_code is None


class FakeWebSocket:
    """Minimal WebSocket double used to verify server-side DLP enforcement."""

    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []
        self.closed = []
        self.remote_address = ("127.0.0.1", 12345)

    async def recv(self):
        return self.messages.pop(0)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.messages:
            raise StopAsyncIteration
        return self.messages.pop(0)

    async def send(self, message):
        self.sent.append(message)

    async def close(self, *args):
        self.closed.append(args)


def test_blocked_message_is_not_saved_or_broadcast(monkeypatch):
    token = server.create_token("yovel")
    websocket = FakeWebSocket(
        [
            json.dumps({"token": token}),
            json.dumps({"room": "general"}),
            "TSPO_SECRET_RECIPE=do-not-share",
        ]
    )
    saved_messages = []
    broadcast_messages = []

    monkeypatch.setattr(server, "save_message", lambda *args: saved_messages.append(args))

    async def fake_broadcast(*args):
        broadcast_messages.append(args)

    monkeypatch.setattr(server, "broadcast_to_room", fake_broadcast)
    asyncio.run(server.chat(websocket))

    assert saved_messages == []
    assert broadcast_messages == []
    assert "Message blocked: DLP_EXPLICIT_SECRET" in websocket.sent


def test_third_dlp_violation_closes_connection(monkeypatch):
    token = server.create_token("yovel")
    websocket = FakeWebSocket(
        [
            json.dumps({"token": token}),
            json.dumps({"room": "general"}),
            "pineapple",
            "pineapple",
            "pineapple",
        ]
    )
    monkeypatch.setattr(server, "save_message", lambda *args: None)

    async def fake_broadcast(*args):
        return None

    monkeypatch.setattr(server, "broadcast_to_room", fake_broadcast)
    asyncio.run(server.chat(websocket))

    assert "Too many DLP violations - connection closed" in websocket.sent
    assert websocket.closed[-1] == (1008, "Too many DLP violations")
