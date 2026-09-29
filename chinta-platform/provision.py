"""Provision module runtime schema for a new tenant (notes baseline)."""
from __future__ import annotations

import psycopg
from psycopg import sql

from schema_naming import tenant_notes_index_name


def provision_notes_schema(conn: psycopg.Connection, schema: str) -> None:
    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
        cur.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {}.notes (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    body TEXT NOT NULL,
                    modified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            ).format(sql.Identifier(schema))
        )
        cur.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS {} ON {}.notes (user_id, modified_at DESC)"
            ).format(
                sql.Identifier(tenant_notes_index_name(schema)),
                sql.Identifier(schema),
            )
        )
    conn.commit()
