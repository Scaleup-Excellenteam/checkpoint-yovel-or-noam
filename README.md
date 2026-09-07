# TSPO Chat

Simple Python WebSocket chat project for the Tel-Hai Bootcamp checkpoint.

## What Works For Day 1

- One server can accept multiple clients.
- Clients can connect from another laptop on the same network.
- WebSocket chat runs on port `8765`.
- REST API runs on port `8000`.
- `GET /health` shows that the server is alive.
- Users can sign up and log in.
- There are two clients: a browser UI (React) and the original terminal client.
- Passwords are stored with a salt and hash in SQLite.
- A client must log in before joining chat.
- Clients join one of two rooms: `general` or `secret-pizza`.
- Messages are sent only to clients in the same room.
- Empty or very long messages are rejected.
- Important events are written to the terminal and to `logs/app.log`.
- Messages are saved in SQLite with username, room, content, and time.

## Quick Start (Linux and macOS)

One script prepares everything and starts the server:

```bash
./scripts/start.sh
```

It creates the Python virtual environment, installs the packages, copies
`.env.example` to `.env` if there is no `.env` yet, builds the browser UI, and
runs the server. Running it again skips whatever is already up to date.

```bash
./scripts/start.sh --dev          # also run the Vite dev server for UI work
./scripts/start.sh --skip-build   # use the existing web/dist
./scripts/start.sh --help
```

Then open http://localhost:8000.

On Windows, follow the manual steps below, or run the script from Git Bash.

## Settings

Limits live in `.env`, not in the code. Start from the template:

```powershell
copy .env.example .env
```

`.env` is ignored by Git, so a key or a local change never reaches GitHub. A
value exported in PowerShell, bash, or a systemd unit beats the file, so the
file holds defaults. Restart the server after editing.

| Setting | Default | Meaning |
| --- | --- | --- |
| `CHAT_MAX_CONNECTIONS` | 100 | Chat connections at the same time |
| `CHAT_MAX_CONNECTIONS_PER_IP` | 5 | Connections from one address; two tabs count as two |
| `CHAT_MAX_MESSAGES_PER_WINDOW` | 20 | Messages one client may send per window |
| `CHAT_MESSAGE_WINDOW_SECONDS` | 10 | Length of that window |
| `CHAT_MAX_LOGIN_ATTEMPTS_PER_WINDOW` | 5 | Login attempts from one address |
| `CHAT_LOGIN_WINDOW_SECONDS` | 60 | Length of the login window |
| `CHAT_MAX_SIGNUPS_PER_WINDOW` | 3 | New accounts from one address |
| `CHAT_SIGNUP_WINDOW_SECONDS` | 3600 | Length of the signup window |
| `CHAT_MAX_MESSAGE_LENGTH` | 500 | Longest chat message; must stay below 4096 |
| `CHAT_MAX_DLP_VIOLATIONS` | 3 | Blocked messages before the connection closes |
| `CHAT_TOKEN_TTL_SECONDS` | 3600 | How long a login stays valid |
| `CHAT_BIND_HOST` | 127.0.0.1 | Which addresses the server accepts |
| `CHAT_WEB_HOSTS` | empty | Extra addresses the UI may be opened from |
| `CHAT_PUBLIC_ORIGIN` | empty | Public address when behind a TLS proxy |
| `CHAT_TRUST_PROXY` | 0 | Read the caller address from the proxy |
| `VIRUSTOTAL_API_KEY` | empty | Enables the Anti-Bot reputation check |
| `CHAT_HTTP_BACKLOG` | 128 | Connections queued while REST threads are busy |
| `CHAT_TOKEN_CLEANUP_SECONDS` | 300 | How often expired sessions are swept |
| `CHAT_DB_BUSY_TIMEOUT_MS` | 5000 | How long a database call waits for another writer |
| `CHAT_LOG_LEVEL` | INFO | DEBUG, INFO, WARNING, ERROR, or CRITICAL |
| `CHAT_LOG_DIR` | `logs/` | Where `app.log` is written; created if missing |
| `CHAT_LOG_RETENTION_DAYS` | 14 | Days of rotated logs to keep |
| `CHAT_LOG_COMPRESS` | 1 | Gzip each rotated day |

