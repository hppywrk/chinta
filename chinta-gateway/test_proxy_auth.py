"""Regression tests for gateway /auth blind proxy response forwarding.

Uses a real HTTP upstream so Content-Encoding / Content-Length framing is
exercised (ASGI transports hide this class of failure).
"""
from __future__ import annotations

import gzip
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
import uvicorn


class _GzipAuthHandler(BaseHTTPRequestHandler):
    """Auth upstream that returns gzip-compressed JSON (common behind nginx)."""

    def do_GET(self):  # noqa: N802
        raw = b'{"authorize_url":"https://idp.example/authorize","state":"abc123"}'
        body = gzip.compress(raw)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A003
        return


@pytest.fixture(scope="module")
def gateway_url():
    upstream = HTTPServer(("127.0.0.1", 0), _GzipAuthHandler)
    upstream_port = upstream.server_address[1]
    threading.Thread(target=upstream.serve_forever, daemon=True).start()

    import app as gateway_app

    gateway_app.AUTH_BASE_URL = f"http://127.0.0.1:{upstream_port}"

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


def test_proxy_auth_survives_gzip_upstream(gateway_url):
    """httpx decompresses gzip but keeps upstream Content-Length; must not forward it."""
    with httpx.Client() as client:
        resp = client.get(f"{gateway_url}/auth/authorize", timeout=5.0)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "authorize_url": "https://idp.example/authorize",
        "state": "abc123",
    }
    assert "content-encoding" not in resp.headers
