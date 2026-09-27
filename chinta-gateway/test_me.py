"""Regression tests for gateway GET /me userinfo forwarding.

Unconditional resp.json() crashed with JSONDecodeError whenever auth (or a
proxy in front of it) returned HTML/empty bodies — common for 502/503 pages.
"""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
import uvicorn


class _AuthHandler(BaseHTTPRequestHandler):
    mode = "ok"

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/userinfo"):
            if _AuthHandler.mode == "html502":
                body = b"<html>Bad Gateway</html>"
                status = 502
                ctype = "text/html"
            elif _AuthHandler.mode == "empty401":
                body = b""
                status = 401
                ctype = "application/json"
            elif _AuthHandler.mode == "empty200":
                body = b""
                status = 200
                ctype = "application/json"
            else:
                body = b'{"sub":"user-1","email":"a@b.c"}'
                status = 200
                ctype = "application/json"
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)
            return

        if self.path.startswith("/health"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A003
        return


@pytest.fixture(scope="module")
def gateway_url():
    auth = HTTPServer(("127.0.0.1", 0), _AuthHandler)
    threading.Thread(target=auth.serve_forever, daemon=True).start()

    import app as gateway_app

    gateway_app.AUTH_BASE_URL = f"http://127.0.0.1:{auth.server_address[1]}"

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
        auth.shutdown()
        raise RuntimeError("gateway failed to start")

    yield url
    server.should_exit = True
    auth.shutdown()


def test_me_html_upstream_error_preserves_status(gateway_url):
    _AuthHandler.mode = "html502"
    with httpx.Client() as client:
        resp = client.get(
            f"{gateway_url}/me",
            headers={"Authorization": "Bearer test-token"},
            timeout=5.0,
        )
    assert resp.status_code == 502, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "auth_upstream_error"
    assert "Bad Gateway" in detail["error_description"]


def test_me_empty_json_error_preserves_status(gateway_url):
    _AuthHandler.mode = "empty401"
    with httpx.Client() as client:
        resp = client.get(
            f"{gateway_url}/me",
            headers={"Authorization": "Bearer test-token"},
            timeout=5.0,
        )
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"]["error"] == "auth_upstream_error"


def test_me_empty_json_success_returns_502(gateway_url):
    _AuthHandler.mode = "empty200"
    with httpx.Client() as client:
        resp = client.get(
            f"{gateway_url}/me",
            headers={"Authorization": "Bearer test-token"},
            timeout=5.0,
        )
    assert resp.status_code == 502, resp.text
    assert resp.json()["detail"]["error"] == "invalid_userinfo_response"


def test_me_forwards_valid_userinfo(gateway_url):
    _AuthHandler.mode = "ok"
    with httpx.Client() as client:
        resp = client.get(
            f"{gateway_url}/me",
            headers={"Authorization": "Bearer test-token"},
            timeout=5.0,
        )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"sub": "user-1", "email": "a@b.c"}
