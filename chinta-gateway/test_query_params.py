"""Repeated query keys must be forwarded intact by gateway proxies."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

import app as gateway_app


@pytest.fixture
def client():
    return TestClient(gateway_app.app)


def _mock_httpx_client(capture: dict):
    mock_resp = MagicMock()
    mock_resp.content = b'{"ok":true}'
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.text = '{"ok":true}'
    mock_resp.json.return_value = {"ok": True}

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_resp)

    def _capture(*args, **kwargs):
        capture["args"] = args
        capture["kwargs"] = kwargs
        return mock_resp

    mock_client.request.side_effect = _capture

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def test_proxy_api_preserves_repeated_query_keys(client):
    """DELETE/filter APIs often use ?id=1&id=2; dict() would drop all but the last."""
    capture = {}
    with patch.object(httpx, "AsyncClient", return_value=_mock_httpx_client(capture)):
        resp = client.delete(
            "/api/items",
            params=[("id", "1"), ("id", "2"), ("id", "3")],
            headers={"Authorization": "Bearer test-token"},
        )

    assert resp.status_code == 200
    forwarded = capture["kwargs"]["params"]
    assert forwarded == [("id", "1"), ("id", "2"), ("id", "3")]


def test_proxy_api_preserves_repeated_filter_tags(client):
    capture = {}
    with patch.object(httpx, "AsyncClient", return_value=_mock_httpx_client(capture)):
        resp = client.get(
            "/api/search",
            params=[("tag", "work"), ("tag", "urgent")],
            headers={"Authorization": "Bearer test-token"},
        )

    assert resp.status_code == 200
    assert capture["kwargs"]["params"] == [("tag", "work"), ("tag", "urgent")]


def test_proxy_auth_preserves_repeated_query_keys(client):
    capture = {}
    with patch.object(httpx, "AsyncClient", return_value=_mock_httpx_client(capture)):
        resp = client.get(
            "/auth/authorize",
            params=[("scope", "openid"), ("scope", "email")],
        )

    assert resp.status_code == 200
    assert capture["kwargs"]["params"] == [("scope", "openid"), ("scope", "email")]
