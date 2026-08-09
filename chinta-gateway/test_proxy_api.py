"""Regression tests for gateway /api proxy body forwarding.

Uses a real HTTP backend so httpx/h11 Content-Length framing is exercised
(ASGI transports hide this class of failure).
"""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
import uvicorn


class _BackendHandler(BaseHTTPRequestHandler):
    last_body: bytes | None = None

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        _BackendHandler.last_body = self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, format, *args):  # noqa: A003
        return


@pytest.fixture(scope="module")
def gateway_url():
    backend = HTTPServer(("127.0.0.1", 0), _BackendHandler)
    backend_port = backend.server_address[1]
    threading.Thread(target=backend.serve_forever, daemon=True).start()

    import app as gateway_app

    gateway_app.BACKEND_URL = f"http://127.0.0.1:{backend_port}"

    gateway = HTTPServer(("127.0.0.1", 0), None)  # just to allocate a port
    gateway_port = gateway.server_address[1]
    gateway.server_close()

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
        backend.shutdown()
        raise RuntimeError("gateway failed to start")

    yield url
    server.should_exit = True
    backend.shutdown()


@pytest.mark.parametrize(
    "raw_body",
    [
        b'{"title":"hi","body":"x"}',  # compact
        b'{\n  "title": "hi",\n  "body": "x"\n}',  # pretty-printed
        b'{ "title": "hi", "body": "x" }',  # spaced
        b'{"title":"caf\\u00e9"}',  # unicode-escaped
    ],
)
def test_proxy_api_forwards_json_bodies_without_500(gateway_url, raw_body):
    _BackendHandler.last_body = None
    with httpx.Client() as client:
        resp = client.post(
            f"{gateway_url}/api/items",
            content=raw_body,
            headers={
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json",
            },
            timeout=5.0,
        )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}
    assert _BackendHandler.last_body == raw_body


def test_proxy_api_requires_bearer(gateway_url):
    with httpx.Client() as client:
        resp = client.post(
            f"{gateway_url}/api/items",
            content=b'{"title":"hi"}',
            headers={"Content-Type": "application/json"},
            timeout=5.0,
        )
    assert resp.status_code == 401