A value that is not a whole number, or is below the smallest sensible number, is
ignored: the default is used and the reason is written to the log at startup.

### Logs

Logs go to the terminal and to `logs/app.log`. The file rotates at midnight UTC
and old days are compressed to `app.log.YYYY-MM-DD.gz`, keeping
`CHAT_LOG_RETENTION_DAYS` of them. Each line carries the time, the severity, the
logger name, and the details of the event:

```text
2026-09-07 12:41:03 INFO tspo.chat Client connected: user=noam room=general ip=10.0.0.5
```

Passwords, password hashes, tokens, and request bodies are never written. Chat
text is never written either: a saved message is recorded at DEBUG as its room,
sender, row id, and size. Values that came from a client have their control
characters replaced, so nobody can add invented lines to the log.

Startup and shutdown, connections and disconnections, sign-ups, successful and
failed logins, DLP blocks, database failures, broadcast failures, session
cleanup, and unhandled errors are all recorded. Per-message and per-request
lines are at DEBUG, so `CHAT_LOG_LEVEL=INFO` stays readable on a busy server.

The browser UI reads `CHAT_MAX_MESSAGE_LENGTH` from `/health`, so the counter
under the message box always matches the server.

Password rules, the username rules, and the password hashing cost are
deliberately not settings. Lowering them would weaken how accounts are
protected, so they stay in `server/server.py`.

## Install

These are the manual steps the Quick Start script performs for you.

Run this once:

```powershell
pip install -r requirements.txt
```

