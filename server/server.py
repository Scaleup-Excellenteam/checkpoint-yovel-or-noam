import asyncio
import difflib
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from typing import TYPE_CHECKING, Any, Iterator
from urllib.parse import unquote, urlsplit

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
# active_tokens is read by the chat loop and written by REST threads.
token_lock = Lock()
authenticated_clients: dict["ServerConnection", str] = {}
rooms: dict[str, set["ServerConnection"]] = {
    "general": set(),
    "secret-pizza": set(),
}
client_rooms: dict["ServerConnection", str] = {}
# The caller address behind each live socket, used for the per-IP connection cap.
connection_ips: dict["ServerConnection", str] = {}
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "chat.db"
LOG_PATH = BASE_DIR / "logs" / "app.log"
# Problems found while reading settings. main() logs them once logging is set up.
config_warnings: list[str] = []


def load_env_file() -> None:
    """Read .env into the environment without replacing settings already set.

    A value exported in PowerShell, bash, or a systemd unit always wins, so the
    file is a default rather than an override.
    """
    env_path = BASE_DIR / ".env"
    if not env_path.is_file():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition("=")
        name = key.strip()
        if not separator or not name or name in os.environ:
            continue
        os.environ[name] = value.strip().strip('"').strip("'")


load_env_file()


def env_int(name: str, default: int, minimum: int = 1) -> int:
    """Read a whole-number setting, keeping the default when it is unusable."""
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default

    try:
        value = int(raw_value)
    except ValueError:
        config_warnings.append(f"{name}={raw_value!r} is not a whole number; using {default}")
        return default

    if value < minimum:
        config_warnings.append(f"{name}={value} is below the minimum {minimum}; using {default}")
        return default
    return value


# These describe how much traffic the server accepts and can be tuned in .env.
MAX_CONNECTIONS = env_int("CHAT_MAX_CONNECTIONS", 100)
MAX_CONNECTIONS_PER_IP = env_int("CHAT_MAX_CONNECTIONS_PER_IP", 5)
MAX_MESSAGES_PER_WINDOW = env_int("CHAT_MAX_MESSAGES_PER_WINDOW", 20)
MESSAGE_WINDOW_SECONDS = env_int("CHAT_MESSAGE_WINDOW_SECONDS", 10)
MAX_LOGIN_ATTEMPTS_PER_WINDOW = env_int("CHAT_MAX_LOGIN_ATTEMPTS_PER_WINDOW", 5)
LOGIN_WINDOW_SECONDS = env_int("CHAT_LOGIN_WINDOW_SECONDS", 60)
MAX_SIGNUPS_PER_WINDOW = env_int("CHAT_MAX_SIGNUPS_PER_WINDOW", 3)
SIGNUP_WINDOW_SECONDS = env_int("CHAT_SIGNUP_WINDOW_SECONDS", 60 * 60)
MAX_DLP_VIOLATIONS = env_int("CHAT_MAX_DLP_VIOLATIONS", 3)
MAX_MESSAGE_LENGTH = env_int("CHAT_MAX_MESSAGE_LENGTH", 500)
TOKEN_TTL_SECONDS = env_int("CHAT_TOKEN_TTL_SECONDS", 60 * 60)
# How often expired sessions are swept out of active_tokens.
TOKEN_CLEANUP_SECONDS = env_int("CHAT_TOKEN_CLEANUP_SECONDS", 300)
# Connections the operating system may hold while REST threads are busy.
HTTP_BACKLOG = env_int("CHAT_HTTP_BACKLOG", 128)
# How long a database call waits for another writer before giving up.
DB_BUSY_TIMEOUT_MS = env_int("CHAT_DB_BUSY_TIMEOUT_MS", 5_000)

# These are not read from .env. Lowering them would weaken how accounts are
# protected, and that should be a reviewed code change rather than a setting.
MAX_USERNAME_LENGTH = 16
MAX_JSON_BODY_BYTES = 4_096
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
PASSWORD_ITERATIONS = 600_000

if MAX_MESSAGE_LENGTH >= MAX_JSON_BODY_BYTES:
    # A longer message would be dropped as an oversized frame before any of the
    # chat rules could report a clear reason for it.
    config_warnings.append(
        f"CHAT_MAX_MESSAGE_LENGTH={MAX_MESSAGE_LENGTH} is not below the "
        f"{MAX_JSON_BODY_BYTES} byte frame limit; long messages will be dropped"
    )
