import asyncio
from typing import TYPE_CHECKING

import websockets

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection

# All clients currently connected to the chat.
clients: set["ServerConnection"] = set()


async def broadcast(message: str) -> None:
    """Send a message to every connected client."""
    for client in clients.copy():
        await client.send(message)


async def chat(websocket: "ServerConnection") -> None:
    """Receive messages from one client and share them with everyone."""
    clients.add(websocket)
    print("Client connected")

    try:
        # Share every message with all clients.
        async for message in websocket:
            print(message)
            await broadcast(message)
    finally:
        clients.remove(websocket)
        print("Client disconnected")


async def main() -> None:
    """Start the chat server."""
    async with websockets.serve(chat, "0.0.0.0", 8765):
        print("Chat server running on port 8765")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
