from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from chinta_observability.context import set_request_id

_REQUEST_ID_HEADER = "x-request-id"
_ACCESS_LOGGER = logging.getLogger("chinta.http.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, service_name: str) -> None:
        super().__init__(app)
        self._service_name = service_name

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        incoming = request.headers.get(_REQUEST_ID_HEADER)
        request_id = incoming.strip() if incoming else str(uuid.uuid4())
        set_request_id(request_id)
        request.state.request_id = request_id

        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            duration_ms = int((time.perf_counter() - start) * 1000)
            _ACCESS_LOGGER.exception(
                "request failed",
                extra={
                    "event": "http.request.completed",
                    "service": self._service_name,
                    "request_id": request_id,
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_status": 500,
                    "duration_ms": duration_ms,
                },
            )
            set_request_id(None)
            raise

        duration_ms = int((time.perf_counter() - start) * 1000)
        response.headers[_REQUEST_ID_HEADER] = request_id
        if request.url.path != "/health":
            _ACCESS_LOGGER.info(
                "request completed",
                extra={
                    "event": "http.request.completed",
                    "service": self._service_name,
                    "request_id": request_id,
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_status": status_code,
                    "duration_ms": duration_ms,
                },
            )
        set_request_id(None)
        return response


def install_request_logging(app, service_name: str) -> None:
    """Attach JSON-friendly access logging and X-Request-Id propagation."""
    app.add_middleware(RequestLoggingMiddleware, service_name=service_name)
