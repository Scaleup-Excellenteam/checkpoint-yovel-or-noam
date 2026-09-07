import json
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "server"))

import server


@pytest.fixture
def rest_api(tmp_path):
    """Run the REST API on a temporary port and database for one test."""
    server.DB_PATH = tmp_path / "chat.db"
    server.init_database()
    server.active_tokens.clear()
    http_server = ThreadingHTTPServer(("127.0.0.1", 0), server.RestRequestHandler)
    thread = Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{http_server.server_port}"
    http_server.shutdown()
    http_server.server_close()
    thread.join()


def post_json(base_url, path, payload):
    request = Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request) as response:
        return response.status, json.loads(response.read())


def test_rest_api_health_signup_and_login(rest_api):
    with urlopen(f"{rest_api}/health") as response:
        health = json.loads(response.read())
    assert health["status"] == "ok"

    status, signup = post_json(rest_api, "/signup", {"username": "noam", "password": "secret123"})
    assert status == 201
    assert signup["username"] == "noam"

    status, login = post_json(rest_api, "/login", {"username": "noam", "password": "secret123"})
    assert status == 200
    assert login["token"] in server.active_tokens


def test_rest_api_rejects_wrong_password(rest_api):
    post_json(rest_api, "/signup", {"username": "noam", "password": "secret123"})

    with pytest.raises(HTTPError) as error:
        post_json(rest_api, "/login", {"username": "noam", "password": "wrong"})

    assert error.value.code == 401
