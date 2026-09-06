import asyncio
import os
from typing import TYPE_CHECKING

import websockets

if TYPE_CHECKING:
    from websockets.asyncio.client import ClientConnection


async def send_messages(websocket: "ClientConnection", name: str) -> None:
    """Read keyboard messages and send them to the server."""
    while True:
        # Keep receiving messages while waiting for keyboard input.
        message = await asyncio.to_thread(input, "")

        if message.lower() == "exit":
            await websocket.close()
            return

        await websocket.send(f"{name}: {message}")


async def receive_messages(websocket: "ClientConnection") -> None:
    """Receive server messages and print them."""
    async for message in websocket:
        print(f"\n{message}")


async def chat() -> None:
    """Connect to the server and send and receive messages together."""
    server_uri = os.getenv("CHAT_SERVER_URI", "ws://localhost:8765")

    async with websockets.connect(server_uri) as websocket:
        name = input("Your name: ")
        print("Write a message. Type 'exit' to leave.")

        await asyncio.gather(
            send_messages(websocket, name),
            receive_messages(websocket),
        )


if __name__ == "__main__":
    asyncio.run(chat())