Build the browser UI once as well. This needs [Node.js](https://nodejs.org/) 20
or newer and writes the finished page into `web/dist`:

```powershell
cd web
npm install
npm run build
cd ..
```

The terminal client works without this step. The browser UI needs it, because
the server only serves the compiled files in `web/dist`.

## Run The Server

On the laptop that hosts the server:

```powershell
cd "C:\Users\Admin\Desktop\Bootcamp\checkPointProject\checkpoint-yovel-or-noam"
# Required only for the two-computer demo: accept LAN connections explicitly.
$env:CHAT_BIND_HOST="0.0.0.0"
python server\server.py
```

By default, the server accepts only local connections (`127.0.0.1`). The command
above opens it to the local network for the two-computer demo; do not use that
setting on a public or untrusted network.

## Open The Web UI

On the server laptop, open this address in a browser:

```text
http://localhost:8000
```

The server prints every address the UI can be opened from when it starts. From
another laptop, use the server's IPv4 address instead, for example
`http://192.168.1.20:8000`.

The page asks for a username and password, then for a room, and then shows the
chat. Press `Enter` to send a message and use the room buttons at the top to move
between `general` and `secret-pizza`. `Leave` signs out.

The UI is served by the same Python server that answers `/health`, `/signup`, and
`/login`, so the browser never makes a cross-site request and the project needs
no CORS rules.

### Which addresses the browser may use

A browser always sends an `Origin` header, so the WebSocket server keeps a list
of the exact addresses the UI is allowed to come from. The list is built from
`localhost`, `127.0.0.1`, and the address the server is bound to. When
`CHAT_BIND_HOST` is `0.0.0.0`, the server also detects the LAN address of the
laptop. Any other website is still refused, so no outside page can open a chat
socket for a logged-in user.

If the server does not detect the right address for the two-computer demo, name
it before starting the server:

```powershell
$env:CHAT_WEB_HOSTS="192.168.1.20"
```

### Changing the UI

While working on the UI, run the Vite dev server for instant reloading. Keep the
Python server running in another window:

```powershell
cd web
npm run dev
```

That serves the UI on `http://localhost:5173` and forwards `/health`, `/signup`,
and `/login` to the Python server on port 8000. Run `npm run build` again when
finished, so `http://localhost:8000` serves the updated page.

## Find The Server IP

On the server laptop:

```powershell
ipconfig
```

Use the `IPv4 Address` under `Wi-Fi`.

## Run A Client On The Same Laptop

```powershell
cd "C:\Users\Admin\Desktop\Bootcamp\checkPointProject\checkpoint-yovel-or-noam"
python client\cli_client.py
```

## Run A Client From Another Laptop

Replace `SERVER_IP` with the real IPv4 address of the server laptop:

```powershell
cd "C:\Users\yovel\Desktop\checkpoint-yovel-or-noam"
$env:CHAT_SERVER_URI="ws://SERVER_IP:8765"
$env:CHAT_REST_URI="http://SERVER_IP:8000"
python client\cli_client.py
```

## Client Flow

When the client starts:

```text
Choose action: signup/login:
Username:
Password:
Room (general/secret-pizza):
```

Use `signup` the first time. Use `login` after the user already exists.

To leave the chat:

```text
exit
```

## Test Health

On the server laptop:

```powershell
Invoke-RestMethod "http://localhost:8000/health"
```

From another laptop:

```powershell
Invoke-RestMethod "http://SERVER_IP:8000/health"
```

## Security Checks

Run the project's automated tests:

```powershell
python -m pytest -q
```

Check installed Python packages for known published vulnerabilities:

```powershell
python -m pip install -r requirements-dev.txt
python -m pip_audit
```

The server also enforces these protections:

- New usernames are 3-16 letters, numbers, `_`, or `-`; new passwords are 8-128 characters.
- Password hashes use PBKDF2-HMAC-SHA256 with 600,000 iterations. Old accounts continue to work with their original hash cost.
- Login attempts, signups, WebSocket connections, and message speed are rate-limited.
- Tokens expire after one hour; HTTP request bodies and WebSocket messages have size limits.
- Raw chat text is not written to the log, and control characters in messages are rejected.
- DLP blocks pineapple, TSPO secret markers, recipe declarations, and recipe-like messages before they are saved or sent. Three DLP violations close the connection. See [the full DLP policy](docs/dlp-policy.md).
- Anti-Bot checks every public client IP against VirusTotal before authentication. Malicious or suspicious IPs are blocked; private lab-network IPs are allowed. Results are cached for 10 minutes.

For the browser UI the server also enforces these:

- The WebSocket server accepts only the listed UI addresses and the terminal client. It never allows a wildcard origin.
- Pages are sent with `Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy` headers.
- Only files inside `web/dist` are served, and only known web file types. Paths containing `..` cannot reach other folders.
- The login token is kept in memory only. It is never written to `localStorage`, so closing the tab ends the session.
- Chat text is inserted as text, never as HTML, so a message such as `<img src=x onerror=...>` is shown as plain characters.

### Network encryption

The default `http://` and `ws://` setup is for a trusted local demo network only.
Do not expose it to the internet. A real deployment must place the app behind a
TLS-enabled reverse proxy and use `https://` and `wss://` URLs, otherwise a
person on the network could read passwords, tokens, and messages.

See [Publishing On The Internet](#publishing-on-the-internet) for the supported
way to do that.

## Publishing On The Internet

Never open ports 8000 and 8765 to the internet directly: passwords, tokens, and
messages would travel in the clear. Put Caddy in front instead. It holds the
certificate and forwards to the Python server, which stays on `127.0.0.1`.

```text
browser --https/wss--> Caddy :443 --http/ws--> Python 127.0.0.1:8000 and :8765
```

1. Point a domain name at this machine's public IP address (an `A` record).
2. Open only the proxy ports:

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

3. Start the chat server with the public address, so it accepts that origin and
   reads the real caller address from the proxy:

```bash
export CHAT_BIND_HOST=127.0.0.1
export CHAT_PUBLIC_ORIGIN=https://chat.example.com
export CHAT_TRUST_PROXY=1
python server/server.py
```

4. Start the proxy:

```bash
sudo CHAT_DOMAIN=chat.example.com caddy run --config deploy/Caddyfile
```

Use `deploy/tspo-chat.service` to keep the server running after a reboot.

### What those settings change

- `CHAT_PUBLIC_ORIGIN` adds `https://chat.example.com` to the allowed WebSocket
  origins and adds `wss://chat.example.com` to the page policy. `/health` then
  reports `websocket_path`, and the browser opens `wss://chat.example.com/ws`
  over port 443, so port 8765 is never published.
- `CHAT_TRUST_PROXY=1` makes the server read the caller address from
  `X-Forwarded-For`. Without it every visitor looks like `127.0.0.1`, so all of
  them would share one rate-limit bucket, the sixth visitor would be refused by
  the per-IP connection limit, and Anti-Bot would treat everyone as a private
  address and wave them through.
- The header is only believed when the connection really arrives from the local
  proxy, and only the last entry is used, because that is the one the proxy
  itself wrote. A visitor who sends a fake `X-Forwarded-For` is still recorded
  under their real address.

### Before publishing

- Set `VIRUSTOTAL_API_KEY`. Without it Anti-Bot records `REPUTATION_UNAVAILABLE`
  and allows every public address, so the gate does nothing.
- Signup is open to anyone who finds the address. Rate limits slow that down but
  do not stop it.

### VirusTotal (optional, required for public-IP Anti-Bot checks)

VirusTotal is for checking a suspicious downloaded file, not for uploading this
project's source code, `data/chat.db`, `.env`, or logs. Public VirusTotal file
uploads can be shared with security partners.

1. Create a VirusTotal Community account and copy your API key from its profile.
2. Set the key only for the current PowerShell window:

```powershell
$env:VIRUSTOTAL_API_KEY="paste-your-key-here"
```

Alternatively, paste it after `VIRUSTOTAL_API_KEY=` in the local `.env` file.
The server reads that file at startup; `.env` is ignored by Git.

Start the server from that same PowerShell window. Without an API key, the
server allows public IPs and records `REPUTATION_UNAVAILABLE`; it never places
the key in the repository. Private IPs in a classroom or home network are
allowed with `IP_PRIVATE_NETWORK`.

3. First check whether a file's SHA-256 is already known. This does **not**
upload the file:

```powershell
python scripts\virustotal_check.py "C:\path\to\suspicious-file.exe"
```

4. Only when the file is safe to share publicly and no report exists, upload it:

```powershell
python scripts\virustotal_check.py "C:\path\to\suspicious-file.exe" --upload
```

## Docker

The whole server, including the compiled browser UI, runs in one container:

```bash
docker compose up --build -d      # then open http://localhost:8000
docker compose down               # stop, keeping the database
```

The build, the port and storage rules and the troubleshooting table are in
[the Docker notes](docs/docker.md).

## Load Testing

`scripts/loadtest.py` drives simulated people through the real protocol - signup,
login, joining rooms, chatting, leaving, reconnecting and misbehaving - and
reports what the server did while it was busy. It starts its own server on unused
ports by default, so a run never touches real data.

```bash
python scripts/loadtest.py --scenario all
python scripts/loadtest.py --scenario chat --users 40 --messages 10
python scripts/loadtest.py --scenario login --users 25 --production-limits
python scripts/loadtest.py --scenario chat --target http://localhost:8000
```

The workload of each scenario, the measured results and what they showed about
the server are written up in [the load-testing notes](docs/load-testing.md).

## Final Demo Checklist (Day 3)

Use [the complete final-demo guide](docs/final-demo.md) for commands, expected
results, and the presentation order. The short classroom sequence is:

1. Start the server from the documented commands and open `/health`.
2. Show signup, duplicate-user rejection, wrong-password rejection, and a correct login.
3. Show that an invalid token cannot enter the chat.
4. Connect two authenticated clients, exchange a message, and demonstrate room isolation.
5. Send `pineapple` and show the DLP action and reason code before distribution.
6. Show a live IP-reputation verdict and the repeatable malicious-IP enforcement test.
7. Disconnect and reconnect a client, then inspect the relevant log events.
8. Explain the architecture, two design patterns, a test/fix/retest example, and one limitation.

## Files

```text
server/server.py      Server, REST API, login, rooms, logs, SQLite, serves web/dist
client/cli_client.py  Terminal chat client
web/                  React + Tailwind browser client
web/src/lib/          REST calls and the shared WebSocket protocol rules
web/src/hooks/        Connection state and the /health lookup
web/src/components/   Login card, chat room, message list, composer
web/dist/             Compiled page created by `npm run build`, not in Git
deploy/Caddyfile      TLS reverse proxy config for publishing on the internet
deploy/tspo-chat.service  systemd unit that keeps the server running
scripts/start.sh      Prepares everything and starts the server
scripts/loadtest.py   Simulated users for load and edge-case testing
Dockerfile            Two-stage build: Node compiles the UI, Python runs it
docker-compose.yml    One-command startup with named volumes for data and logs
.env.example          Template for .env, where the limits are set
data/chat.db          Local SQLite database, created automatically
logs/app.log          Log file, created automatically
```
