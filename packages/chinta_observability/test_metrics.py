from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from chinta_observability import install_metrics, install_request_logging


def _counter_routes_for_service(service: str) -> set[str]:
    routes: set[str] = set()
    for metric in REGISTRY.collect():
        if metric.name != "http_requests":
            continue
        for sample in metric.samples:
            if sample.name != "http_requests_total":
                continue
            if sample.labels.get("service") == service:
                routes.add(sample.labels["route"])
    return routes


def test_metrics_endpoint_exposes_http_counters():
    app = FastAPI()
    install_request_logging(app, "test-service")
    install_metrics(app, "test-service")

    @app.get("/hello")
    async def hello():
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/hello").status_code == 200

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    body = metrics.text
    assert "http_requests_total" in body
    assert "service_up" in body
    assert 'service="test-service"' in body


def test_metrics_use_route_template_not_raw_path():
    """Note ids / catch-all segments must not create unbounded Prometheus labels."""
    service = "cardinality-guard"
    # Drop leftover children from prior tests for this service name if any.
    before = _counter_routes_for_service(service)

    app = FastAPI()
    install_metrics(app, service)

    @app.get("/notes/{note_id}")
    async def get_note(note_id: int):
        return {"id": note_id}

    @app.api_route("/api/{path:path}", methods=["GET"])
    async def proxy_api(path: str):
        return {"path": path}

    client = TestClient(app)
    assert client.get("/notes/1").status_code == 200
    assert client.get("/notes/2").status_code == 200
    assert client.get("/notes/99999").status_code == 200
    assert client.get("/api/notes/1").status_code == 200
    assert client.get("/api/notes/2").status_code == 200
    assert client.get("/no-such-path-aaaa").status_code == 404
    assert client.get("/no-such-path-bbbb").status_code == 404

    routes = _counter_routes_for_service(service) - before
    assert "/notes/{note_id}" in routes
    assert "/api/{path:path}" in routes
    assert "unmatched" in routes
    # Raw paths must never appear as label values.
    assert "/notes/1" not in routes
    assert "/notes/2" not in routes
    assert "/api/notes/1" not in routes
    assert "/no-such-path-aaaa" not in routes
    assert len(routes) == 3
