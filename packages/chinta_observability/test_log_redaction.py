"""Secrets in outbound httpx URLs must not appear in configured service logs."""
from __future__ import annotations

import json
import logging

import httpx
import pytest

from chinta_observability.logging_config import (
    _redact_sensitive_query_params,
    configure_logging,
)


def test_redact_sensitive_query_params():
    raw = (
        "HTTP Request: GET https://oauth2.googleapis.com/tokeninfo"
        "?access_token=ya29.SECRET&extra=1"
    )
    assert "ya29.SECRET" not in _redact_sensitive_query_params(raw)
    assert "access_token=***" in _redact_sensitive_query_params(raw)
    assert "code=***" in _redact_sensitive_query_params(
        "GET http://auth/callback?code=oauth-code-value&state=x"
    )


def test_httpx_info_urls_not_emitted_after_configure(monkeypatch, caplog):
    monkeypatch.setenv("CHINTA_LOG_FORMAT", "json")
    monkeypatch.setenv("CHINTA_LOG_LEVEL", "INFO")
    configure_logging("test-service")

    with caplog.at_level(logging.DEBUG):
        httpx.get(
            "https://example.com/tokeninfo",
            params={"access_token": "ya29.SHOULD_NOT_APPEAR"},
            timeout=5.0,
        )

    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "ya29.SHOULD_NOT_APPEAR" not in joined
    # Defense-in-depth: even if a record sneaks through a formatter, redact it.
    formatter = logging.getLogger().handlers[0].formatter
    for record in caplog.records:
        line = formatter.format(record)
        assert "ya29.SHOULD_NOT_APPEAR" not in line
        if "access_token=" in line:
            payload = json.loads(line)
            assert "ya29.SHOULD_NOT_APPEAR" not in payload["msg"]
