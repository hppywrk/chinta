"""Functional tests for the auth service."""


def test_authorize_url(auth):
    resp = auth.get(
        "/auth/authorize",
        params={"redirect_uri": "http://localhost:8084/auth/callback"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "authorize_url" in data
    assert "state" in data
    assert "accounts.google.com" in data["authorize_url"]


def test_authorize_via_gateway(gateway):
    resp = gateway.get(
        "/auth/authorize",
        params={"redirect_uri": "http://localhost:8084/auth/callback"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "authorize_url" in data


def test_openapi_yaml(auth):
    resp = auth.get("/openapi.yaml")
    assert resp.status_code == 200
    assert "openapi" in resp.text
