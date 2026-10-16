"""Unit tests for chinta-ui routes (no live gateway)."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# App is reached at / on :8086; browser links use /ui via gateway proxy.
os.environ["CHINTA_UI_MOUNT_PATH"] = ""

from app import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app, follow_redirects=False)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_login_page_renders(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "Sign in" in r.text


def test_app_redirects_without_session(client):
    r = client.get("/app", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/login")


@patch("app.fetch_me", new_callable=AsyncMock)
@patch("app.list_notes", new_callable=AsyncMock)
def test_app_renders_with_session(mock_list, mock_me, client):
    mock_me.return_value = {"sub": "u1", "name": "Ada"}
    mock_list.return_value = [{"body": "hello", "modified_at": "2026-01-01T00:00:00Z"}]
    r = client.get("/app", cookies={"chinta_access_token": "tok"})
    assert r.status_code == 200
    assert "Ada" in r.text
    assert "hello" in r.text


@patch("app.create_note", new_callable=AsyncMock)
def test_create_note_redirects(mock_create, client):
    mock_create.return_value = {"id": 1}
    r = client.post("/notes", data={"body": "new"}, cookies={"chinta_access_token": "tok"})
    assert r.status_code == 303
    assert r.headers["location"].endswith("/app")
    mock_create.assert_awaited_once()


def _set_cookie_headers(response) -> list[str]:
    # Starlette may expose one or many Set-Cookie values depending on version.
    return [v for k, v in response.headers.multi_items() if k.lower() == "set-cookie"]


def test_logout_clears_secure_cookie_when_public_url_is_https(client, monkeypatch):
    """Gateway sets Secure on https origins; clear must match or the session sticks."""
    monkeypatch.setenv("CHINTA_PUBLIC_URL", "https://app.example.com")
    # get_config reads env each call; no cache to clear.
    r = client.get("/logout", follow_redirects=False)
    assert r.status_code == 302
    cookies = _set_cookie_headers(r)
    assert cookies, "expected Set-Cookie to clear session"
    joined = " ".join(cookies).lower()
    assert "chinta_access_token=" in joined
    assert "secure" in joined
    assert "httponly" in joined


def test_logout_clear_cookie_not_secure_on_http_public_url(client, monkeypatch):
    monkeypatch.setenv("CHINTA_PUBLIC_URL", "http://localhost:8084")
    r = client.get("/logout", follow_redirects=False)
    assert r.status_code == 302
    cookies = _set_cookie_headers(r)
    assert cookies
    joined = " ".join(cookies).lower()
    assert "chinta_access_token=" in joined
    assert "secure" not in joined


@patch("app.fetch_me", new_callable=AsyncMock)
def test_expired_session_clears_secure_cookie(mock_me, client, monkeypatch):
    from gateway_client import GatewayError

    monkeypatch.setenv("CHINTA_PUBLIC_URL", "https://app.example.com")
    mock_me.side_effect = GatewayError(401, "expired")
    r = client.get("/app", cookies={"chinta_access_token": "stale"}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/login")
    joined = " ".join(_set_cookie_headers(r)).lower()
    assert "chinta_access_token=" in joined
    assert "secure" in joined
