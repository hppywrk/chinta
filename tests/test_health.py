"""Health-check tests for all services."""


def test_gateway_health(gateway):
    resp = gateway.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_auth_health(auth):
    resp = auth.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_notebook_health(notebook):
    resp = notebook.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
