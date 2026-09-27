"""Shared test helpers for gateway integration tests."""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class AuthStubHandler(BaseHTTPRequestHandler):
    """Minimal auth /userinfo stub for /api tests that validate Bearer tokens."""

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/userinfo"):
            auth = self.headers.get("Authorization", "")
            if auth in ("Bearer good-token", "Bearer test-token"):
                body = b'{"sub":"test-user"}'
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


def start_auth_stub() -> tuple[HTTPServer, str]:
    auth = HTTPServer(("127.0.0.1", 0), AuthStubHandler)
    threading.Thread(target=auth.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{auth.server_address[1]}"
    return auth, base
