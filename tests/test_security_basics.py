import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "server"))

import server


def test_sql_injection_text_is_not_a_valid_login(tmp_path):
    """Parameterized SQL must treat an injection attempt as plain text."""
    server.DB_PATH = tmp_path / "chat.db"
    server.init_database()
    server.create_user("yovel", "correct-password")

    assert server.check_login("' OR '1'='1", "anything") is False


def test_message_over_limit_is_rejected():
    too_long_message = "a" * (server.MAX_MESSAGE_LENGTH + 1)

    assert server.validate_chat_message(too_long_message) == (
        f"Message rejected: message cannot be longer than {server.MAX_MESSAGE_LENGTH} characters"
    )
    assert server.validate_chat_message("hello\nworld") == "Message rejected: control characters are not allowed"


def test_signup_rejects_weak_or_invalid_credentials():
    assert server.validate_signup("ab", "long-enough") is not None
    assert server.validate_signup("bad name", "long-enough") is not None
    assert server.validate_signup("yovel", "short") is not None
    assert server.validate_signup("yovel", "long-enough") is None


def test_expired_token_is_rejected():
    server.active_tokens["expired"] = server.TokenSession("yovel", time.monotonic() - 1)

    assert server.get_token_username("expired") is None
    assert "expired" not in server.active_tokens


def test_sensitive_local_files_are_gitignored():
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "data/*.db" in gitignore
    assert "logs/*.log" in gitignore
    assert ".env" in gitignore
import time
