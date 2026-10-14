from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

from chinta_observability.context import get_request_id, get_service_name, set_service_name


class _ChintaJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "service": getattr(record, "service", None) or get_service_name() or "unknown",
            "msg": record.getMessage(),
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
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True

    logger = logging.getLogger(service_name)
    logger.setLevel(level)
    return logger
