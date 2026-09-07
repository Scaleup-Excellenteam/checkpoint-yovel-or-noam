# Continuous integration

`.github/workflows/ci.yml` checks every change automatically. It is the same set
of commands a person would run before pushing, so nothing reaches `main` without
the tests, the security scans, the UI build and the container all being checked.

## When it runs

| Trigger | Why |
| --- | --- |
| `push` to `main` | Confirms the branch everyone shares is still good after a merge. |
| `pull_request` targeting `main` | Checks the change **before** it is merged, which is where a problem is cheapest to fix. |
| `workflow_dispatch` | Lets anyone start a run by hand from the Actions tab, which is useful before a demo. |

A newer push to the same branch cancels the run that is already in flight
(`concurrency` with `cancel-in-progress`), so the queue never fills with results
nobody is waiting for.

## What it does

The workflow has two jobs that run at the same time.

### Job 1: tests, security and UI build

| Stage | Command | What it protects |
| --- | --- | --- |
| Install | `pip install -r requirements-dev.txt` | Cached on `requirements-dev.txt`, so unchanged dependencies are not downloaded again. |
| Tests | `python -m pytest -q` | The whole suite. Given 15 minutes of its own because password hashing is deliberately slow and several tests sign in dozens of accounts at once. |
| Security scan | `python -m bandit -q -r server client scripts` | Catches unsafe patterns in the Python we wrote. |
| Dependency audit | `python -m pip_audit -r requirements.txt` | Checks the packages that actually ship. Auditing the file rather than the whole environment means an advisory against a development-only tool cannot fail the build. |
| UI build | `npm ci && npm run build` | Proves the browser client still compiles. Cached on `web/package-lock.json`. |
| UI output check | `test -f web/dist/index.html` | A build can succeed and still produce nothing useful. |
| Load-test smoke | `python scripts/loadtest.py --scenario abuse` | Starts its own server on unused ports and proves invalid input, unissued tokens, DLP and the duplicate-username and wrong-password paths are all still refused. |

### Job 2: container build and smoke test

| Stage | What it proves |
| --- | --- |
| `docker build` | The image still builds, including the Node stage that compiles the UI. |
| `docker run` with ports 8000 and 8765 | The packaged application starts. |
| Wait for `HEALTHCHECK` | The server inside the container answers `/health` on its own. |
| `curl /health` and `curl /` | The REST API and the browser page are both served by the image. |
| `loadtest.py --target` | A real client reaches the packaged application over the real protocol, rather than only the port answering. |
| `docker logs` on failure | The container log is printed when anything fails, so a red run can be diagnosed without rerunning it. |

## Secrets

The workflow uses **no secrets at all**. It never deploys, never publishes an
image and never contacts the running server, so there is nothing to pass in and
nothing that could be printed. Its token is restricted to `contents: read`, which
is only enough to check the code out.

The container it starts has no `VIRUSTOTAL_API_KEY`, so Anti-Bot answers
`REPUTATION_UNAVAILABLE` during the smoke test. That is expected: the point of
that stage is that the packaged application runs and speaks the protocol, not
that the reputation service is reachable.

## Reading a failure

Open the Actions tab, pick the run, and open the job that is red. Each stage is a
separate step, so the failing command is the one that is expanded. The container
job also prints the container log whenever it fails.
