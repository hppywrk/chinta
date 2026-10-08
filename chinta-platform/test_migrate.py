"""Tests for idempotent platform DDL apply (gateway resolve dependency)."""
from __future__ import annotations

import os
import uuid

import psycopg
import pytest

from migrate import apply_platform_migrations


def _database_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("CHINTA_PLATFORM_DATABASE_URL")


@pytest.fixture
def database_url() -> str:
    url = _database_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL / CHINTA_PLATFORM_DATABASE_URL not set")
    return url


def test_apply_platform_migrations_creates_tables(database_url: str):
    # Drop platform schema if a previous test left it — exercise empty → ready.
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS platform CASCADE")
        conn.commit()

    apply_platform_migrations(database_url)
    apply_platform_migrations(database_url)  # idempotent

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'platform' AND table_name = 'tenants'"
            )
            assert cur.fetchone() is not None
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'platform' AND table_name = 'memberships'"
            )
            assert cur.fetchone() is not None


def test_store_ensure_ready_applies_missing_schema(database_url: str):
    from store import PlatformStore

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS platform CASCADE")
        conn.commit()

    store = PlatformStore(database_url)
    # Should not raise PLATFORM_SCHEMA_MISSING — migrate runs inside _ensure_ready.
    user = store.create_user(
        email=f"migrate-{uuid.uuid4().hex[:8]}@example.com",
        display_name=None,
        external_subject=f"sub-{uuid.uuid4()}",
    )
    assert user["user_id"]