# Accept only this computer by default. The server operator must explicitly
# enable a LAN binding for the two-computer demo.
CHAT_BIND_HOST = os.getenv("CHAT_BIND_HOST", "127.0.0.1")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,16}$")
VALID_ROOMS = tuple(rooms.keys())
REST_PORT = 8000
CHAT_PORT = 8765
# The React client in web/ is compiled into web/dist by `npm run build`.
WEB_DIST = BASE_DIR / "web" / "dist"
# Only these file types are served, so an unexpected file cannot be downloaded.
STATIC_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webmanifest": "application/manifest+json",
    ".woff2": "font/woff2",
}
# The Vite dev server and `npm run preview`. They only ever run on this computer.
WEB_DEV_ORIGINS = tuple(
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1")
    for port in (5173, 4173)
)
# Set when the app runs behind a TLS reverse proxy, for example
# CHAT_PUBLIC_ORIGIN="https://chat.example.com".
CHAT_PUBLIC_ORIGIN = os.getenv("CHAT_PUBLIC_ORIGIN", "").strip().rstrip("/")
# The proxy forwards this path to the chat port, so the browser only needs 443.
WEBSOCKET_PROXY_PATH = "/ws"
# Behind a proxy every connection arrives from the proxy itself, so the real
# caller has to be read from X-Forwarded-For. That header is only trusted when
# the connection really came from the local proxy; otherwise a caller could
# forge an address and walk past the rate limits and the Anti-Bot check.
TRUST_PROXY = os.getenv("CHAT_TRUST_PROXY", "0") == "1"
TRUSTED_PROXY_IPS = frozenset({"127.0.0.1", "::1"})
request_history: dict[tuple[str, str], deque[float]] = defaultdict(deque)
message_history: dict["ServerConnection", deque[float]] = defaultdict(deque)
dlp_violations: dict["ServerConnection", int] = defaultdict(int)
rate_limit_lock = Lock()
dlp_scanner = DLPScanner()


reputation_checker = IPReputationChecker()


def detect_lan_ip() -> str | None:
    """Return this computer's LAN address without sending any network traffic."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            # TEST-NET-1 is never routed; this only asks the OS which interface
            # it would use, so no packet leaves the computer.
            probe.connect(("192.0.2.1", 9))
            return probe.getsockname()[0]
        except OSError:
            return None


def real_client_ip(peer_ip: str, forwarded_for: str | None) -> str:
    """Return the address to rate-limit and reputation-check for one caller."""
    if not TRUST_PROXY or peer_ip not in TRUSTED_PROXY_IPS or not forwarded_for:
        return peer_ip
    # The proxy appends the address it actually saw, so the last entry is the
    # only one the caller cannot choose.
    return forwarded_for.rsplit(",", 1)[-1].strip() or peer_ip


def websocket_client_ip(websocket: "ServerConnection") -> str:
    """Find the caller's address for a WebSocket, proxy or no proxy."""
    remote_address = websocket.remote_address
    peer_ip = remote_address[0] if remote_address else "unknown"
    request = getattr(websocket, "request", None)
    forwarded_for = request.headers.get("X-Forwarded-For") if request is not None else None
    return real_client_ip(peer_ip, forwarded_for)


def binds_every_interface(host: str) -> bool:
    """True when the server was told to listen on every network interface."""
    try:
        return ipaddress.ip_address(host).is_unspecified
    except ValueError:
        return False


def build_web_hosts() -> list[str]:
    """List every address the browser UI is allowed to be opened from."""
    hosts = ["localhost", "127.0.0.1"]
    # A wildcard bind is the two-computer demo, so find the address to advertise.
    if binds_every_interface(CHAT_BIND_HOST):
        lan_ip = detect_lan_ip()
        if lan_ip is not None and lan_ip not in hosts:
            hosts.append(lan_ip)
    elif CHAT_BIND_HOST not in hosts:
        hosts.append(CHAT_BIND_HOST)

    for extra_host in os.getenv("CHAT_WEB_HOSTS", "").split(","):
        clean_host = extra_host.strip()
        if clean_host and clean_host not in hosts:
            hosts.append(clean_host)
    return hosts


WEB_HOSTS = build_web_hosts()
# A browser always sends an Origin header, so the WebSocket server needs the
# exact origins the UI is served from. It is never a wildcard: any other page
# that tries to open a socket for a logged-in user is still rejected.
ALLOWED_WEB_ORIGINS = [f"http://{host}:{REST_PORT}" for host in WEB_HOSTS]
ALLOWED_WEB_ORIGINS.extend(WEB_DEV_ORIGINS)
WEBSOCKET_SOURCES = [f"ws://{host}:{CHAT_PORT}" for host in WEB_HOSTS]
if CHAT_PUBLIC_ORIGIN:
    # Behind the proxy the page is https:// and the socket is wss:// on port 443.
    ALLOWED_WEB_ORIGINS.append(CHAT_PUBLIC_ORIGIN)
    WEBSOCKET_SOURCES.append("wss://" + urlsplit(CHAT_PUBLIC_ORIGIN).netloc)
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "connect-src 'self' " + " ".join(WEBSOCKET_SOURCES),
        "img-src 'self' data:",
        "style-src 'self'",
        "script-src 'self'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    )
)


