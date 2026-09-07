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

## Install

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

## Day 1 Demo Checklist

1. Start the server.
2. Open `/health`.
3. Sign up two users from two clients (browser tabs, terminal clients, or one of each).
4. Log in with both users.
5. Join both users to `general`.
6. Send messages and show both clients receive them.
7. Connect a third client to `secret-pizza`.
8. Send a message in `general` and show the third client does not receive it.
9. Try an empty message and show it is rejected.
10. Type `exit` (or press `Leave` in the browser), reconnect, and show the server keeps running.
11. Open `logs/app.log` and show connection, room, message, and error events.
12. Send `pineapple` from the browser and show the blocked message and the reason code.

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
data/chat.db          Local SQLite database, created automatically
logs/app.log          Log file, created automatically
```
