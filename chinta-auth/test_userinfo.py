"""Regression tests for GET /userinfo bearer forwarding and audience checks.

Authlib's httpx AsyncOAuth2Client.get() does not accept token=; the access
token must be set on client.token (or sent as an Authorization header).
"""
from __future__ import annotations

import base64
import json

import httpx
import pytest
from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi.testclient import TestClient

import app as auth_app


def _jwt_with_claims(claims: dict) -> str:
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload = b64(json.dumps(claims).encode())
    return f"{header}.{payload}.sig"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OIDC_CLIENT_ID", "test-client")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-secret")
    # Non-Google issuer so audience checks use JWT claims (no live tokeninfo).
    monkeypatch.setenv("OIDC_ISSUER", "https://idp.example")
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
    access_token = _jwt_with_claims({"sub": "user-1", "aud": "test-client"})

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
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"sub": "user-1", "email": "user@example.com"}
    assert seen["url"] == "https://idp.example/userinfo"
    assert seen["authorization"] == f"Bearer {access_token}"


def test_userinfo_requires_bearer(client):
    resp = client.get("/userinfo")
    assert resp.status_code == 401


def test_userinfo_rejects_foreign_client_audience(client, monkeypatch):
    """Access tokens minted for another OAuth client must not authenticate here."""
    access_token = _jwt_with_claims({"sub": "user-1", "azp": "other-app-client"})

    async def fake_get_oidc_client(redirect_uri: str | None = None):
        raise AssertionError("userinfo must not call IdP after audience rejection")

    monkeypatch.setattr(auth_app, "get_oidc_client", fake_get_oidc_client)

    resp = client.get(
        "/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "invalid_token_audience"


def test_userinfo_closes_oidc_client(client, monkeypatch):
    """Every /userinfo must aclose the Authlib httpx client (FD leak otherwise)."""
    closed = {"n": 0}
    access_token = _jwt_with_claims({"sub": "user-1", "aud": "test-client"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sub": "user-1"})

    transport = httpx.MockTransport(handler)

    async def fake_get_oidc_client(redirect_uri: str | None = None):
        oauth = AsyncOAuth2Client(
            client_id="test-client",
            client_secret="test-secret",
            transport=transport,
        )
        oauth.userinfo_endpoint = "https://idp.example/userinfo"
        original = oauth.aclose

        async def tracked_aclose():
            closed["n"] += 1
            await original()

        oauth.aclose = tracked_aclose  # type: ignore[method-assign]
        return oauth

    monkeypatch.setattr(auth_app, "get_oidc_client", fake_get_oidc_client)

    resp = client.get(
        "/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 200
    assert closed["n"] == 1


def test_audiences_from_claims_reads_azp_and_aud_list():
    assert auth_app.audiences_from_claims({"azp": "a", "aud": ["b", "c"]}) == {"a", "b", "c"}
