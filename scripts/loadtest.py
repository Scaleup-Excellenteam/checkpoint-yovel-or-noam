#!/usr/bin/env python3
"""Virtual bot inspector for the TSPO chat server.

Drives many simulated users through the real protocol - signing up, logging in,
joining rooms, chatting, leaving, reconnecting and misbehaving - and reports what
the server did under that load.

By default it starts a private server on unused ports with its own database and
log folder, so a run never touches the real one and always starts from the same
state. Use --target to load a server that is already running.

    python scripts/loadtest.py --scenario all
    python scripts/loadtest.py --scenario chat --users 40 --messages 20
    python scripts/loadtest.py --scenario chat --target http://localhost:8000

Every scenario prints what it did, what it measured, and whether the server
behaved correctly while it was busy.
"""

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# The server broadcasts "[room] user: text".
CHAT_LINE = re.compile(r"^\[([^\]]+)\] ([^:]+): (.*)$")
# "probe" shares no word with any DLP rule, so ordinary load is never blocked.
PROBE_WORD = "probe"


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

@dataclass
class Report:
    """What one scenario did and what it found."""

    name: str
    workload: str
    passed: bool = True
    measurements: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    failures: list = field(default_factory=list)

    def measure(self, label, value):
        self.measurements[label] = value

    def find(self, text):
        self.findings.append(text)

    def fail(self, text):
        self.passed = False
        self.failures.append(text)

    def show(self):
        mark = "PASS" if self.passed else "FAIL"
        print(f"\n{'=' * 78}\n[{mark}] {self.name}\n{'=' * 78}")
        print(f"  workload: {self.workload}")
        if self.measurements:
            print("  measured:")
            for label, value in self.measurements.items():
                print(f"    {label:<44} {value}")
        for text in self.findings:
            print(f"  finding: {text}")
        for text in self.failures:
            print(f"  FAILURE: {text}")


def percentiles(samples):
    """Return p50/p95/p99/max in milliseconds for a list of seconds."""
    if not samples:
        return None
    ordered = sorted(samples)
    at = lambda q: ordered[min(len(ordered) - 1, int(len(ordered) * q))]
    return {
        "p50_ms": round(statistics.median(ordered) * 1000, 2),
        "p95_ms": round(at(0.95) * 1000, 2),
        "p99_ms": round(at(0.99) * 1000, 2),
        "max_ms": round(max(ordered) * 1000, 2),
    }


# ---------------------------------------------------------------------------
# The server under test
# ---------------------------------------------------------------------------

class ServerUnderTest:
    """Addresses of the server being loaded, private or already running."""

    def __init__(self, rest_url, websocket_url, private=False):
        self.rest_url = rest_url.rstrip("/")
        self.websocket_url = websocket_url
        self.private = private


def require_web_address(url):
    """Refuse anything that is not a plain web address before opening it."""
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"the server address must start with http:// or https://, got {url!r}")
    return url


