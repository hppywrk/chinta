from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from chinta_observability import install_metrics, install_request_logging
from chinta_observability.metrics import metrics_method_label


def _counter_methods_for_service(service: str) -> set[str]:
    methods: set[str] = set()
    for metric in REGISTRY.collect():
        if metric.name != "http_requests":
            continue
        for sample in metric.samples:
            if sample.name != "http_requests_total":
                continue
            if sample.labels.get("service") == service:
                methods.add(sample.labels["method"])
    return methods


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


def test_metrics_method_label_allowlist():
    assert metrics_method_label("get") == "GET"
    assert metrics_method_label("POST") == "POST"
    assert metrics_method_label("M0001") == "other"
    assert metrics_method_label("A" * 200) == "other"
    assert metrics_method_label("") == "other"


def test_metrics_collapse_unknown_http_methods():
    """Custom HTTP methods must not create unbounded Prometheus label children."""
    service = "method-cardinality-guard"
    before = _counter_methods_for_service(service)

    app = FastAPI()
    install_metrics(app, service)

    @app.get("/")
    async def root():
        return {"ok": True}

    client = TestClient(app)
    for i in range(20):
        assert client.request(f"M{i:04d}", "/").status_code == 405
    assert client.get("/").status_code == 200

    methods = _counter_methods_for_service(service) - before
    assert "GET" in methods
    assert "other" in methods
    assert "M0000" not in methods
    assert "M0019" not in methods
    assert methods <= {"GET", "other"}
