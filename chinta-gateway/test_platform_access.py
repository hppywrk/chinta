"""Gateway + chinta-platform access resolve integration."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
import uvicorn

from conftest import start_auth_stub


class _PlatformHandler(BaseHTTPRequestHandler):
    last_resolve: dict | None = None

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if self.path == "/v1/access/resolve":
            _PlatformHandler.last_resolve = json.loads(body.decode())
            payload = {
                "allowed": True,
                "deny_reason": None,
                "tenant_id": "00000000-0000-4000-8000-000000000001",
                "tenant_status": "ACTIVE_SHARED",
                "schema_name": "t_abc123",
                "role_code": "member",
            }
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A003
        return


class _BackendHandler(BaseHTTPRequestHandler):
    last_headers: dict[str, str] | None = None

    def do_GET(self):  # noqa: N802
        _BackendHandler.last_headers = {k: v for k, v in self.headers.items()}
        body = b"[]"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A003
        return


@pytest.fixture(scope="module")
def gateway_with_platform():
    auth, auth_base = start_auth_stub()
    platform = HTTPServer(("127.0.0.1", 0), _PlatformHandler)
    platform_base = f"http://127.0.0.1:{platform.server_address[1]}"
    threading.Thread(target=platform.serve_forever, daemon=True).start()

    backend = HTTPServer(("127.0.0.1", 0), _BackendHandler)
    threading.Thread(target=backend.serve_forever, daemon=True).start()

    import app as gateway_app

    gateway_app.AUTH_BASE_URL = auth_base
    gateway_app.BACKEND_URL = f"http://127.0.0.1:{backend.server_address[1]}"
    gateway_app.PLATFORM_BASE_URL = platform_base

    probe = HTTPServer(("127.0.0.1", 0), None)
    port = probe.server_address[1]
    probe.server_close()

    config = uvicorn.Config(gateway_app.app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()

    url = f"http://127.0.0.1:{port}"
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
    platform.shutdown()
    backend.shutdown()
    gateway_app.PLATFORM_BASE_URL = ""


def test_platform_resolve_injects_schema_headers(gateway_with_platform):
    _PlatformHandler.last_resolve = None
    _BackendHandler.last_headers = None
    resp = httpx.get(
        f"{gateway_with_platform}/api/notes",
        headers={
            "Authorization": "Bearer test-token",
            "X-Tenant-Id": "demo",
            "X-Tenant-Schema": "t_evil",
        },
        timeout=5,
    )
    assert resp.status_code == 200
    assert _PlatformHandler.last_resolve == {
        "tenant_slug": "demo",
        "user_external_subject": "test-user",
        "module_code": "notes",
        "operation": "read",
    }
    assert _BackendHandler.last_headers is not None
    assert _BackendHandler.last_headers.get("X-Tenant-Schema") == "t_abc123"
    assert _BackendHandler.last_headers.get("X-Platform-User-Role") == "member"
    assert _BackendHandler.last_headers.get("X-Tenant-Schema") != "t_evil"


def test_platform_enforced_requires_tenant_header(gateway_with_platform):
    resp = httpx.get(
        f"{gateway_with_platform}/api/notes",
        headers={"Authorization": "Bearer test-token"},
        timeout=5,
    )
    assert resp.status_code == 400
