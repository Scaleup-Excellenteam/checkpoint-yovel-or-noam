import asyncio
import json
import sqlite3
import sys
from pathlib import Path

import websockets

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "server"))

import server


async def connect_authenticated_client(uri: str, username: str, room: str):
    """Connect a real WebSocket client through the complete server handshake."""
    websocket = await websockets.connect(uri)
    assert (await websocket.recv()).startswith("Anti-Bot passed: IP_PRIVATE_NETWORK")
    await websocket.send(json.dumps({"token": server.create_token(username)}))
    await websocket.send(json.dumps({"room": room}))
    assert (await websocket.recv()).startswith(f"Welcome {username}!")
    return websocket


def test_websocket_rooms_dlp_and_authentication_work_together(tmp_path):
    """Exercise the real WebSocket protocol, not only mock WebSocket objects."""
    server.DB_PATH = tmp_path / "chat.db"
    server.init_database()
    server.active_tokens.clear()

    async def scenario():
        async with websockets.serve(server.chat, "127.0.0.1", 0, origins=[None]) as web_server:
            port = web_server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}"

            # A client cannot enter chat with a token the server did not issue.
            unauthenticated = await websockets.connect(uri)
            assert (await unauthenticated.recv()).startswith("Anti-Bot passed:")
            await unauthenticated.send(json.dumps({"token": "not-a-real-token"}))
            assert await unauthenticated.recv() == "Authentication failed: invalid token"
            await unauthenticated.wait_closed()

            general_one = await connect_authenticated_client(uri, "alice", "general")
            general_two = await connect_authenticated_client(uri, "bob", "general")
            secret_room = await connect_authenticated_client(uri, "carol", "secret-pizza")
            try:
                await general_one.send("hello team")
                expected_message = "[general] alice: hello team"
                assert await general_one.recv() == expected_message
                assert await general_two.recv() == expected_message
                try:
                    await asyncio.wait_for(secret_room.recv(), timeout=0.1)
                    raise AssertionError("A different room received a general-room message")
                except TimeoutError:
                    pass

                await general_one.send("pineapple")
                assert await general_one.recv() == "Message blocked: DLP_FORBIDDEN_PINEAPPLE"
                try:
                    await asyncio.wait_for(general_two.recv(), timeout=0.1)
                    raise AssertionError("A DLP-blocked message reached another client")
                except TimeoutError:
                    pass
            finally:
                await general_one.close()
                await general_two.close()
                await secret_room.close()

    asyncio.run(scenario())

    with sqlite3.connect(server.DB_PATH) as connection:
        rows = connection.execute("SELECT content FROM messages ORDER BY id").fetchall()
    assert rows == [("hello team",)]
