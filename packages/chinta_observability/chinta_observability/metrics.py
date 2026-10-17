from __future__ import annotations

import time
from typing import Callable

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests processed",
    ("service", "method", "route", "status"),
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ("service", "method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

SERVICE_UP = Gauge(
    "service_up",
    "1 while the process is serving traffic",
    ("service",),
)

_QUIET_PATHS = frozenset({"/health", "/metrics"})
# Unmatched / pre-routing failures must not use the raw URL path as a label —
# clients can mint unbounded paths (e.g. /api/notes/{id}) and OOM the process.
_UNMATCHED_ROUTE = "unmatched"


def metrics_route_label(request: Request) -> str:
    """Low-cardinality route template for Prometheus labels.

    Prefer the matched FastAPI/Starlette route path (``/notes/{note_id}``,
    ``/api/{path:path}``) over ``request.url.path``. Using the raw path makes
    every note id (and every 404 probe) a permanent in-process time series.
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None) if route is not None else None
    if isinstance(template, str) and template:
        return template
    return _UNMATCHED_ROUTE


def record_http_request(
    service_name: str,
    method: str,
    route: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    status = str(status_code)
    HTTP_REQUESTS_TOTAL.labels(service=service_name, method=method, route=route, status=status).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(service=service_name, method=method, route=route).observe(
        duration_seconds
    )


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, service_name: str) -> None:
        super().__init__(app)
        self._service_name = service_name

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in _QUIET_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            record_http_request(
                self._service_name,
                request.method,
                metrics_route_label(request),
                500,
                time.perf_counter() - start,
            )
            raise
        record_http_request(
            self._service_name,
            request.method,
            metrics_route_label(request),
            status_code,
            time.perf_counter() - start,
        )
        return response


def install_metrics(app, service_name: str) -> None:
    """Expose Prometheus metrics and instrument HTTP handlers."""
    SERVICE_UP.labels(service=service_name).set(1)
    app.add_middleware(RequestMetricsMiddleware, service_name=service_name)

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
