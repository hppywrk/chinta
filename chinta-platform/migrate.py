"""Apply idempotent platform DDL so gateway access resolve can succeed."""
from __future__ import annotations

from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
PLATFORM_CORE_SQL = MIGRATIONS_DIR / "001_platform_core.sql"


def apply_platform_migrations(database_url: str) -> None:
    """Create platform.* objects if missing (safe to run on every startup).

    Compose defaults ``CHINTA_PLATFORM_URL`` on the gateway after #27, but
    ``chinta-db/init.sql`` never created platform tables. Without this apply,
    every ``/api/*`` call fails closed with HTTP 503 (PLATFORM_SCHEMA_MISSING).
    """
    if not database_url:
        raise ValueError("database_url is required")
    if not PLATFORM_CORE_SQL.is_file():
        raise FileNotFoundError(f"Missing migration file: {PLATFORM_CORE_SQL}")

    sql = PLATFORM_CORE_SQL.read_text(encoding="utf-8")
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