def post_json(rest_url, path, payload):
    """Return (status, body). A refusal is a result, not a crash."""
    require_web_address(rest_url)
    request = Request(
        f"{rest_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        # The scheme is checked above; the address is chosen by whoever runs this.
        with urlopen(request, timeout=30) as response:  # nosec B310
            return response.status, json.loads(response.read())
    except HTTPError as error:
        try:
            return error.code, json.loads(error.read())
        except (ValueError, OSError):
            return error.code, {}
    except (URLError, TimeoutError, OSError) as error:
        return 0, {"error": type(error).__name__}


def start_private_server(limits):
    """Start a server on unused ports with its own database and log folder."""
    scratch = Path(tempfile.mkdtemp(prefix="tspo-loadtest-"))
    for name, value in limits.items():
        os.environ[name] = str(value)
    os.environ["CHAT_LOG_DIR"] = str(scratch / "logs")
    os.environ.setdefault("CHAT_LOG_LEVEL", "WARNING")

    sys.path.insert(0, str(PROJECT_ROOT / "server"))
    import server  # imported here so the settings above are the ones it reads

    server.DB_PATH = scratch / "loadtest.db"
    server.init_database()
    server.active_tokens.clear()
    server.request_history.clear()
    return server, scratch


# ---------------------------------------------------------------------------
# One simulated person
# ---------------------------------------------------------------------------

class VirtualUser:
    """A single simulated member of the chat."""

    def __init__(self, name, target, inbox):
        self.name = name
        # A fixed, obviously fake credential for the simulated accounts.
        self.password = "loadtest-password"  # nosec B105
        self.target = target
        self.inbox = inbox
        self.token = None
        self.socket = None
        self.room = None
        self.reader = None
        self.errors = []

    # -- REST ---------------------------------------------------------------

    def sign_up(self):
        status, body = post_json(self.target.rest_url, "/signup",
                                 {"username": self.name, "password": self.password})
        return status, body

    def log_in(self):
        started = time.perf_counter()
        status, body = post_json(self.target.rest_url, "/login",
                                 {"username": self.name, "password": self.password})
        waited = time.perf_counter() - started
        if status == 200:
            self.token = body["token"]
        return status, waited

    # -- WebSocket ----------------------------------------------------------

    async def join(self, room, websockets):
        """Walk the real handshake: anti-bot, token, room, welcome."""
        self.socket = await websockets.connect(self.target.websocket_url, open_timeout=30)
        greeting = await self.socket.recv()
        if not greeting.startswith("Anti-Bot passed: "):
            self.errors.append(f"anti-bot refused: {greeting}")
            await self.socket.close()
            return False
        await self.socket.send(json.dumps({"token": self.token}))
        await self.socket.send(json.dumps({"room": room}))
        welcome = await self.socket.recv()
        if not welcome.startswith("Welcome "):
            self.errors.append(f"join refused: {welcome}")
            await self.socket.close()
            return False
        self.room = room
        self.reader = asyncio.create_task(self._read_forever())
        return True

    async def _read_forever(self):
        """Record everything the server sends until the socket closes."""
        try:
            async for message in self.socket:
                arrived = time.perf_counter()
                match = CHAT_LINE.match(message)
                if match:
                    self.inbox.chat(self.name, self.room, match.group(1), match.group(3), arrived)
                else:
                    self.inbox.notice(self.name, message)
        except Exception:
            # A closed socket ends the reader; the scenario decides if that matters.
            return

    async def say(self, text):
        await self.socket.send(text)

    async def leave(self):
        if self.reader is not None:
            self.reader.cancel()
            try:
                await self.reader
            except asyncio.CancelledError:
                pass
            except Exception as error:
                self.errors.append(f"reader ended badly: {type(error).__name__}")
        if self.socket is not None:
            try:
                await self.socket.close()
            except Exception as error:
                self.errors.append(f"close failed: {type(error).__name__}")
        self.socket = None
        self.room = None


class Inbox:
    """Everything the simulated users received, so delivery can be checked."""

    def __init__(self):
        self.sent_at = {}          # probe id -> time it was sent
        self.sent_room = {}        # probe id -> room it was sent to
        self.latencies = []
        self.receipts = 0
        self.leaks = []
        self.notices = []

    def chat(self, receiver, receiver_room, line_room, text, arrived):
        parts = text.split()
        if len(parts) != 2 or parts[0] != PROBE_WORD:
            return
        probe_id = parts[1]
        if probe_id not in self.sent_at:
            return
        self.receipts += 1
        self.latencies.append(arrived - self.sent_at[probe_id])
        if self.sent_room[probe_id] != receiver_room:
            self.leaks.append((probe_id, self.sent_room[probe_id], receiver, receiver_room))

    def notice(self, receiver, message):
        self.notices.append((receiver, message))


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

async def scenario_chat(target, args, websockets):
    """Many people in several rooms all talking at once."""
    rooms = args.rooms[: max(1, min(len(args.rooms), args.room_count))]
    report = Report(
        "chat: sustained conversation",
        f"{args.users} users spread over {len(rooms)} room(s) "
        f"({', '.join(rooms)}), {args.messages} messages each, sent as fast as the server accepts them",
    )
    inbox = Inbox()
    users = [VirtualUser(f"{args.prefix}{index:03d}", target, inbox) for index in range(args.users)]

    # Everyone signs up and logs in before anyone starts talking.
    for user in users:
        user.sign_up()
        status, _ = user.log_in()
        if status != 200:
            report.fail(f"{user.name} could not log in (HTTP {status})")
            return report

    membership = {}
    for index, user in enumerate(users):
        room = rooms[index % len(rooms)]
        if not await user.join(room, websockets):
            report.fail(f"{user.name} could not join {room}: {user.errors[-1]}")
            return report
        membership.setdefault(room, []).append(user)

    # Every message is a probe with a unique id, so delivery can be counted.
    probe_id = 0
    expected_receipts = 0
    started = time.perf_counter()

    async def talk(user):
        nonlocal probe_id, expected_receipts
        for _ in range(args.messages):
            probe_id += 1
            key = str(probe_id)
            inbox.sent_at[key] = time.perf_counter()
            inbox.sent_room[key] = user.room
            expected_receipts += len(membership[user.room])
            await user.say(f"{PROBE_WORD} {key}")

    await asyncio.gather(*(talk(user) for user in users))

    # Give the last broadcasts a moment to land before counting.
    deadline = time.perf_counter() + 15
    while inbox.receipts < expected_receipts and time.perf_counter() < deadline:
        await asyncio.sleep(0.05)
    elapsed = time.perf_counter() - started

    for user in users:
        await user.leave()

    sent = args.users * args.messages
    delivered = inbox.receipts
    report.measure("messages sent", sent)
    report.measure("messages delivered / expected", f"{delivered} / {expected_receipts}")
    report.measure("delivery rate", f"{100 * delivered / max(1, expected_receipts):.2f}%")
    report.measure("send throughput", f"{sent / elapsed:.0f} messages/sec")
    report.measure("delivery throughput", f"{delivered / elapsed:.0f} deliveries/sec")
    for label, value in (percentiles(inbox.latencies) or {}).items():
        report.measure(f"end-to-end latency {label}", value)
    report.measure("cross-room leaks", len(inbox.leaks))

    rejected = [text for _, text in inbox.notices if text.startswith("Message rejected")]
    if rejected:
        report.measure("messages the server refused", len(rejected))
        report.find(f"server pushed back under load: {rejected[0]}")

    if inbox.leaks:
        report.fail(f"{len(inbox.leaks)} message(s) reached the wrong room")
    if delivered < expected_receipts:
        report.fail(f"{expected_receipts - delivered} deliveries never arrived")
    return report


async def scenario_login(target, args, websockets):
    """Everyone signs in at the same moment, as a class would."""
    count = args.users
    report = Report(
        "login: everyone arrives at once",
        f"{count} logins fired simultaneously for one account; each login runs "
        f"PBKDF2, so this measures how the server copes with a burst of CPU work",
    )
    user = VirtualUser(f"{args.prefix}burst", target, Inbox())
    user.sign_up()

    started = time.perf_counter()
    results = await asyncio.gather(*(asyncio.to_thread(user.log_in) for _ in range(count)))
    elapsed = time.perf_counter() - started

    statuses = [status for status, _ in results]
    waits = [waited for _, waited in results]
    accepted = statuses.count(200)
    limited = statuses.count(429)
    broken = [s for s in statuses if s not in (200, 429)]

    report.measure("logins attempted", count)
    report.measure("accepted / rate-limited / failed", f"{accepted} / {limited} / {len(broken)}")
    report.measure("wall clock for the burst", f"{elapsed:.2f} s")
    report.measure("throughput", f"{accepted / elapsed:.1f} logins/sec")
    for label, value in (percentiles(waits) or {}).items():
        report.measure(f"login wait {label}", value)

    if broken:
        report.fail(f"{len(broken)} login(s) failed with unexpected status {sorted(set(broken))}")
    else:
        report.find(
            f"the burst was served without dropped connections; the slowest caller waited "
            f"{max(waits) * 1000:.0f} ms because password hashing is deliberately expensive"
        )
    return report


async def scenario_churn(target, args, websockets):
    """People joining, leaving, switching rooms and reconnecting, repeatedly."""
    cycles = args.cycles
    report = Report(
        "churn: connect, join, leave, reconnect",
        f"{args.users} users repeating {cycles} cycles of "
        f"join -> say something -> leave -> rejoin a different room",
    )
    inbox = Inbox()
    users = [VirtualUser(f"{args.prefix}c{index:03d}", target, inbox) for index in range(args.users)]
    for user in users:
        user.sign_up()
        status, _ = user.log_in()
        if status != 200:
            report.fail(f"{user.name} could not log in (HTTP {status})")
            return report

    rooms = args.rooms
    completed = 0
    failed = 0
    started = time.perf_counter()

    async def cycle(user):
        nonlocal completed, failed
        for round_number in range(cycles):
            room = rooms[round_number % len(rooms)]
            if not await user.join(room, websockets):
                failed += 1
                return
            probe = f"{user.name}-{round_number}"
            inbox.sent_at[probe] = time.perf_counter()
            inbox.sent_room[probe] = room
            await user.say(f"{PROBE_WORD} {probe}")
            await asyncio.sleep(0.05)
            await user.leave()
            completed += 1

    await asyncio.gather(*(cycle(user) for user in users))
    elapsed = time.perf_counter() - started

    report.measure("connect/join/leave cycles completed", f"{completed} / {args.users * cycles}")
    report.measure("cycles that failed to reconnect", failed)
    report.measure("wall clock", f"{elapsed:.2f} s")
    report.measure("reconnect rate", f"{completed / elapsed:.1f} cycles/sec")
    if failed:
        report.fail(f"{failed} user(s) could not reconnect")
    else:
        report.find("the server stayed usable while connections churned; no reconnect was refused")
    return report


async def scenario_abuse(target, args, websockets):
    """Edge cases and misbehaviour, to prove the server refuses them politely."""
    report = Report(
        "abuse: invalid input and unauthorised access",
        "one user sends empty, oversized, control-character and DLP-triggering "
        "messages; a second connection presents a token the server never issued",
    )
    inbox = Inbox()
    user = VirtualUser(f"{args.prefix}abuse", target, inbox)
    user.sign_up()
    status, _ = user.log_in()
    if status != 200:
        report.fail(f"could not log in (HTTP {status})")
        return report

    checks = []

    # A token the server never issued must not reach a room.
    socket = await websockets.connect(target.websocket_url, open_timeout=30)
    await socket.recv()
    # A token the server never issued, to prove it is refused.
    await socket.send(json.dumps({"token": "not-a-real-token"}))  # nosec B105
    reply = await socket.recv()
    checks.append(("unissued token refused", reply.startswith("Authentication failed"), reply))
    await socket.close()

    if not await user.join(args.rooms[0], websockets):
        report.fail("could not join for the abuse checks")
        return report

    async def expect(label, text, prefix):
        await user.say(text)
        await asyncio.sleep(0.35)
        replies = [message for _, message in inbox.notices if message.startswith(prefix)]
        checks.append((label, bool(replies), replies[-1] if replies else "no reply"))
        inbox.notices.clear()

    # Ask the server what its own message limit is, so this adapts to settings.
    require_web_address(target.rest_url)
    # The scheme is checked above; the address is chosen by whoever runs this.
    with urlopen(f"{target.rest_url}/health", timeout=15) as response:  # nosec B310
        max_length = json.loads(response.read()).get("max_message_length", 500)

    control_text = "bad" + chr(10) + "text"
    await expect("empty message refused", "   ", "Message rejected")
    await expect("over-length message refused", "x" * (max_length + 100), "Message rejected")
    await expect("control characters refused", control_text, "Message rejected")
    await expect("DLP blocks the secret recipe", "TSPO_SECRET_RECIPE=hidden", "Message blocked")
    await user.leave()

    # A message larger than the WebSocket frame limit never reaches the chat
    # rules at all: the protocol layer closes the connection with 1009 first.
    # That needs its own connection because it ends the one it uses.
    status, _ = user.log_in()
    frame_closed = False
    if status == 200 and await user.join(args.rooms[0], websockets):
        try:
            await user.say("x" * 100_000)
            await asyncio.sleep(0.35)
        except Exception as error:
            frame_closed = "1009" in str(error)
        if not frame_closed:
            frame_closed = user.socket is not None and user.socket.close_code == 1009
        await user.leave()
    checks.append(("frame-limit overflow closes the connection", frame_closed,
                   "expected close code 1009"))

    status, _ = user.sign_up()
    checks.append(("duplicate username refused", status == 409, f"HTTP {status}"))
    # Deliberately the wrong credential, to prove login refuses it.
    wrong_password = "not-the-password"  # nosec B105
    status, body = post_json(target.rest_url, "/login",
                             {"username": user.name, "password": wrong_password})
    checks.append(("wrong password refused", status == 401, f"HTTP {status}"))

    for label, ok, detail in checks:
        report.measure(label, "yes" if ok else f"NO - {detail}")
        if not ok:
            report.fail(f"{label}: {detail}")
    if report.passed:
        report.find("every invalid input was refused with a reason, and the server stayed up")
        report.find(
            "oversized input is handled by two different layers: over the message "
            "limit gets a readable refusal, over the 4096-byte frame limit closes "
            "the connection with code 1009 before any chat rule runs"
        )
    return report


SCENARIOS = {
    "chat": scenario_chat,
    "login": scenario_login,
    "churn": scenario_churn,
    "abuse": scenario_abuse,
}


# ---------------------------------------------------------------------------
# Running the whole thing
# ---------------------------------------------------------------------------

# Raised so the load itself is what gets measured rather than the rate limiter.
# Use --production-limits to leave the real values in place and watch them work.
BENCHMARK_LIMITS = {
    "CHAT_MAX_CONNECTIONS": 500,
    "CHAT_MAX_CONNECTIONS_PER_IP": 500,
    "CHAT_MAX_MESSAGES_PER_WINDOW": 1_000_000,
    "CHAT_MAX_LOGIN_ATTEMPTS_PER_WINDOW": 1_000_000,
    "CHAT_MAX_SIGNUPS_PER_WINDOW": 1_000_000,
}


def discover_target(rest_url):
    """Ask a running server where its chat socket is."""
    require_web_address(rest_url)
    # The scheme is checked above; the address is chosen by whoever runs this.
    with urlopen(f"{rest_url.rstrip('/')}/health", timeout=15) as response:  # nosec B310
        health = json.loads(response.read())
    scheme = "wss" if rest_url.startswith("https") else "ws"
    host = rest_url.split("://", 1)[1].rstrip("/").split("/")[0].split(":")[0]
    if health.get("websocket_path"):
        websocket_url = f"{scheme}://{host}{health['websocket_path']}"
    else:
        websocket_url = f"{scheme}://{host}:{health['websocket_port']}"
    return ServerUnderTest(rest_url, websocket_url), health


async def run_scenarios(target, args, websockets):
    reports = []
    for name in args.scenario_list:
        report = await SCENARIOS[name](target, args, websockets)
        report.show()
        reports.append(report)
    return reports


async def main_async(args):
    import websockets

    if args.target:
        target, health = discover_target(args.target)
        print(f"  loading the running server at {target.rest_url}")
        print(f"  chat socket: {target.websocket_url}")
        print(f"  rooms reported by /health: {', '.join(health.get('rooms', {}))}")
        print("  note: the real rate limits apply, so some refusals are expected")
        return await run_scenarios(target, args, websockets)

    limits = {} if args.production_limits else BENCHMARK_LIMITS
    chat_server, scratch = start_private_server(limits)
    print(f"  started a private server; database and logs in {scratch}")
    if limits:
        print("  limits raised for measurement: " + ", ".join(f"{k}={v}" for k, v in limits.items()))
    else:
        print("  production limits in force, so refusals are part of the result")

    async with websockets.serve(
        chat_server.chat,
        "127.0.0.1",
        0,
        max_size=chat_server.MAX_JSON_BODY_BYTES,
        max_queue=16,
        open_timeout=10,
        ping_interval=20,
        ping_timeout=20,
        origins=[None],
    ) as socket_server:
        chat_port = socket_server.sockets[0].getsockname()[1]
        http_server = chat_server.ChatHTTPServer(("127.0.0.1", 0), chat_server.RestRequestHandler)
        thread = Thread(target=http_server.serve_forever, daemon=True)
        thread.start()
        target = ServerUnderTest(
            f"http://127.0.0.1:{http_server.server_port}",
            f"ws://127.0.0.1:{chat_port}",
            private=True,
        )
        print(f"  REST on {target.rest_url}, chat on {target.websocket_url}")
        try:
            return await run_scenarios(target, args, websockets)
        finally:
            http_server.shutdown()
            http_server.server_close()
            thread.join()
            chat_server.message_writer.close()


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="Drive simulated users against the TSPO chat server and report what happened.",
    )
    parser.add_argument("--scenario", default="all",
                        choices=[*SCENARIOS, "all"], help="which scenario to run")
    parser.add_argument("--users", type=int, default=20, help="how many simulated people")
    parser.add_argument("--messages", type=int, default=15, help="messages each person sends")
    parser.add_argument("--cycles", type=int, default=3, help="reconnect cycles in the churn scenario")
    parser.add_argument("--room-count", type=int, default=2, help="how many rooms to spread users over")
    parser.add_argument("--prefix", default="bot", help="username prefix for the simulated people")
    parser.add_argument("--target", help="load a running server, for example http://localhost:8000")
    parser.add_argument("--production-limits", action="store_true",
                        help="keep the real rate limits instead of raising them")
    parser.add_argument("--json", help="also write the results to this file")
    args = parser.parse_args(argv)
    args.scenario_list = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    args.rooms = ["general", "secret-pizza"]
    return args


def main(argv=None):
    args = parse_arguments(argv)
    print("=" * 78)
    print("TSPO chat load test - simulated users driving the real protocol")
    print("=" * 78)
    reports = asyncio.run(main_async(args))

    print(f"\n{'=' * 78}\nSummary\n{'=' * 78}")
    for report in reports:
        print(f"  {'PASS' if report.passed else 'FAIL'}  {report.name}")
    failed = [report for report in reports if not report.passed]

    if args.json:
        Path(args.json).write_text(json.dumps([
            {
                "scenario": report.name,
                "workload": report.workload,
                "passed": report.passed,
                "measurements": report.measurements,
                "findings": report.findings,
                "failures": report.failures,
            }
            for report in reports
        ], indent=2), encoding="utf-8")
        print(f"\n  results written to {args.json}")

    print(f"\n  {len(reports) - len(failed)} of {len(reports)} scenarios passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
