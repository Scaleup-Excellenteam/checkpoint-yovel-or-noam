import asyncio
import json
import os
from typing import TYPE_CHECKING
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import websockets

if TYPE_CHECKING:
    from websockets.asyncio.client import ClientConnection


def post_json(rest_uri: str, path: str, payload: dict[str, str]) -> dict[str, str]:
    """Send a JSON POST request to the REST API and return the JSON response."""
    request_body = json.dumps(payload).encode("utf-8")
    request = Request(
        f"{rest_uri}{path}",
        data=request_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request) as response:
            response_body = response.read().decode("utf-8")
    except HTTPError as error:
        error_body = error.read().decode("utf-8")
        raise RuntimeError(error_body) from error

    return json.loads(response_body)


def login_or_signup(rest_uri: str) -> str:
    """Ask the user to sign up or log in and return an auth token."""
    action = input("Choose action: signup/login: ").strip().lower()
    if action not in {"signup", "login"}:
        raise ValueError("Action must be signup or login")

    username = input("Username: ").strip()
    password = input("Password: ").strip()

    if action == "signup":
        signup_response = post_json(
            rest_uri,
            "/signup",
            {"username": username, "password": password},
        )
        print(f"Signup completed for {signup_response['username']}")

    login_response = post_json(
        rest_uri,
        "/login",
        {"username": username, "password": password},
    )
    print(f"Login completed for {login_response['username']}")

    return login_response["token"]


async def send_messages(websocket: "ClientConnection") -> None:
    """Read keyboard messages and send them to the server."""
    while True:
        # Keep receiving messages while waiting for keyboard input.
        message = await asyncio.to_thread(input, "")

        if message.lower() == "exit":
            await websocket.close()
            return

        if not message.strip():
            print("Message cannot be empty")
            continue

        await websocket.send(message)


async def receive_messages(websocket: "ClientConnection") -> None:
    """Receive server messages and print them."""
    async for message in websocket:
        print(f"\n{message}")


async def chat() -> None:
    """Connect to the server and send and receive messages together."""
    server_uri = os.getenv("CHAT_SERVER_URI", "ws://localhost:8765")
    rest_uri = os.getenv("CHAT_REST_URI", "http://localhost:8000")
    token = login_or_signup(rest_uri)

    async with websockets.connect(server_uri) as websocket:
        await websocket.send(json.dumps({"token": token}))
        room_name = input("Room (general/secret-pizza): ").strip()
        if not room_name:
            raise ValueError("Room cannot be empty")

        await websocket.send(json.dumps({"room": room_name}))
        print("Write a message. Type 'exit' to leave.")

        await asyncio.gather(
            send_messages(websocket),
            receive_messages(websocket),
        )


if __name__ == "__main__":
    asyncio.run(chat())
