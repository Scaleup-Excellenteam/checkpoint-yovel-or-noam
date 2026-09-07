import asyncio
import difflib
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from typing import TYPE_CHECKING, Any

import websockets
from dlp import DLPScanner
from reputation import IPReputationChecker

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection

# All clients currently connected to the chat.
clients: set["ServerConnection"] = set()
connected_sockets: set["ServerConnection"] = set()


@dataclass(frozen=True)
class TokenSession:
    username: str
    expires_at: float


active_tokens: dict[str, TokenSession] = {}
authenticated_clients: dict["ServerConnection", str] = {}
rooms: dict[str, set["ServerConnection"]] = {
    "general": set(),
    "secret-pizza": set(),
}
client_rooms: dict["ServerConnection", str] = {}
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "chat.db"
LOG_PATH = BASE_DIR / "logs" / "app.log"
MAX_USERNAME_LENGTH = 16
MAX_MESSAGE_LENGTH = 500
MAX_JSON_BODY_BYTES = 4_096
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
PASSWORD_ITERATIONS = 600_000
TOKEN_TTL_SECONDS = 60 * 60
MAX_CONNECTIONS = 100
MAX_CONNECTIONS_PER_IP = 5
MAX_MESSAGES_PER_WINDOW = 20
MESSAGE_WINDOW_SECONDS = 10
MAX_LOGIN_ATTEMPTS_PER_WINDOW = 5
LOGIN_WINDOW_SECONDS = 60
MAX_SIGNUPS_PER_WINDOW = 3
SIGNUP_WINDOW_SECONDS = 60 * 60
MAX_DLP_VIOLATIONS = 3
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,16}$")
VALID_ROOMS = tuple(rooms.keys())
request_history: dict[tuple[str, str], deque[float]] = defaultdict(deque)
message_history: dict["ServerConnection", deque[float]] = defaultdict(deque)
dlp_violations: dict["ServerConnection", int] = defaultdict(int)
rate_limit_lock = Lock()
dlp_scanner = DLPScanner()


def load_virustotal_api_key() -> None:
    """Load only the local VirusTotal key from .env without overriding PowerShell."""
    env_path = BASE_DIR / ".env"
    if not env_path.is_file() or os.getenv("VIRUSTOTAL_API_KEY"):
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "VIRUSTOTAL_API_KEY":
            api_key = value.strip().strip('"').strip("'")
            if api_key:
                os.environ["VIRUSTOTAL_API_KEY"] = api_key
            return


load_virustotal_api_key()
reputation_checker = IPReputationChecker()


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
                password_hash TEXT NOT NULL,
                password_iterations INTEGER NOT NULL
            )
            """
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        if "password_iterations" not in columns:
            # Keep existing accounts working while new accounts use the stronger cost.
            connection.execute(
                "ALTER TABLE users ADD COLUMN password_iterations INTEGER NOT NULL DEFAULT 100000"
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


def hash_password(password: str, salt: str, iterations: int = PASSWORD_ITERATIONS) -> str:
    """Hash a password with PBKDF2 and return it as hex text."""
    hashed_password = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
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
                INSERT INTO users (username, password_salt, password_hash, password_iterations)
                VALUES (?, ?, ?, ?)
                """,
                (username, salt, password_hash, PASSWORD_ITERATIONS),
            )
    except sqlite3.IntegrityError:
        return False

    return True


def validate_username(username: str) -> str | None:
    """Return an error message when the username is invalid."""
    if not username:
        return "username is required"

    if len(username) > MAX_USERNAME_LENGTH:
        return f"username cannot be longer than {MAX_USERNAME_LENGTH} characters"

    return None


def check_login(username: str, password: str) -> bool:
    """Return True only when the username exists and the password matches."""
    with sqlite3.connect(DB_PATH) as connection:
        row = connection.execute(
            """
            SELECT password_salt, password_hash, password_iterations
            FROM users
            WHERE username = ?
            """,
            (username,),
        ).fetchone()

    if row is None:
        return False

    salt, saved_password_hash, iterations = row
    supplied_password_hash = hash_password(password, salt, iterations)
    return hmac.compare_digest(supplied_password_hash, saved_password_hash)


def validate_signup(username: str, password: str) -> str | None:
    """Return a public error string when signup credentials are unsafe."""
    if not USERNAME_PATTERN.fullmatch(username):
        return "username must be 3-16 characters: letters, numbers, _ or -"
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        return f"password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters"
    return None


def allow_event(key: object, limit: int, window_seconds: int) -> bool:
    """Allow a bounded number of events in a sliding time window."""
    now = time.monotonic()
    with rate_limit_lock:
        events = request_history[key] if isinstance(key, tuple) else message_history[key]
        while events and events[0] <= now - window_seconds:
            events.popleft()
        if len(events) >= limit:
            return False
        events.append(now)
    return True


