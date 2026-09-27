"""Regression tests for GET /userinfo bearer forwarding.

Authlib's httpx AsyncOAuth2Client.get() does not accept token=; the access
token must be set on client.token (or sent as an Authorization header).
"""
from __future__ import annotations

import httpx
import pytest
from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi.testclient import TestClient

import app as auth_app


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


def test_userinfo_sends_bearer_via_client_token(client, monkeypatch):
    """ /userinfo must not pass token= into AsyncOAuth2Client.get (TypeError). """
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"sub": "user-1", "email": "user@example.com"},
        )

    transport = httpx.MockTransport(handler)

    async def fake_get_oidc_client(redirect_uri: str | None = None):
        oauth = AsyncOAuth2Client(
            client_id="test-client",
            client_secret="test-secret",
            transport=transport,
        )
        oauth.userinfo_endpoint = "https://idp.example/userinfo"
        return oauth

    monkeypatch.setattr(auth_app, "get_oidc_client", fake_get_oidc_client)

    resp = client.get(
        "/userinfo",
        headers={"Authorization": "Bearer access-token-123"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"sub": "user-1", "email": "user@example.com"}
    assert seen["url"] == "https://idp.example/userinfo"
    assert seen["authorization"] == "Bearer access-token-123"


def test_userinfo_requires_bearer(client):
    resp = client.get("/userinfo")
    assert resp.status_code == 401
