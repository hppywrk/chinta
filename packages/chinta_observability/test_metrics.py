from fastapi import FastAPI
from fastapi.testclient import TestClient

from chinta_observability import install_metrics, install_request_logging


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
