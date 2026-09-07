import asyncio
import hashlib
import json
import logging
import secrets
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, Any

import websockets

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection

# All clients currently connected to the chat.
clients: set["ServerConnection"] = set()
active_tokens: dict[str, str] = {}
authenticated_clients: dict["ServerConnection", str] = {}
rooms: dict[str, set["ServerConnection"]] = {
    "general": set(),
    "secret-pizza": set(),
}
client_rooms: dict["ServerConnection", str] = {}
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "chat.db"
LOG_PATH = BASE_DIR / "logs" / "app.log"
MAX_MESSAGE_LENGTH = 500


def setup_logging() -> None:
    """Write logs to the terminal and to logs/app.log."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def init_database() -> None:
    """Create the database tables if they do not exist yet."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                room TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def hash_password(password: str, salt: str) -> str:
    """Hash a password with PBKDF2 and return it as hex text."""
    hashed_password = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000,
    )
    return hashed_password.hex()


def create_user(username: str, password: str) -> bool:
    """Create a user. Return False when the username already exists."""
    salt = secrets.token_hex(16)
    password_hash = hash_password(password, salt)

    try:
        with sqlite3.connect(DB_PATH) as connection:
            connection.execute(
                """
                INSERT INTO users (username, password_salt, password_hash)
                VALUES (?, ?, ?)
                """,
                (username, salt, password_hash),
            )
    except sqlite3.IntegrityError:
        return False

    return True


def check_login(username: str, password: str) -> bool:
    """Return True only when the username exists and the password matches."""
    with sqlite3.connect(DB_PATH) as connection:
        row = connection.execute(
            """
            SELECT password_salt, password_hash
            FROM users
            WHERE username = ?
            """,
            (username,),
        ).fetchone()

    if row is None:
        return False

    salt, saved_password_hash = row
    return hash_password(password, salt) == saved_password_hash


def save_message(username: str, room_name: str, content: str) -> None:
    """Save a chat message with a UTC timestamp."""
    created_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            INSERT INTO messages (username, room, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (username, room_name, content, created_at),
        )


class RestRequestHandler(BaseHTTPRequestHandler):
    """Handle the small REST API required by the project."""

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404, "Not Found")
            return

        response = {
            "status": "ok",
            "service": "tspo-chat",
            "connected_clients": len(clients),
            "rooms": {room_name: len(members) for room_name, members in rooms.items()},
        }
        response_body = json.dumps(response).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def do_POST(self) -> None:
        if self.path == "/signup":
            self.handle_signup()
            return

        if self.path == "/login":
            self.handle_login()
            return

        self.send_error(404, "Not Found")

    def handle_signup(self) -> None:
        request_data = self.read_json_body()
        username = str(request_data.get("username", "")).strip()
        password = str(request_data.get("password", "")).strip()

        if not username or not password:
            self.send_json({"error": "username and password are required"}, 400)
            return

        if not create_user(username, password):
            self.send_json({"error": "username already exists"}, 409)
            return

        logging.info("User signed up: %s", username)
        self.send_json({"status": "created", "username": username}, 201)

    def handle_login(self) -> None:
        request_data = self.read_json_body()
        username = str(request_data.get("username", "")).strip()
        password = str(request_data.get("password", "")).strip()

        if not username or not password:
            self.send_json({"error": "username and password are required"}, 400)
            return

        if not check_login(username, password):
            self.send_json({"error": "invalid username or password"}, 401)
            return

        token = secrets.token_urlsafe(32)
        active_tokens[token] = username

        logging.info("User logged in: %s", username)
        self.send_json({"status": "ok", "username": username, "token": token})

    def read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            request_data = json.loads(body)
        except json.JSONDecodeError:
            return {}

        if not isinstance(request_data, dict):
            return {}

        return request_data

    def send_json(self, response: dict[str, Any], status_code: int = 200) -> None:
        response_body = json.dumps(response).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def log_message(self, format: str, *args: object) -> None:
        logging.info("REST %s - %s", self.address_string(), format % args)


