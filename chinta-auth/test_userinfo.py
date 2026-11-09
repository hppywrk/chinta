"""Regression tests for GET /userinfo bearer forwarding and audience checks.

Authlib's httpx AsyncOAuth2Client.get() does not accept token=; the access
token must be set on client.token (or sent as an Authorization header).
"""
from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest
from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi import HTTPException
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


def test_audiences_from_claims_reads_google_tokeninfo_fields():
    """Google access-token tokeninfo uses audience/issued_to, not aud/azp."""
    assert auth_app.audiences_from_claims(
        {
            "issued_to": "client.apps.googleusercontent.com",
            "audience": "client.apps.googleusercontent.com",
            "scope": "openid email profile",
            "expires_in": 3600,
        }
    ) == {"client.apps.googleusercontent.com"}


def test_assert_audience_accepts_google_tokeninfo_fields(monkeypatch):
    """Google opaque tokens: tokeninfo audience/issued_to must satisfy the check."""
    monkeypatch.setenv("OIDC_CLIENT_ID", "test-client")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("OIDC_ISSUER", "https://accounts.google.com")
    auth_app._oidc_metadata = {
        "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_endpoint": "https://oauth2.googleapis.com/token",
        "userinfo_endpoint": "https://openidconnect.googleapis.com/v1/userinfo",
    }

    opaque_token = "ya29.opaque-google-access-token"
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        assert "oauth2.googleapis.com/tokeninfo" in str(request.url)
        assert request.url.params.get("access_token") == opaque_token
        return httpx.Response(
            200,
            json={
                "issued_to": "test-client",
                "audience": "test-client",
                "user_id": "user-1",
                "scope": "openid email profile",
                "expires_in": 3500,
            },
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def async_client_with_transport(*args, **kwargs):
        kwargs.setdefault("transport", transport)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(auth_app.httpx, "AsyncClient", async_client_with_transport)

    asyncio.run(auth_app.assert_access_token_audience(opaque_token))
    assert "tokeninfo" in seen["url"]


def test_assert_audience_rejects_google_tokeninfo_foreign_client(monkeypatch):
    monkeypatch.setenv("OIDC_CLIENT_ID", "test-client")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("OIDC_ISSUER", "https://accounts.google.com")
    auth_app._oidc_metadata = {
        "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_endpoint": "https://oauth2.googleapis.com/token",
        "userinfo_endpoint": "https://openidconnect.googleapis.com/v1/userinfo",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "issued_to": "other-app-client",
                "audience": "other-app-client",
                "expires_in": 3500,
            },
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def async_client_with_transport(*args, **kwargs):
        kwargs.setdefault("transport", transport)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(auth_app.httpx, "AsyncClient", async_client_with_transport)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(auth_app.assert_access_token_audience("ya29.other-app-token"))
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"] == "invalid_token_audience"
