import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "server"))

import server


def test_create_user_rejects_duplicate_username(tmp_path: Path) -> None:
    """Check that signup blocks an existing username."""
    server.DB_PATH = tmp_path / "chat.db"
    server.init_database()

    assert server.create_user("noam", "1234") is True
    assert server.create_user("noam", "5678") is False


def test_check_login_accepts_correct_password_only(tmp_path: Path) -> None:
    """Check that login accepts only the saved password."""
    server.DB_PATH = tmp_path / "chat.db"
    server.init_database()
    server.create_user("yuval", "secret")

    assert server.check_login("yuval", "secret") is True
    assert server.check_login("yuval", "wrong") is False
    assert server.check_login("missing", "secret") is False


def test_validate_username_rejects_more_than_16_characters() -> None:
    """Check that usernames are limited to 16 characters."""
    assert server.validate_username("a" * 16) is None
    assert server.validate_username("a" * 17) == "username cannot be longer than 16 characters"


def test_validate_chat_message_rejects_invalid_input() -> None:
    """Check that invalid chat messages are rejected."""
    assert server.validate_chat_message("") == "Message rejected: message cannot be empty"
    assert server.validate_chat_message("   ") == "Message rejected: message cannot be empty"
    assert server.validate_chat_message("hello") is None


def test_normalize_room_name_accepts_small_typos() -> None:
    """Check that small room-name typos are mapped to a real room."""
    assert server.normalize_room_name("general") == "general"
    assert server.normalize_room_name("generl") == "general"
    assert server.normalize_room_name("secret-piza") == "secret-pizza"
    assert server.normalize_room_name("unknown") is None


def test_save_message_stores_room_message(tmp_path: Path) -> None:
    """Check that messages are saved with sender, room, and content."""
    server.DB_PATH = tmp_path / "chat.db"
    server.init_database()

    server.save_message("noam", "general", "hello")

    with sqlite3.connect(server.DB_PATH) as connection:
        row = connection.execute(
            "SELECT username, room, content FROM messages"
        ).fetchone()

    assert row == ("noam", "general", "hello")
