"""Tests for client-side network-address validation."""

import pytest

from client.cli_client import post_json


def test_post_json_rejects_a_non_http_address() -> None:
    """The client must not pass local file URLs to urllib."""
    with pytest.raises(ValueError, match="http"):
        post_json("file:///C:/private-file", "/login", {})


def test_post_json_requires_an_absolute_api_path() -> None:
    """A relative path could create an unintended request URL."""
    with pytest.raises(ValueError, match="path"):
        post_json("http://127.0.0.1:8000", "login", {})