def resolve_web_file(url_path: str) -> Path | None:
    """Map a URL path to one file inside web/dist, or None when it is not servable."""
    relative_path = unquote(url_path).lstrip("/")
    if not relative_path or relative_path.endswith("/"):
        relative_path = "index.html"

    web_root = WEB_DIST.resolve()
    candidate = (web_root / relative_path).resolve()
    # resolve() collapses "..", so a path outside web/dist is rejected here.
    if not candidate.is_relative_to(web_root) or not candidate.is_file():
        return None
    if candidate.suffix not in STATIC_CONTENT_TYPES:
        return None
    return candidate


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


def connect_database(path: Path) -> sqlite3.Connection:
    """Open SQLite with the settings the whole project depends on."""
    connection = sqlite3.connect(
        path,
        timeout=DB_BUSY_TIMEOUT_MS / 1000,
        check_same_thread=False,
    )
    # WAL lets readers carry on while a message is being written, and NORMAL
    # drops the fsync from every commit. A power cut can lose the last few
    # commits; a crash of this process cannot, and neither can corrupt the file.
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    return connection


@contextmanager
def database_connection() -> Iterator[sqlite3.Connection]:
    """Open a short-lived connection that is always committed and closed."""
    connection = connect_database(DB_PATH)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_database() -> None:
    """Create the database tables if they do not exist yet."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with database_connection() as connection:
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
        with database_connection() as connection:
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
    with database_connection() as connection:
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
    with token_lock:
        active_tokens[token] = TokenSession(username, time.monotonic() + TOKEN_TTL_SECONDS)
    return token


def get_token_username(token: str) -> str | None:
    """Return a username only for a valid, unexpired token."""
    with token_lock:
        session = active_tokens.get(token)
        if session is None:
            return None
        if session.expires_at <= time.monotonic():
            active_tokens.pop(token, None)
            return None
        return session.username


def purge_expired_tokens() -> int:
    """Drop every expired session and return how many were removed.

    Sessions were only ever dropped when that exact token was looked up again,
    so a user who closed the tab left an entry behind until the server stopped.
    """
    now = time.monotonic()
    with token_lock:
        expired = [token for token, session in active_tokens.items() if session.expires_at <= now]
        for token in expired:
            active_tokens.pop(token, None)
    return len(expired)


async def purge_expired_tokens_periodically() -> None:
    """Sweep expired sessions on a timer: one task in total, not one per token."""
    while True:
        await asyncio.sleep(TOKEN_CLEANUP_SECONDS)
        removed = purge_expired_tokens()
        if removed:
            logging.info("Expired sessions removed: count=%d", removed)


class MessageWriter:
    """Own the single SQLite connection the chat message stream writes through.

    Opening a connection and forcing a full fsync for every message costs about
    two milliseconds, and save_message runs on the event loop, so every client
    waited for it. One connection kept open in WAL mode turns that into a few
    microseconds. The lock keeps it safe to call from any thread.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._connection: sqlite3.Connection | None = None
        self._path: Path | None = None

    def save(self, username: str, room_name: str, content: str) -> int | None:
        """Store one message and return its row id, raising on a database error."""
        created_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            connection = self._connection_for(DB_PATH)
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO messages (username, room, content, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (username, room_name, content, created_at),
                )
                connection.commit()
            except sqlite3.Error:
                with suppress(sqlite3.Error):
                    connection.rollback()
                raise
            return cursor.lastrowid

    def close(self) -> None:
        """Commit anything outstanding and let SQLite tidy the WAL file."""
        with self._lock:
            self._close_connection()

    def _connection_for(self, path: Path) -> sqlite3.Connection:
        # Tests and tools point DB_PATH at another file, so follow it.
        if self._connection is not None and self._path != path:
            self._close_connection()
        if self._connection is None:
            self._connection = connect_database(path)
            self._path = path
        return self._connection

    def _close_connection(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.commit()
            self._connection.close()
        except sqlite3.Error:
            logging.exception("Could not close the message database cleanly")
        finally:
            self._connection = None
            self._path = None


message_writer = MessageWriter()


def save_message(username: str, room_name: str, content: str) -> int | None:
    """Save a chat message with a UTC timestamp and return its row id."""
    return message_writer.save(username, room_name, content)


class RestRequestHandler(BaseHTTPRequestHandler):
    """Handle the small REST API required by the project."""

    def do_GET(self) -> None:
        route = urlsplit(self.path).path

        if route == "/health":
            self.send_json(
                {
                    "status": "ok",
                    "service": "tspo-chat",
                    "connected_clients": len(clients),
                    "rooms": {room_name: len(members) for room_name, members in rooms.items()},
                    "websocket_port": CHAT_PORT,
                    # Behind the proxy the browser uses wss://host/ws on port 443.
                    "websocket_path": WEBSOCKET_PROXY_PATH if CHAT_PUBLIC_ORIGIN else None,
                    "max_message_length": MAX_MESSAGE_LENGTH,
                }
            )
            return

        web_file = resolve_web_file(route)
        if web_file is not None:
            self.send_web_file(web_file)
            return

        if route == "/" or route == "/index.html":
            logging.warning("Web UI is not built yet; run 'npm install && npm run build' in web/")
            self.send_error(503, "Web UI is not built")
            return

        self.send_error(404, "Not Found")

    def send_web_file(self, file_path: Path) -> None:
        """Serve one built file from web/dist with browser security headers."""
        try:
            body = file_path.read_bytes()
        except OSError:
            logging.error("Cannot read web file: %s", file_path.name)
            self.send_error(404, "Not Found")
            return

        # Vite puts a content hash in every asset name, so those never go stale.
        is_hashed_asset = file_path.parent.name == "assets"

        self.send_response(200)
        self.send_header("Content-Type", STATIC_CONTENT_TYPES[file_path.suffix])
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Cache-Control",
            "public, max-age=31536000, immutable" if is_hashed_asset else "no-store",
        )
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

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
        client_ip = self.caller_ip()
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
        client_ip = self.caller_ip()
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

    def caller_ip(self) -> str:
        """The address of the person making the request, proxy or no proxy."""
        return real_client_ip(self.client_address[0], self.headers.get("X-Forwarded-For"))

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


