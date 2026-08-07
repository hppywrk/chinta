"""Structured JSON logging setup shared across services."""
import logging
import sys

from pythonjsonlogger.json import JsonFormatter


def setup_logging(level: str = "INFO"):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter(
            fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level"},
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
