# Running the chat server in Docker

The image packages the Python server together with the compiled browser UI, so
one container serves the REST API, the web page and the chat socket.

## Build and run

```bash
docker compose up --build -d
```

Then open <http://localhost:8000>. Stop it with:

```bash
docker compose down          # keep the database and logs
docker compose down -v       # also delete them
```

Without Compose:

```bash
docker build -t tspo-chat:local .
docker run -d --name tspo-chat \
  -p 8000:8000 -p 8765:8765 \
  -v chat-data:/app/data \
  -v chat-logs:/app/logs \
  -e CHAT_BIND_HOST=0.0.0.0 \
  tspo-chat:local
```

## How the image is built

It is a two-stage build. The first stage uses Node to run `npm ci` and
`npm run build`; the second stage is a slim Python image that copies only the
finished `web/dist` across. Node and `node_modules` never reach the final image,
which keeps it around 210 MB.

The application runs as the unprivileged user `tspo` (uid 10001), not root.

## Ports

| Port | Purpose |
| --- | --- |
| 8000 | REST API, `/health`, and the browser UI |
| 8765 | The chat WebSocket |

**Map both ports one to one.** The list of allowed WebSocket origins is built
from port 8000, so publishing the UI on another host port makes the browser send
an `Origin` the server does not recognise and the socket is refused. The browser
also derives the chat address from `websocket_port` in `/health`, so port 8765
has to be reachable at that number too.

If you need a different external port, put a TLS reverse proxy in front and set
`CHAT_PUBLIC_ORIGIN`, as described in the main README.

## Storage

`data/` and `logs/` are **named volumes**, not bind mounts. SQLite runs in WAL
mode, which needs working file locking; a named volume lives on the Docker
filesystem where locking behaves correctly on every host. Bind mounts to a
Windows or macOS folder are known to break SQLite locking, and the symptom is an
intermittent `database is locked` rather than a clear failure.

Because the image creates `/app/data` and `/app/logs` already owned by uid 10001,
a fresh named volume inherits that ownership and the unprivileged user can write
to it.

Data survives `docker compose down` and container recreation. It is deleted only
by `docker compose down -v` or `docker volume rm`.

## Settings and secrets

No secret is ever copied into the image. `.dockerignore` excludes `.env`, the
database, the WAL sidecar files and the logs, so they cannot end up in a layer.

Settings come from the environment. Compose reads an optional `.env` from the
project folder and passes it to the container; the file does not have to exist.

```bash
# .env, kept out of Git and out of the image
VIRUSTOTAL_API_KEY=your-key
CHAT_MAX_CONNECTIONS=200
```

Every setting in `.env.example` works the same way inside the container.

## Health

The image declares a `HEALTHCHECK` that calls `/health` with Python, so no extra
package is needed in the image.

```bash
docker inspect -f '{{.State.Health.Status}}' tspo-chat
docker compose ps
```

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `failed to bind host port 0.0.0.0:8000: address already in use` | Something else already uses the port, often a server started outside Docker. Stop it, or free the port. Do not simply remap, see **Ports** above. |
| The page loads but the chat never connects | Port 8765 is not published, or the ports were remapped. Publish both, one to one. |
| `GET /` returns 503 | The image was built without the UI stage. Rebuild with `docker compose build --no-cache`. |
| `database is locked` | The database is on a bind mount that does not support SQLite locking. Use the named volume the Compose file defines. |
| Permission denied writing the database | The volume was created before the image set its ownership. `docker compose down -v` and start again. |
| Anti-Bot always answers `REPUTATION_UNAVAILABLE` | No `VIRUSTOTAL_API_KEY` is set. Put it in `.env`. |

Container logs:

```bash
docker compose logs -f chat
docker exec tspo-chat tail -f /app/logs/app.log
```
