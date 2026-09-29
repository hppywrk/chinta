import os

from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_create_user_requires_admin_token(monkeypatch):
    monkeypatch.setenv("CHINTA_PLATFORM_ADMIN_TOKEN", "secret")
    monkeypatch.setenv(
        "CHINTA_PLATFORM_DATABASE_URL",
        "postgresql://chinta_user:chinta_password@localhost:5432/chinta",
    )
    resp = client.post("/v1/users", json={"email": "a@example.com"})
    assert resp.status_code == 401

    resp = client.post(
        "/v1/users",
        json={"email": "a@example.com"},
        headers={"Authorization": "Bearer secret"},
    )
    # May be 503 if DB/schema missing in CI; must not be 401.
    assert resp.status_code != 401
