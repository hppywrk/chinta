"""Notes API and tenant isolation tests (requires PostgreSQL)."""
from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from fastapi.testclient import TestClient

from app import app
from config import get_config
from db import NotesStore, tenant_schema_name


class _AuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/userinfo"):
            auth = self.headers.get("Authorization", "")
            if auth == "Bearer good-token":
                body = b'{"sub":"alice"}'
                status = 200
            elif auth == "Bearer bob-token":
                body = b'{"sub":"bob"}'
                status = 200
            else:
                body = b'{"error":"invalid_token"}'
                status = 401
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A003
        return


def _postgres_store() -> NotesStore | None:
    url = os.environ.get("TEST_DATABASE_URL") or get_config()["database_url"]
    store = NotesStore(url)
    try:
        store.list_notes("connectivity-check", "nobody")
    except Exception:
        return None
    return store


@pytest.fixture(scope="module")
def auth_stub():
    server = HTTPServer(("127.0.0.1", 0), _AuthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base
    server.shutdown()


@pytest.fixture(scope="module")
def store():
    s = _postgres_store()
    if s is None:
        pytest.skip("PostgreSQL is not available for integration tests")
    return s


@pytest.fixture
def client(auth_stub, store, monkeypatch):
    import app as chinta_app

    monkeypatch.setattr(chinta_app, "_auth_url", auth_stub)
    monkeypatch.setattr(chinta_app, "_store", store)
    return TestClient(chinta_app.app)


def _headers(tenant: str, token: str = "good-token") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": tenant,
    }


def test_tenant_schema_name():
    # Hash-based names: distinct ids must not share a schema (see test_db_unit).
    assert tenant_schema_name("acme-corp") != tenant_schema_name("acme_corp")
    assert tenant_schema_name("acme-corp").startswith("t_")
    assert len(tenant_schema_name("acme-corp")) <= 63


def test_notes_crud_and_tenant_isolation(client, store):
    tenant_a = "test-tenant-a"
    tenant_b = "test-tenant-b"

    r = client.post("/notes", json={"body": "hello"}, headers=_headers(tenant_a))
    assert r.status_code == 201
    note_id = r.json()["id"]
    assert r.json()["body"] == "hello"
    assert "modified_at" in r.json()

    r = client.get("/notes", headers=_headers(tenant_a))
    assert r.status_code == 200
    assert len(r.json()) >= 1

    r = client.put(
        f"/notes/{note_id}",
        json={"body": "updated"},
        headers=_headers(tenant_a),
    )
    assert r.status_code == 200
    assert r.json()["body"] == "updated"

    r = client.get("/notes", headers=_headers(tenant_b))
    assert r.status_code == 200
    assert all(n["id"] != note_id for n in r.json())

    r = client.delete(f"/notes/{note_id}", headers=_headers(tenant_a))
    assert r.status_code == 204

    r = client.put(
        f"/notes/{note_id}",
        json={"body": "nope"},
        headers=_headers(tenant_a),
    )
    assert r.status_code == 404


def test_normalized_tenant_ids_do_not_share_notes(client):
    """acme-corp / acme.corp / acme_corp must not share a schema or notes."""
    r = client.post(
        "/notes",
        json={"body": "only-hyphen-tenant"},
        headers=_headers("acme-corp"),
    )
    assert r.status_code == 201
    note_id = r.json()["id"]

    for other in ("acme.corp", "acme_corp"):
        r = client.get("/notes", headers=_headers(other))
        assert r.status_code == 200
        assert all(n["id"] != note_id for n in r.json())
        assert all(n["body"] != "only-hyphen-tenant" for n in r.json())

    r = client.get("/notes", headers=_headers("acme-corp"))
    assert r.status_code == 200
    assert any(n["id"] == note_id for n in r.json())


def test_requires_tenant_header(client):
    r = client.get("/notes", headers={"Authorization": "Bearer good-token"})
    assert r.status_code == 400


def test_requires_valid_token(client):
    r = client.get("/notes", headers=_headers("t1", token="bad"))
    assert r.status_code == 401


def test_rejects_spoofed_tenant_schema_header(client):
    """Direct backend callers must not target another tenant's schema via header."""
    headers = {
        **_headers("acme"),
        "X-Tenant-Schema": tenant_schema_name("other-tenant"),
    }
    r = client.post("/notes", json={"body": "cross-tenant"}, headers=headers)
    assert r.status_code == 400


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
