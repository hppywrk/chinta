"""Runtime configuration from environment."""
from __future__ import annotations

import os


def get_config() -> dict[str, str]:
    host = os.environ.get("CHINTA_DB_HOST", "localhost")
    port = os.environ.get("CHINTA_DB_PORT", "5432")
    dbname = os.environ.get("CHINTA_DB_NAME", "chinta")
    user = os.environ.get("CHINTA_DB_USER", "chinta_user")
    password = os.environ.get("CHINTA_DB_PASSWORD", "chinta_password")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        database_url = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

    enforce = os.environ.get("CHINTA_ENFORCE_PLATFORM", "").strip().lower()
    enforce_platform = enforce in ("1", "true", "yes", "on")

    return {
        "database_url": database_url,
        "auth_url": os.environ.get("CHINTA_AUTH_URL", "http://chinta-auth:8083").rstrip("/"),
        "enforce_platform": enforce_platform,
    }