def create_token(username: str) -> str:
    """Create a short-lived bearer token for an authenticated user."""
    token = secrets.token_urlsafe(32)
    active_tokens[token] = TokenSession(username, time.monotonic() + TOKEN_TTL_SECONDS)
    return token


def get_token_username(token: str) -> str | None:
    """Return a username only for a valid, unexpired token."""
    session = active_tokens.get(token)
    if session is None:
        return None
    if session.expires_at <= time.monotonic():
        active_tokens.pop(token, None)
        return None
    return session.username


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
        if request_data is None:
            self.send_json({"error": "request body must be valid JSON and at most 4096 bytes"}, 400)
            return
        client_ip = self.client_address[0]
        if not allow_event(("signup", client_ip), MAX_SIGNUPS_PER_WINDOW, SIGNUP_WINDOW_SECONDS):
            logging.warning("Signup rate limit exceeded for IP %s", client_ip)
            self.send_json({"error": "too many signup attempts; try again later"}, 429)
            return
        username_value = request_data.get("username")
        password_value = request_data.get("password")
        if not isinstance(username_value, str) or not isinstance(password_value, str):
            self.send_json({"error": "username and password must be text"}, 400)
            return
        username = username_value.strip()
        password = password_value

        validation_error = validate_signup(username, password)
        if validation_error is not None:
            self.send_json({"error": validation_error}, 400)
            return

        if not create_user(username, password):
            self.send_json({"error": "username already exists"}, 409)
            return

        logging.info("User signed up: %s", username)
        self.send_json({"status": "created", "username": username}, 201)

    def handle_login(self) -> None:
        request_data = self.read_json_body()
        if request_data is None:
            self.send_json({"error": "request body must be valid JSON and at most 4096 bytes"}, 400)
            return
        client_ip = self.client_address[0]
        if not allow_event(("login", client_ip), MAX_LOGIN_ATTEMPTS_PER_WINDOW, LOGIN_WINDOW_SECONDS):
            logging.warning("Login rate limit exceeded for IP %s", client_ip)
            self.send_json({"error": "too many login attempts; try again later"}, 429)
            return

        username_value = request_data.get("username")
        password_value = request_data.get("password")
        if not isinstance(username_value, str) or not isinstance(password_value, str):
            self.send_json({"error": "username and password must be text"}, 400)
            return
        username = username_value.strip()
        password = password_value

        username_error = validate_username(username)
        if username_error is not None:
            self.send_json({"error": username_error}, 400)
            return

        if not password:
            self.send_json({"error": "password is required"}, 400)
            return

        if not check_login(username, password):
            self.send_json({"error": "invalid username or password"}, 401)
            return

        token = create_token(username)

        logging.info("User logged in: %s", username)
        self.send_json({"status": "ok", "username": username, "token": token})

    def read_json_body(self) -> dict[str, Any] | None:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return None
        if content_length < 1 or content_length > MAX_JSON_BODY_BYTES:
            return None
        body = self.rfile.read(content_length)

        try:
            request_data = json.loads(body)
        except json.JSONDecodeError:
            return None

        if not isinstance(request_data, dict):
            return None

        return request_data

    def send_json(self, response: dict[str, Any], status_code: int = 200) -> None:
        response_body = json.dumps(response).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
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

    if any(ord(character) < 32 or ord(character) == 127 for character in message):
        return "Message rejected: control characters are not allowed"

    return None


def normalize_room_name(room_name: str) -> str | None:
    """Return an existing room name, allowing small typing mistakes."""
    clean_room_name = room_name.strip().lower()
    if clean_room_name in rooms:
        return clean_room_name

    close_matches = difflib.get_close_matches(clean_room_name, VALID_ROOMS, n=1, cutoff=0.7)
    if close_matches:
        return close_matches[0]

    return None


async def authenticate_websocket(websocket: "ServerConnection") -> str | None:
    """Read the first client message and return the logged-in username."""
    try:
        auth_message = await websocket.recv()
        if not isinstance(auth_message, str):
            await websocket.send("Authentication failed: binary messages are not allowed")
            return None
        auth_data = json.loads(auth_message)
    except json.JSONDecodeError:
        await websocket.send("Authentication failed: invalid JSON")
        return None

    if not isinstance(auth_data, dict):
        await websocket.send("Authentication failed: invalid message")
        return None

    token = auth_data.get("token")
    if not isinstance(token, str):
        await websocket.send("Authentication failed: invalid token")
        return None
    username = get_token_username(token)

    if username is None:
        await websocket.send("Authentication failed: invalid token")
        return None

    return username


