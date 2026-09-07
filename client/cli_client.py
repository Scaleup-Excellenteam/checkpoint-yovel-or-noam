import asyncio
import difflib
import json
import os
from getpass import getpass
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import websockets

if TYPE_CHECKING:
    from websockets.asyncio.client import ClientConnection

MAX_USERNAME_LENGTH = 16
VALID_ACTIONS = ("signup", "login")
VALID_ROOMS = ("general", "secret-pizza")


def normalize_choice(value: str, valid_choices: tuple[str, ...], label: str) -> str:
    """Accept exact input or a close typo for a known option."""
    clean_value = value.strip().lower()
    if clean_value in valid_choices:
        return clean_value

    close_matches = difflib.get_close_matches(clean_value, valid_choices, n=1, cutoff=0.7)
    if close_matches:
        fixed_value = close_matches[0]
        print(f"{label} typo detected. Using '{fixed_value}' instead of '{value}'.")
        return fixed_value

    options = ", ".join(valid_choices)
    raise ValueError(f"{label} must be one of: {options}")


def post_json(rest_uri: str, path: str, payload: dict[str, str]) -> dict[str, str]:
    """Send a JSON POST request to the REST API and return the JSON response."""
    parsed_uri = urlparse(rest_uri)
    if parsed_uri.scheme not in {"http", "https"} or not parsed_uri.netloc:
        raise ValueError("REST server address must start with http:// or https://")
    if not path.startswith("/"):
        raise ValueError("REST API path must start with /")

    request_body = json.dumps(payload).encode("utf-8")
    request = Request(
        f"{rest_uri}{path}",
        data=request_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        # The scheme and host are checked above; the address is supplied by the user.
        with urlopen(request, timeout=10) as response:  # nosec B310
            response_body = response.read().decode("utf-8")
    except HTTPError as error:
        error_body = error.read().decode("utf-8")
        raise RuntimeError(error_body) from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError("Cannot reach the chat server. Check the server address and network.") from error

    return json.loads(response_body)


def login_or_signup(rest_uri: str) -> str:
    """Ask the user to sign up or log in and return an auth token."""
    action = normalize_choice(
        input("Choose action: signup/login: "),
        VALID_ACTIONS,
        "Action",
    )

    username = input("Username: ").strip()
    if len(username) > MAX_USERNAME_LENGTH:
        raise ValueError(f"Username cannot be longer than {MAX_USERNAME_LENGTH} characters")

    password = getpass("Password: ")

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

        try:
            await websocket.send(message)
        except websockets.exceptions.ConnectionClosed:
            print("Connection closed by the server.")
            return


async def receive_messages(websocket: "ClientConnection") -> None:
    """Receive server messages and print them."""
    async for message in websocket:
        print(f"\n{message}")


async def chat() -> None:
    """Connect to the server and send and receive messages together."""
    server_uri = os.getenv("CHAT_SERVER_URI", "ws://localhost:8765")
    rest_uri = os.getenv("CHAT_REST_URI", "http://localhost:8000")
    if urlparse(server_uri).scheme not in {"ws", "wss"}:
        raise ValueError("CHAT_SERVER_URI must start with ws:// or wss://")
    if urlparse(rest_uri).scheme not in {"http", "https"}:
        raise ValueError("CHAT_REST_URI must start with http:// or https://")
    token = login_or_signup(rest_uri)

    async with websockets.connect(server_uri) as websocket:
        anti_bot_message = await websocket.recv()
        if not isinstance(anti_bot_message, str) or not anti_bot_message.startswith("Anti-Bot passed: "):
            print(anti_bot_message)
            return
        print(anti_bot_message)

        await websocket.send(json.dumps({"token": token}))
        room_name = normalize_choice(
            input("Room (general/secret-pizza): "),
            VALID_ROOMS,
            "Room",
        )
        if not room_name:
            raise ValueError("Room cannot be empty")

        await websocket.send(json.dumps({"room": room_name}))
        first_server_message = await websocket.recv()
        if not isinstance(first_server_message, str) or not first_server_message.startswith("Welcome "):
            print(first_server_message)
            return

        print(first_server_message)
        print("Write a message. Type 'exit' to leave.")

        await asyncio.gather(
            send_messages(websocket),
            receive_messages(websocket),
        )


if __name__ == "__main__":
    asyncio.run(chat())
