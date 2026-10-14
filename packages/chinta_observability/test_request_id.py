import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chinta_observability import configure_logging, install_request_logging


@pytest.fixture()
def json_logs(caplog, monkeypatch):
    monkeypatch.setenv("CHINTA_LOG_FORMAT", "json")
    configure_logging("test-service")
    caplog.set_level(logging.INFO)
    with caplog.at_level(logging.INFO):
        yield caplog


def test_request_id_propagates_in_json_logs(json_logs):
    app = FastAPI()
    install_request_logging(app, "test-service")

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/ping", headers={"X-Request-Id": "req-test-123"})
    assert response.status_code == 200
    assert response.headers.get("x-request-id") == "req-test-123"

    completed = [
        r
        for r in json_logs.records
        if getattr(r, "event", None) == "http.request.completed"
    ]
    assert completed, "expected http.request.completed log record"
    record = completed[0]
    assert record.request_id == "req-test-123"

    formatter = logging.getLogger().handlers[0].formatter
    line = formatter.format(record)
    payload = json.loads(line)
    assert payload["request_id"] == "req-test-123"
    assert payload["event"] == "http.request.completed"
    assert payload["service"] == "test-service"
