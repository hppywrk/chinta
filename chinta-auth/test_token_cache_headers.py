"""Regression: OAuth token responses must not be cacheable (RFC 6749 §5.1)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app as auth_app

TOKEN_PAYLOAD = {
    "access_token": "access-secret",
    "refresh_token": "refresh-secret",
    "token_type": "Bearer",
    "expires_in": 3600,
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OIDC_CLIENT_ID", "test-client")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-secret")
    auth_app._oidc_metadata = {
        "authorization_endpoint": "https://idp.example/authorize",
        "token_endpoint": "https://idp.example/token",
        "userinfo_endpoint": "https://idp.example/userinfo",
    }
    yield TestClient(auth_app.app)
    auth_app._oidc_metadata = None


def _mock_oidc_client():
    mock = MagicMock()
    mock.token_endpoint = "https://idp.example/token"
    mock.fetch_token = AsyncMock(return_value=TOKEN_PAYLOAD)
    return mock


def test_callback_token_response_is_not_cacheable(client):
    """GET /auth/callback is browser-facing; caches must not store tokens."""
    with patch.object(
        auth_app, "get_oidc_client", new=AsyncMock(return_value=_mock_oidc_client())
    ):
        resp = client.get(
            "/auth/callback",
            params={"code": "abc", "redirect_uri": "http://localhost:8084/auth/callback"},
        )

    assert resp.status_code == 200
    assert resp.json()["access_token"] == "access-secret"
    assert resp.json()["refresh_token"] == "refresh-secret"
    assert resp.headers.get("cache-control") == "no-store"
    assert resp.headers.get("pragma") == "no-cache"


def test_authenticate_token_response_is_not_cacheable(client):
    """POST /authenticate must also send no-store (RFC 6749 §5.1 MUST)."""
    with patch.object(
        auth_app, "get_oidc_client", new=AsyncMock(return_value=_mock_oidc_client())
    ):
        resp = client.post(
            "/authenticate",
            json={"code": "abc", "redirect_uri": "http://localhost:8084/auth/callback"},
        )

    assert resp.status_code == 200
    assert resp.json()["refresh_token"] == "refresh-secret"
    assert resp.headers.get("cache-control") == "no-store"
    assert resp.headers.get("pragma") == "no-cache"
