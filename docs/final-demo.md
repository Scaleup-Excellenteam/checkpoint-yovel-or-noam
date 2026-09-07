# TSPO Final Demo - Day 3

This checklist keeps the classroom demo short, repeatable, and honest. Allow
about 8-10 minutes. Use test accounts and never display the VirusTotal API key.

## 1. Prepare before class

On the server computer, install and build once:

```powershell
cd "C:\Users\yovel\Desktop\checkpoint-yovel-or-noam"
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
cd web
npm.cmd install
npm.cmd run build
cd ..
```

For a two-computer demo, start the server with LAN access:

```powershell
$env:CHAT_BIND_HOST="0.0.0.0"
.\.venv\Scripts\python.exe server\server.py
```

Open `http://localhost:8000` on the server computer. On another computer, open
`http://SERVER_IP:8000`, replacing `SERVER_IP` with the server's IPv4 address.

Keep another PowerShell window open for the logs:

```powershell
Get-Content .\logs\app.log -Tail 20 -Wait
```

## 2. Health and identity

1. Open `http://SERVER_IP:8000/health` and show `"status": "ok"`.
2. Sign up `demo_alice` with a password of at least eight characters.
3. Leave, choose **Sign up**, and repeat the same username. Show the duplicate-user error.
4. Choose **Log in** and enter a wrong password. Show the invalid-credentials error.
5. Log in correctly and explain that the server returns a random token valid for one hour.
6. Run the authentication integration test to prove that an invalid token cannot enter chat:

```powershell
.\.venv\Scripts\python.exe -m pytest -vv tests\test_websocket_integration.py
```

Expected result: the test passes after checking `Authentication failed: invalid token`.

## 3. Chat and room isolation

1. Log in as `demo_alice` and `demo_bob` in two browser windows.
2. Put both users in `general` and exchange a normal message.
3. Move `demo_bob` to `secret-pizza`. The browser closes the old WebSocket and opens a new one.
4. Send another message from `general` and show that `demo_bob` does not receive it.

## 4. DLP decision

1. Send `hello team` and show that it is delivered.
2. Send `pineapple` and show `Message blocked: DLP_FORBIDDEN_PINEAPPLE`.
3. Explain that the blocked text is neither stored in SQLite nor sent to the room.
4. The integration test from the previous section verifies both facts automatically.

## 5. Anti-Bot decision

A classroom client normally has a private IP, so the visible result will be:

```text
Anti-Bot passed: IP_PRIVATE_NETWORK
```

To show real VirusTotal evidence, place the API key in the local `.env` file and
check a public IP approved by the instructor:

```powershell
.\.venv\Scripts\python.exe scripts\ip_reputation_check.py PUBLIC_IP
```

The command prints only the IP, `ALLOW` or `BLOCK`, and the reason code. It never
prints the API key. A malicious result is `IP_REPUTATION_MALICIOUS`; a clean
result is `IP_REPUTATION_CLEAN`.

Then show that the server enforces a malicious verdict before authentication:

```powershell
.\.venv\Scripts\python.exe -m pytest -vv tests\test_reputation.py::test_malicious_ip_is_blocked_before_authentication
```

Be explicit: the first command is live reputation evidence; the second is a
repeatable enforcement test. Do not claim that a simulated result came live
from VirusTotal.

## 6. Recovery and logs

1. Press **Leave** or close one browser window.
2. Log in again and reconnect to the room.
3. Send a message and show that the server stayed usable.
4. In the log window, point to the connect, join, DLP block, disconnect, and reconnect events.

## 7. Engineering explanation

Explain these four points briefly:

- REST handles short signup and login requests; WebSocket carries live chat.
- `asyncio` lets the server handle several connected clients concurrently.
- Observer/Publish-Subscribe distributes a message only to subscribers in its room.
- Strategy/Dependency Injection lets tests replace the real VirusTotal fetcher.

State one honest limitation: the DLP matches configured words and patterns, so
it can miss indirect wording or block an innocent sentence.

## 8. Test, fix, retest example

Use the network-validation improvement as the example:

1. Bandit reported unrestricted `urlopen` calls.
2. The client now validates HTTP/HTTPS addresses, and VirusTotal calls validate
   the official HTTPS host and use timeouts.
3. The validation tests pass and Bandit reports no medium/high findings:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m bandit -q -r server client scripts -ll
```

## Final pre-demo check

- Both computers can open the site and exchange messages.
- The `.env` file and API key are not shown or committed.
- All automated tests pass.
- The prepared public IP has a current VirusTotal result.
- Team members know who explains identity, chat, DLP, Anti-Bot, tests, and limitations.
