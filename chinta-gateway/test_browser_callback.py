"""Browser OAuth callback completion at the gateway."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import SESSION_COOKIE_NAME, app, ui_browser_path


@pytest.fixture
def client():
    return TestClient(app)


def test_ui_browser_path_strips_localhost_host():
    """Absolute CHINTA_WEB_URL must not dictate post-login Location host."""
    assert ui_browser_path("http://localhost:8084/ui") == "/ui"
    assert ui_browser_path("https://api.example.com/ui/") == "/ui"
    assert ui_browser_path("/ui") == "/ui"


@patch("app.httpx.AsyncClient")
def test_browser_callback_sets_cookie_and_redirects(mock_client_cls, client):
    mock_client = AsyncMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    mock_resp = type("Resp", (), {})()
    mock_resp.status_code = 200
    mock_resp.json = lambda: {"access_token": "at-123", "token_type": "Bearer"}
    mock_client.get = AsyncMock(return_value=mock_resp)

    r = client.get("/auth/callback", params={"code": "abc"}, follow_redirects=False)
    assert r.status_code == 302
    # Relative Location: public OIDC base + localhost CHINTA_WEB_URL must not
    # bounce the browser off the gateway host that holds the session cookie.
    assert r.headers["location"] == "/ui/app"
    assert r.headers.get("cache-control") == "no-store"
    assert r.cookies.get(SESSION_COOKIE_NAME) == "at-123"


@patch("app.httpx.AsyncClient")
@patch("app.WEB_UI_URL", "http://localhost:8084/ui")
def test_browser_callback_ignores_absolute_localhost_web_url(mock_client_cls, client):
    mock_client = AsyncMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    mock_resp = type("Resp", (), {})()
    mock_resp.status_code = 200
    mock_resp.json = lambda: {"access_token": "at-999", "token_type": "Bearer"}
    mock_client.get = AsyncMock(return_value=mock_resp)

    r = client.get("/auth/callback", params={"code": "xyz"}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/ui/app"
    assert "localhost" not in r.headers["location"]


@patch("app._proxy_auth_request", new_callable=AsyncMock)
def test_callback_json_format_proxies(mock_proxy, client):
    from fastapi.responses import Response

    mock_proxy.return_value = Response(content=b"{}", status_code=200)
    r = client.get("/auth/callback", params={"code": "x", "format": "json"})
    assert r.status_code == 200
    mock_proxy.assert_awaited_once()


def test_root_redirect_is_same_origin_relative(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/ui"