class ChatHTTPServer(ThreadingHTTPServer):
    """REST server with an accept queue deep enough for a class signing in.

    Every login spends about a fifth of a second hashing a password, so with
    the default queue of five, connections were reset before anything had a
    chance to accept them.
    """

    request_queue_size = HTTP_BACKLOG

    def handle_error(self, request: object, client_address: object) -> None:
        """Record a failed request instead of printing it to standard error."""
        logging.exception("Unhandled error while serving a REST request")


def start_rest_server() -> None:
    """Start the REST server in a background thread."""
    http_server = ChatHTTPServer((CHAT_BIND_HOST, REST_PORT), RestRequestHandler)
    logging.info("REST API running at http://%s:%d", CHAT_BIND_HOST, REST_PORT)
    if (WEB_DIST / "index.html").is_file():
        for host in WEB_HOSTS:
            logging.info("Web UI available at http://%s:%d", host, REST_PORT)
    else:
        logging.warning(
            "Web UI is not built. Run 'npm install' and 'npm run build' inside web/ to enable it."
        )
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
    client_ip = websocket_client_ip(websocket)
    if len(connected_sockets) >= MAX_CONNECTIONS:
        await websocket.close(1013, "Server is busy")
        return
    # Count the callers themselves. Behind a proxy every socket looks like it
    # comes from the proxy, so comparing peer addresses would cap the whole site.
    if sum(1 for ip in connection_ips.values() if ip == client_ip) >= MAX_CONNECTIONS_PER_IP:
        await websocket.close(1008, "Too many connections from this IP")
        return

    connected_sockets.add(websocket)
    connection_ips[websocket] = client_ip
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

            try:
                message_id = save_message(username, room_name, message)
            except sqlite3.Error:
                # Never broadcast a message the database did not accept.
                logging.exception("Database write failed: user=%s room=%s", username, room_name)
                await websocket.send("Message rejected: the server could not save it")
                continue

            chat_message = f"[{room_name}] {username}: {message}"
            logging.info(
                "Message saved: user=%s room=%s id=%s length=%d",
                username,
                room_name,
                message_id,
                len(message),
            )
            await broadcast_to_room(room_name, chat_message)
    finally:
        clients.discard(websocket)
        connected_sockets.discard(websocket)
        connection_ips.pop(websocket, None)
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
    for warning in config_warnings:
        logging.warning("Setting ignored: %s", warning)
    init_database()

    rest_thread = Thread(target=start_rest_server, daemon=True)
    rest_thread.start()

    cleanup_task = asyncio.create_task(purge_expired_tokens_periodically())
    try:
        async with websockets.serve(
            chat,
            CHAT_BIND_HOST,
            CHAT_PORT,
            max_size=MAX_JSON_BODY_BYTES,
            max_queue=16,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            # None keeps the CLI client working; the listed origins let the
            # browser UI connect. Any other page's origin is refused.
            origins=[None, *ALLOWED_WEB_ORIGINS],
        ):
            logging.info("Chat server running on port %d", CHAT_PORT)
            await asyncio.Future()  # run forever
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task
        message_writer.close()
        logging.info("Chat server stopped")


if __name__ == "__main__":
    asyncio.run(main())
