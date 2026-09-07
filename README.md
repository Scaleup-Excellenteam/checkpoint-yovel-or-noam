# TSPO Chat

Simple Python WebSocket chat project for the Tel-Hai Bootcamp checkpoint.

## What Works For Day 1

- One server can accept multiple clients.
- Clients can connect from another laptop on the same network.
- WebSocket chat runs on port `8765`.
- REST API runs on port `8000`.
- `GET /health` shows that the server is alive.
- Users can sign up and log in.
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

## Run The Server

On the laptop that hosts the server:

```powershell
cd "C:\Users\Admin\Desktop\Bootcamp\checkPointProject\checkpoint-yovel-or-noam"
python server\server.py
```

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

- New usernames are 3-32 letters, numbers, `_`, or `-`; new passwords are 8-128 characters.
- Password hashes use PBKDF2-HMAC-SHA256 with 600,000 iterations. Old accounts continue to work with their original hash cost.
- Login attempts, signups, WebSocket connections, and message speed are rate-limited.
- Tokens expire after one hour; HTTP request bodies and WebSocket messages have size limits.
- Raw chat text is not written to the log, and control characters in messages are rejected.
- DLP blocks pineapple, TSPO secret markers, recipe declarations, and recipe-like messages before they are saved or sent. Three DLP violations close the connection. See [the full DLP policy](docs/dlp-policy.md).
- Anti-Bot checks every public client IP against VirusTotal before authentication. Malicious or suspicious IPs are blocked; private lab-network IPs are allowed. Results are cached for 10 minutes.

### Network encryption

The default `http://` and `ws://` setup is for a trusted local demo network only.
Do not expose it to the internet. A real deployment must place the app behind a
TLS-enabled reverse proxy and use `https://` and `wss://` URLs, otherwise a
person on the network could read passwords, tokens, and messages.

### VirusTotal (optional, required for public-IP Anti-Bot checks)

VirusTotal is for checking a suspicious downloaded file, not for uploading this
project's source code, `data/chat.db`, `.env`, or logs. Public VirusTotal file
uploads can be shared with security partners.

1. Create a VirusTotal Community account and copy your API key from its profile.
2. Set the key only for the current PowerShell window:

```powershell
$env:VIRUSTOTAL_API_KEY="paste-your-key-here"
```

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
3. Sign up two users from two clients.
4. Log in with both users.
5. Join both users to `general`.
6. Send messages and show both clients receive them.
7. Connect a third client to `secret-pizza`.
8. Send a message in `general` and show the third client does not receive it.
9. Try an empty message and show it is rejected.
10. Type `exit`, reconnect, and show the server keeps running.
11. Open `logs/app.log` and show connection, room, message, and error events.

## Files

```text
server/server.py      Server, REST API, login, rooms, logs, SQLite
client/cli_client.py  Terminal chat client
data/chat.db          Local SQLite database, created automatically
logs/app.log          Log file, created automatically
```
