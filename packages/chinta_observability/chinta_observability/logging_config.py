from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

from chinta_observability.context import get_request_id, get_service_name, set_service_name

# httpx logs full request URLs at INFO, including query strings. Auth puts Google
# tokeninfo access_token= and gateway OAuth code= in those URLs; never let that
# reach stdout (compose json-file logs, log aggregators).
_SENSITIVE_QUERY_RE = re.compile(
    r"(?i)\b(access_token|refresh_token|id_token|code|client_secret)=([^&\s\"']+)"
)


def _redact_sensitive_query_params(message: str) -> str:
    return _SENSITIVE_QUERY_RE.sub(r"\1=***", message)


class _ChintaJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "service": getattr(record, "service", None) or get_service_name() or "unknown",
            "msg": _redact_sensitive_query_params(record.getMessage()),
            "event": getattr(record, "event", None) or "log",
        }
        request_id = getattr(record, "request_id", None) or get_request_id()
        if request_id:
            payload["request_id"] = request_id
        for key in ("duration_ms", "http_method", "http_path", "http_status"):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class _ChintaTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        original = record.msg
        try:
            if isinstance(record.msg, str):
                record.msg = _redact_sensitive_query_params(record.msg)
            return super().format(record)
        finally:
            record.msg = original


class _ChintaContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "service", None):
            record.service = get_service_name()
        if not getattr(record, "request_id", None):
            record.request_id = get_request_id()
        return True


def configure_logging(service_name: str) -> logging.Logger:
    """
    Configure process-wide logging for a Chinta service.

    Env:
      CHINTA_LOG_FORMAT=json|text (default text)
      CHINTA_LOG_LEVEL=DEBUG|INFO|... (default INFO)
    """
    set_service_name(service_name)
    log_format = os.environ.get("CHINTA_LOG_FORMAT", "text").strip().lower()
    level_name = os.environ.get("CHINTA_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_ChintaContextFilter())
    if log_format == "json":
        handler.setFormatter(_ChintaJsonFormatter())
    else:
        handler.setFormatter(
            _ChintaTextFormatter(
                fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
    root.addHandler(handler)
    root.setLevel(level)

    # Access lines come from RequestLoggingMiddleware (path only, no query).
    # uvicorn.access includes ?code= / other secrets — keep it quiet.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # httpx INFO is "HTTP Request: GET url?access_token=..." — drop to WARNING.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)

    logger = logging.getLogger(service_name)
    logger.setLevel(level)
    return logger
