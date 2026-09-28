"""PostgreSQL access with schema-per-tenant isolation."""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,60}$")
# PostgreSQL identifiers are limited to 63 bytes; schema is t_<tenant_id>.
_MAX_TENANT_ID_LEN = 61


def validate_tenant_id(tenant_id: str) -> str:
    tenant_id = tenant_id.strip()
    if not tenant_id or len(tenant_id) > _MAX_TENANT_ID_LEN:
        raise ValueError("invalid tenant id")
    if not _TENANT_ID_RE.match(tenant_id):
        raise ValueError("invalid tenant id")
    return tenant_id


def tenant_schema_name(tenant_id: str) -> str:
    """
    Map tenant id to a PostgreSQL schema (platform convention: t_<tenant_id>).

    The tenant id is preserved verbatim (no normalization) so distinct ids
    never share a schema. psycopg.sql.Identifier quotes names when needed.
    """
    tenant_id = validate_tenant_id(tenant_id)
    schema = f"t_{tenant_id}"
    if len(schema) > 63:
        raise ValueError("tenant id too long for schema name")
    return schema


@dataclass(frozen=True)
class Note:
    id: int
    body: str
    modified_at: datetime

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "body": self.body,
            "modified_at": self.modified_at.isoformat(),
        }


class NotesStore:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
            yield conn

    def _ensure_schema(self, conn: psycopg.Connection, schema: str) -> None:
        # Showcase-only: lazy DDL per request. Replace with B5.0 schema creation service.
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
                    "CREATE INDEX IF NOT EXISTS {} ON {}.{} (user_id, modified_at DESC)"
                ).format(
                    sql.Identifier("idx_notes_user_modified"),
                    sql.Identifier(schema),
                    sql.Identifier("notes"),
                )
            )
        conn.commit()

    def list_notes(self, tenant_id: str, user_id: str) -> list[Note]:
        schema = tenant_schema_name(tenant_id)
        with self._connection() as conn:
            self._ensure_schema(conn, schema)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT id, body, modified_at
                        FROM {}.notes
                        WHERE user_id = %s
                        ORDER BY modified_at DESC, id DESC
                        """
                    ).format(sql.Identifier(schema)),
                    (user_id,),
                )
                rows = cur.fetchall()
        return [Note(id=r["id"], body=r["body"], modified_at=r["modified_at"]) for r in rows]

    def create_note(self, tenant_id: str, user_id: str, body: str) -> Note:
        schema = tenant_schema_name(tenant_id)
        with self._connection() as conn:
            self._ensure_schema(conn, schema)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {}.notes (user_id, body, modified_at)
                        VALUES (%s, %s, NOW())
                        RETURNING id, body, modified_at
                        """
                    ).format(sql.Identifier(schema)),
                    (user_id, body),
                )
                row = cur.fetchone()
            conn.commit()
        return Note(id=row["id"], body=row["body"], modified_at=row["modified_at"])

    def replace_note(self, tenant_id: str, user_id: str, note_id: int, body: str) -> Note | None:
        schema = tenant_schema_name(tenant_id)
        with self._connection() as conn:
            self._ensure_schema(conn, schema)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        UPDATE {}.notes
                        SET body = %s, modified_at = NOW()
                        WHERE id = %s AND user_id = %s
                        RETURNING id, body, modified_at
                        """
                    ).format(sql.Identifier(schema)),
                    (body, note_id, user_id),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            return None
        return Note(id=row["id"], body=row["body"], modified_at=row["modified_at"])

    def delete_note(self, tenant_id: str, user_id: str, note_id: int) -> bool:
        schema = tenant_schema_name(tenant_id)
        with self._connection() as conn:
            self._ensure_schema(conn, schema)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("DELETE FROM {}.notes WHERE id = %s AND user_id = %s").format(
                        sql.Identifier(schema)
                    ),
                    (note_id, user_id),
                )
                deleted = cur.rowcount > 0
            conn.commit()
        return deleted
