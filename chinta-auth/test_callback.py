"""Tests for OIDC callback handling."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app as auth_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OIDC_REDIRECT_URI_BASE", "http://localhost:8084")
    monkeypatch.setenv("OIDC_CLIENT_ID", "test-client")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-secret")
    auth_app._oidc_metadata = {
        "authorization_endpoint": "https://idp.example/authorize",
        "token_endpoint": "https://idp.example/token",
        "userinfo_endpoint": "https://idp.example/userinfo",
    }
    yield TestClient(auth_app.app)
    auth_app._oidc_metadata = None


def test_default_redirect_uri_matches_callback_route(monkeypatch):
    monkeypatch.setenv("OIDC_REDIRECT_URI_BASE", "http://localhost:8084")
    assert auth_app.default_redirect_uri() == "http://localhost:8084/auth/callback"


def test_compose_default_redirect_base_is_gateway_origin():
    """Stock compose must not default the OAuth public origin to auth :8083.

    Browser OAuth hits gateway /auth/callback; IdPs omit redirect_uri on the
    redirect. Auth then uses {OIDC_REDIRECT_URI_BASE}/auth/callback for the
    token exchange — a :8083 default makes that URI disagree with authorize.
    """
    import re
    from pathlib import Path

    compose = Path(__file__).resolve().parents[1] / "docker-compose.yml"
    text = compose.read_text()
    match = re.search(
        r"OIDC_REDIRECT_URI_BASE:\s*\$\{OIDC_REDIRECT_URI_BASE:-(http://[^}]+)\}",
        text,
    )
    assert match is not None, "OIDC_REDIRECT_URI_BASE default missing from compose"
    assert match.group(1) == "http://localhost:8084"
    assert "CHINTA_AUTH_CALLBACK_URL" not in text


def test_callback_without_redirect_uri_uses_configured_default(client):
    """IdP redirects with only code/state; redirect_uri must not be required."""
    token_payload = {
        "access_token": "access-123",
        "token_type": "Bearer",
        "expires_in": 3600,
    }

    mock_oidc = MagicMock()
    mock_oidc.token_endpoint = "https://idp.example/token"
    mock_oidc.fetch_token = AsyncMock(return_value=token_payload)

    with patch.object(auth_app, "get_oidc_client", AsyncMock(return_value=mock_oidc)):
        resp = client.get("/auth/callback", params={"code": "auth-code", "state": "abc"})

    assert resp.status_code == 200
    assert resp.json()["access_token"] == "access-123"
    mock_oidc.fetch_token.assert_awaited_once_with(
        "https://idp.example/token",
        code="auth-code",
        redirect_uri="http://localhost:8084/auth/callback",
    )


def test_callback_explicit_redirect_uri_is_honored(client):
    token_payload = {"access_token": "access-456", "token_type": "Bearer"}
    mock_oidc = MagicMock()
    mock_oidc.token_endpoint = "https://idp.example/token"
    mock_oidc.fetch_token = AsyncMock(return_value=token_payload)

    with patch.object(auth_app, "get_oidc_client", AsyncMock(return_value=mock_oidc)):
        resp = client.get(
            "/auth/callback",
            params={
                "code": "auth-code",
                "redirect_uri": "https://app.example/custom/callback",
            },
        )

    assert resp.status_code == 200
    mock_oidc.fetch_token.assert_awaited_once_with(
        "https://idp.example/token",
        code="auth-code",
        redirect_uri="https://app.example/custom/callback",
    )
