"""Regression tests for gateway /api upstream response forwarding.

Re-parsing via resp.json()/JSONResponse crashed on empty application/json
bodies and corrupted non-JSON payloads (e.g. PDF → JSON string).
"""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
import uvicorn


class _BackendHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/empty-json"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if self.path.startswith("/file.pdf"):
            data = b"%PDF-1.4 binary-payload"
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if self.path.startswith("/mixed-case-json"):
            body = b'{"a":1}'
            self.send_response(200)
            self.send_header("Content-Type", "Application/JSON")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A003
        return


@pytest.fixture(scope="module")
def gateway_url():
    upstream = HTTPServer(("127.0.0.1", 0), _BackendHandler)
    upstream_port = upstream.server_address[1]
    threading.Thread(target=upstream.serve_forever, daemon=True).start()

    import app as gateway_app

    gateway_app.BACKEND_URL = f"http://127.0.0.1:{upstream_port}"

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
            if httpx.get(f"{url}/health", timeout=0.2).status_code == 200:
                break
        except Exception:
            time.sleep(0.05)
    else:
        server.should_exit = True
        upstream.shutdown()
        raise RuntimeError("gateway failed to start")

    yield url
    server.should_exit = True
    upstream.shutdown()


def test_proxy_api_empty_json_does_not_crash(gateway_url):
    with httpx.Client() as client:
        resp = client.get(
            f"{gateway_url}/api/empty-json",
            headers={"Authorization": "Bearer test-token"},
            timeout=5.0,
        )
    assert resp.status_code == 200, resp.text
    assert resp.content == b""


def test_proxy_api_forwards_binary_unchanged(gateway_url):
    with httpx.Client() as client:
        resp = client.get(
            f"{gateway_url}/api/file.pdf",
            headers={"Authorization": "Bearer test-token"},
            timeout=5.0,
        )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("content-type", "").startswith("application/pdf")
    assert resp.content == b"%PDF-1.4 binary-payload"


def test_proxy_api_preserves_mixed_case_json_bytes(gateway_url):
    with httpx.Client() as client:
        resp = client.get(
            f"{gateway_url}/api/mixed-case-json",
            headers={"Authorization": "Bearer test-token"},
            timeout=5.0,
        )
    assert resp.status_code == 200, resp.text
    assert resp.content == b'{"a":1}'
    assert resp.json() == {"a": 1}