async def join_room(websocket: "ServerConnection") -> str | None:
    """Read the selected room from the client and add the client to it."""
    try:
        room_message = await websocket.recv()
        if not isinstance(room_message, str):
            await websocket.send("Join room failed: binary messages are not allowed")
            return None
        room_data = json.loads(room_message)
    except json.JSONDecodeError:
        await websocket.send("Join room failed: invalid JSON")
        return None

    if not isinstance(room_data, dict):
        await websocket.send("Join room failed: invalid message")
        return None

    room_value = room_data.get("room")
    if not isinstance(room_value, str):
        await websocket.send("Join room failed: invalid room")
        return None
    room_name = normalize_room_name(room_value)
    if room_name is None:
        available_rooms = ", ".join(rooms)
        await websocket.send(f"Join room failed: choose one of {available_rooms}")
        return None

    rooms[room_name].add(websocket)
    client_rooms[websocket] = room_name
    return room_name


async def chat(websocket: "ServerConnection") -> None:
    """Receive messages from one client and share them with everyone."""
    remote_address = websocket.remote_address
    client_ip = remote_address[0] if remote_address else "unknown"
    if len(connected_sockets) >= MAX_CONNECTIONS:
        await websocket.close(1013, "Server is busy")
        return
    if sum(
        1
        for socket in connected_sockets
        if socket.remote_address and socket.remote_address[0] == client_ip
    ) >= MAX_CONNECTIONS_PER_IP:
        await websocket.close(1008, "Too many connections from this IP")
        return

    connected_sockets.add(websocket)
    username: str | None = None
    room_name: str | None = None
    try:
        reputation_decision = await asyncio.to_thread(reputation_checker.check_ip, client_ip)
        if not reputation_decision.allowed:
            logging.warning(
                "Anti-bot blocked: ip=%s reason=%s",
                client_ip,
                reputation_decision.reason_code,
            )
            await websocket.send(f"Connection blocked: {reputation_decision.reason_code}")
            await websocket.close(1008, "Anti-Bot reputation block")
            return

        logging.info(
            "Anti-bot allowed: ip=%s reason=%s",
            client_ip,
            reputation_decision.reason_code,
        )
        await websocket.send(f"Anti-Bot passed: {reputation_decision.reason_code}")

        username = await asyncio.wait_for(authenticate_websocket(websocket), timeout=10)
        if username is None:
            await websocket.close()
            return

        room_name = await asyncio.wait_for(join_room(websocket), timeout=10)
        if room_name is None:
            await websocket.close()
            return

        clients.add(websocket)
        authenticated_clients[websocket] = username
        logging.info("Client connected: %s joined %s", username, room_name)
        await websocket.send(f"Welcome {username}! You joined room: {room_name}")

        # Share every message only with clients in the same room.
        async for message in websocket:
            if not isinstance(message, str):
                await websocket.send("Message rejected: binary messages are not allowed")
                continue
            if not allow_event(websocket, MAX_MESSAGES_PER_WINDOW, MESSAGE_WINDOW_SECONDS):
                logging.warning("Message rate limit exceeded for user %s", username)
                await websocket.send("Message rejected: sending messages too quickly")
                await websocket.close(1008, "Message rate limit exceeded")
                return
            validation_error = validate_chat_message(message)
            if validation_error is not None:
                logging.info("%s sent an invalid message: %s", username, validation_error)
                await websocket.send(validation_error)
                continue

            dlp_decision = dlp_scanner.scan(message)
            if not dlp_decision.allowed:
                dlp_violations[websocket] += 1
                logging.warning(
                    "DLP blocked: user=%s room=%s reason=%s",
                    username,
                    room_name,
                    dlp_decision.reason_code,
                )
                await websocket.send(f"Message blocked: {dlp_decision.reason_code}")
                if dlp_violations[websocket] >= MAX_DLP_VIOLATIONS:
                    await websocket.send("Too many DLP violations - connection closed")
                    await websocket.close(1008, "Too many DLP violations")
                    return
                continue

            save_message(username, room_name, message)
            chat_message = f"[{room_name}] {username}: {message}"
            logging.info("Message saved: user=%s room=%s length=%d", username, room_name, len(message))
            await broadcast_to_room(room_name, chat_message)
    finally:
        clients.discard(websocket)
        connected_sockets.discard(websocket)
        if room_name is not None:
            rooms[room_name].discard(websocket)
        client_rooms.pop(websocket, None)
        authenticated_clients.pop(websocket, None)
        message_history.pop(websocket, None)
        dlp_violations.pop(websocket, None)
        if username is not None and room_name is not None:
            logging.info("Client disconnected: %s left %s", username, room_name)


async def main() -> None:
    """Start the chat server."""
    setup_logging()
    init_database()

    rest_thread = Thread(target=start_rest_server, daemon=True)
    rest_thread.start()

    async with websockets.serve(
        chat,
        "0.0.0.0",
        8765,
        max_size=MAX_JSON_BODY_BYTES,
        max_queue=16,
        open_timeout=10,
        ping_interval=20,
        ping_timeout=20,
        origins=[None],
    ):
        logging.info("Chat server running on port 8765")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
