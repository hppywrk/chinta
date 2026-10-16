"""CI stub userinfo (unsigned JWT) for compose functional tests."""
from __future__ import annotations

import base64
import json

import pytest
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
    monkeypatch.setenv("OIDC_CLIENT_ID", "ci")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "ci")
    monkeypatch.setenv("OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("CHINTA_AUTH_CI_STUB", "1")
    auth_app._oidc_metadata = {
        "authorization_endpoint": "https://idp.example/authorize",
        "token_endpoint": "https://idp.example/token",
        "userinfo_endpoint": "https://idp.example/userinfo",
    }
    yield TestClient(auth_app.app)
    auth_app._oidc_metadata = None


def test_ci_stub_userinfo_returns_sub_without_idp_call(client):
    token = _jwt_with_claims({"sub": "local-demo-sub", "aud": "ci"})
    resp = client.get("/userinfo", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"sub": "local-demo-sub"}


def test_ci_stub_disabled_calls_idp_path(client, monkeypatch):
    monkeypatch.delenv("CHINTA_AUTH_CI_STUB", raising=False)
    token = _jwt_with_claims({"sub": "local-demo-sub", "aud": "ci"})
    resp = client.get("/userinfo", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
