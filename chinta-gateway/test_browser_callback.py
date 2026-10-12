"""Browser OAuth callback completion at the gateway."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import SESSION_COOKIE_NAME, app


@pytest.fixture
def client():
    return TestClient(app)


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
    assert r.headers["location"].endswith("/ui/app")
    assert r.cookies.get(SESSION_COOKIE_NAME) == "at-123"


@patch("app._proxy_auth_request", new_callable=AsyncMock)
def test_callback_json_format_proxies(mock_proxy, client):
    from fastapi.responses import Response

    mock_proxy.return_value = Response(content=b"{}", status_code=200)
    r = client.get("/auth/callback", params={"code": "x", "format": "json"})
    assert r.status_code == 200
    mock_proxy.assert_awaited_once()
