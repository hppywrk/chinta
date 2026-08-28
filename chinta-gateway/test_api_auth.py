"""Regression tests: /api must validate Bearer tokens via auth /userinfo.

Previously get_access_token only checked that a Bearer string was present, so
Authorization: Bearer totally-fake was proxied to the backend (auth bypass).
"""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
import uvicorn


class _AuthHandler(BaseHTTPRequestHandler):
    """Minimal auth stub: 200 only for Bearer good-token."""

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/userinfo"):
            auth = self.headers.get("Authorization", "")
            if auth == "Bearer good-token":
                body = b'{"sub":"user-1"}'
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


class _BackendHandler(BaseHTTPRequestHandler):
    hits: list[dict] = []

    def do_GET(self):  # noqa: N802
        _BackendHandler.hits.append(
            {
                "path": self.path,
                "auth": self.headers.get("Authorization"),
            }
        )
        body = b'{"secret":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A003
        return


@pytest.fixture(scope="module")
def gateway_url():
    auth = HTTPServer(("127.0.0.1", 0), _AuthHandler)
    threading.Thread(target=auth.serve_forever, daemon=True).start()

    backend = HTTPServer(("127.0.0.1", 0), _BackendHandler)
    threading.Thread(target=backend.serve_forever, daemon=True).start()

    import app as gateway_app

    gateway_app.AUTH_BASE_URL = f"http://127.0.0.1:{auth.server_address[1]}"
    gateway_app.BACKEND_URL = f"http://127.0.0.1:{backend.server_address[1]}"

    probe = HTTPServer(("127.0.0.1", 0), None)
    gateway_port = probe.server_address[1]
    probe.server_close()

    config = uvicorn.Config(
        gateway_app.app,
        host="127.0.0.1",
        port=gateway_port,
        log_level="error",
    )
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()

    url = f"http://127.0.0.1:{gateway_port}"
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            httpx.get(f"{url}/health", timeout=0.2)
            break
        except Exception:
            time.sleep(0.05)
    yield url

    server.should_exit = True
    auth.shutdown()
    backend.shutdown()


def test_fake_bearer_is_rejected_and_not_proxied(gateway_url):
    _BackendHandler.hits.clear()
    resp = httpx.get(
        f"{gateway_url}/api/admin/users",
        headers={"Authorization": "Bearer totally-fake"},
        timeout=5,
    )
    assert resp.status_code == 401
    assert _BackendHandler.hits == []


def test_missing_bearer_is_rejected(gateway_url):
    _BackendHandler.hits.clear()
    resp = httpx.get(f"{gateway_url}/api/admin/users", timeout=5)
    assert resp.status_code == 401
    assert _BackendHandler.hits == []


def test_valid_bearer_is_proxied_to_backend(gateway_url):
    _BackendHandler.hits.clear()
    resp = httpx.get(
        f"{gateway_url}/api/admin/users",
        headers={"Authorization": "Bearer good-token"},
        timeout=5,
    )
    assert resp.status_code == 200
    assert resp.json() == {"secret": True}
    assert len(_BackendHandler.hits) == 1
    assert _BackendHandler.hits[0]["path"] == "/admin/users"
    assert _BackendHandler.hits[0]["auth"] == "Bearer good-token"