def start_rest_server() -> None:
    """Start the REST server in a background thread."""
    http_server = ThreadingHTTPServer(("0.0.0.0", 8000), RestRequestHandler)
    logging.info("REST API running at http://0.0.0.0:8000")
    http_server.serve_forever()


async def broadcast_to_room(room_name: str, message: str) -> None:
    """Send a message to every client in one room."""
    room_clients = rooms.get(room_name, set())
    for client in room_clients.copy():
        try:
            await client.send(message)
        except websockets.exceptions.ConnectionClosed:
            room_clients.discard(client)
            clients.discard(client)
            authenticated_clients.pop(client, None)
            client_rooms.pop(client, None)
            logging.info("Removed disconnected client while broadcasting")


def validate_chat_message(message: str) -> str | None:
    """Return an error message when the chat message is invalid."""
    if not message.strip():
        return "Message rejected: message cannot be empty"

    if len(message) > MAX_MESSAGE_LENGTH:
        return f"Message rejected: message cannot be longer than {MAX_MESSAGE_LENGTH} characters"

    return None


async def authenticate_websocket(websocket: "ServerConnection") -> str | None:
    """Read the first client message and return the logged-in username."""
    try:
        auth_message = await websocket.recv()
        auth_data = json.loads(auth_message)
    except json.JSONDecodeError:
        await websocket.send("Authentication failed: invalid JSON")
        return None

    if not isinstance(auth_data, dict):
        await websocket.send("Authentication failed: invalid message")
        return None

    token = str(auth_data.get("token", ""))
    username = active_tokens.get(token)

    if username is None:
        await websocket.send("Authentication failed: invalid token")
        return None

    return username


async def join_room(websocket: "ServerConnection") -> str | None:
    """Read the selected room from the client and add the client to it."""
    try:
        room_message = await websocket.recv()
        room_data = json.loads(room_message)
    except json.JSONDecodeError:
        await websocket.send("Join room failed: invalid JSON")
        return None

    if not isinstance(room_data, dict):
        await websocket.send("Join room failed: invalid message")
        return None

    room_name = str(room_data.get("room", "")).strip()
    if room_name not in rooms:
        available_rooms = ", ".join(rooms)
        await websocket.send(f"Join room failed: choose one of {available_rooms}")
        return None

    rooms[room_name].add(websocket)
    client_rooms[websocket] = room_name
    return room_name


async def chat(websocket: "ServerConnection") -> None:
    """Receive messages from one client and share them with everyone."""
    username = await authenticate_websocket(websocket)
    if username is None:
        await websocket.close()
        return

    room_name = await join_room(websocket)
    if room_name is None:
        await websocket.close()
        return

    clients.add(websocket)
    authenticated_clients[websocket] = username
    logging.info("Client connected: %s joined %s", username, room_name)
    await websocket.send(f"Welcome {username}! You joined room: {room_name}")

    try:
        # Share every message only with clients in the same room.
        async for message in websocket:
            validation_error = validate_chat_message(message)
            if validation_error is not None:
                logging.info("%s invalid message: %s", username, validation_error)
                await websocket.send(validation_error)
                continue

            save_message(username, room_name, message)
            chat_message = f"[{room_name}] {username}: {message}"
            logging.info(chat_message)
            await broadcast_to_room(room_name, chat_message)
    finally:
        clients.discard(websocket)
        rooms[room_name].discard(websocket)
        client_rooms.pop(websocket, None)
        authenticated_clients.pop(websocket, None)
        logging.info("Client disconnected: %s left %s", username, room_name)


async def main() -> None:
    """Start the chat server."""
    setup_logging()
    init_database()

    rest_thread = Thread(target=start_rest_server, daemon=True)
    rest_thread.start()

    async with websockets.serve(chat, "0.0.0.0", 8765):
        logging.info("Chat server running on port 8765")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
