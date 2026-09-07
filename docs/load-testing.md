# Load testing the chat server

`scripts/loadtest.py` is a virtual bot inspector. It drives simulated people
through the real protocol - signing up, logging in, joining rooms, chatting,
leaving, reconnecting and misbehaving - and reports what the server did while it
was busy.

It speaks the same WebSocket handshake as `client/cli_client.py` and the browser
UI. Nothing is stubbed: every message goes over a real socket to the real server
code, through DLP, Anti-Bot, the rate limits and SQLite.

## Running it

By default the tool starts a **private server on unused ports** with its own
database and log folder, so a run never touches real data and always starts from
the same state.

```bash
python scripts/loadtest.py --scenario all
python scripts/loadtest.py --scenario chat --users 40 --messages 10
python scripts/loadtest.py --scenario login --users 25 --production-limits
python scripts/loadtest.py --scenario all --json results.json
```

To load a server that is already running, including the deployed one:

```bash
python scripts/loadtest.py --scenario chat --target http://localhost:8000
```

The tool exits with status 1 if any scenario fails, so it can be run from a
script or a pipeline.

### Rate limits during a run

The chat rate limits would otherwise be what gets measured rather than the
server, so by default the tool raises them and prints exactly which values it
used. `--production-limits` leaves the real values in place, which is how to
watch the limiter work.

## What each scenario does

| Scenario | Workload | What it checks |
| --- | --- | --- |
| `chat` | N users spread over both rooms, each sending M messages as fast as the server accepts them | Throughput, end-to-end latency, that every message reaches every member of its room, and that no message reaches the other room |
| `login` | N logins fired at the same instant for one account | How a class arriving together is served; each login runs PBKDF2 |
| `churn` | N users repeating join, talk, leave, rejoin a different room | That the server stays usable while connections come and go |
| `abuse` | Empty, over-length, control-character and DLP-triggering messages, a token the server never issued, a duplicate username and a wrong password | That every invalid input is refused with a reason and the server stays up |

Every chat message is a probe with a unique id. The tool records when each probe
was sent and which room it was sent to, then matches every arrival against it.
That is how delivery rate and cross-room leaks are counted rather than assumed.

## Observed results

Measured on a 4-core VPS, private server, limits raised, 10 messages per user.

### Chat, as concurrency grows

| Users | Send rate | Delivery rate | Latency p50 | Latency p95 | Delivered | Cross-room leaks |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 1781 msg/s | 8,904/s | 31 ms | 49 ms | 100% | 0 |
| 20 | 1720 msg/s | 17,201/s | 57 ms | 100 ms | 100% | 0 |
| 40 | 1046 msg/s | 20,916/s | 200 ms | 362 ms | 100% | 0 |

### Login burst

| Limits | Attempted | Accepted | Rate-limited | Failed | Slowest wait |
| --- | --- | --- | --- | --- | --- |
| Raised | 20 | 20 | 0 | 0 | 468 ms |
| Production | 25 | 5 | 20 | 0 | 305 ms |

### Churn and abuse

60 of 60 connect/join/leave/rejoin cycles completed at 223 cycles/sec, none
refused. All 8 abuse checks passed.

## Findings

### 1. The server queues under load; it never loses or misroutes a message

Going from 10 to 40 concurrent talkers, **delivery throughput kept rising**
(8,900 to 20,900 per second) while the per-message send rate fell and latency
grew about six times. Delivery stayed at **100% with zero cross-room leaks at
every level**.

That is the signature of a single event loop. All chat work - the DLP scan, the
database write and the fan-out to each room member - happens on one thread, so a
synchronised burst does not overload it, it forms a queue. Latency becomes queue
depth divided by service rate, which is why it grows roughly linearly with the
number of talkers while correctness is untouched.

The useful conclusion is that the limit to watch is **latency, not loss**. Users
would notice the chat feeling slow long before anything went wrong. Throughput
flattening near 21,000 deliveries per second is the fan-out ceiling of one loop;
getting past it needs more than tuning, it needs more than one loop.

### 2. Oversized input is handled by two different layers

A message over the 500-character limit gets a readable refusal from the chat
rules. A message over the 4096-byte **WebSocket frame limit** never reaches those
rules at all: the protocol layer closes the connection with code 1009 first.

Both are correct, but only the first is explainable to a user. This is why
`CHAT_MAX_MESSAGE_LENGTH` must stay below the frame limit, and why the server
logs a warning at startup if it is not.

### 3. The rate limiter refuses cleanly rather than dropping connections

With production limits, 25 simultaneous logins produced exactly **5 accepted and
20 refused with HTTP 429, and no failed connections**. The limiter matches its
configured value and answers every caller, which is what makes the refusal
visible to the client instead of looking like an outage.

## Limitations

- The tool runs on the same machine as the server, so the numbers exclude real
  network latency and the load generator competes for the same CPU. Treat them as
  a floor for latency and a ceiling for throughput.
- The `chat` scenario sends as fast as the server accepts, which is a burst, not
  a realistic typing pattern. It is a stress test, not a simulation of a class.
- Nothing here measures memory over hours. The findings are about behaviour under
  a burst, not about long-running stability.
