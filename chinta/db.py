"""PostgreSQL access with schema-per-tenant isolation."""
from __future__ import annotations

import hashlib
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,62}$")
_SCHEMA_RE = re.compile(r"^t_[a-z0-9_]+$")


class TenantSchemaNotFoundError(Exception):
    """Raised when platform enforcement forbids lazy schema creation."""


def validate_tenant_schema(schema: str) -> str:
    schema = schema.strip()
    if not schema or not _SCHEMA_RE.match(schema):
        raise ValueError("invalid tenant schema")
    return schema
# PostgreSQL truncates identifiers to NAMEDATALEN-1 (63) bytes silently.
_PG_IDENT_MAX = 63


def validate_tenant_id(tenant_id: str) -> str:
    tenant_id = tenant_id.strip()
    if not tenant_id or not _TENANT_ID_RE.match(tenant_id):
        raise ValueError("invalid tenant id")
    return tenant_id


def tenant_schema_name(tenant_id: str) -> str:
    """Map tenant id to a PostgreSQL schema name that cannot collide.

    A naive ``t_<id>`` with ``-``/``.`` folded to ``_`` merges distinct tenants
    (``acme-corp`` / ``acme.corp`` / ``acme_corp``). Long ids also collide after
    PostgreSQL's silent 63-byte identifier truncation. Hash the id so every
    validated tenant maps to a unique schema within the identifier limit.
    """
    validate_tenant_id(tenant_id)
    digest = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()
    # ``t_`` + 60 hex chars == 62 bytes, safely under the 63-byte limit.
    return f"t_{digest[:60]}"


def tenant_notes_index_name(schema: str) -> str:
    """Stable per-schema index name that also fits in 63 bytes."""
    digest = hashlib.sha256(schema.encode("utf-8")).hexdigest()
    name = f"i_{digest[:60]}"
    assert len(name) <= _PG_IDENT_MAX
    return name


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
    def __init__(self, database_url: str, *, enforce_platform: bool = False) -> None:
        self._database_url = database_url
        self._enforce_platform = enforce_platform

    @contextmanager
    def _connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
            yield conn

    def _ensure_schema(self, conn: psycopg.Connection, schema: str) -> None:
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

    def _schema_exists(self, conn: psycopg.Connection, schema: str) -> bool:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM information_schema.schemata
                WHERE schema_name = %s
                """,
                (schema,),
            )
            return cur.fetchone() is not None

    def _resolve_schema(self, tenant_id: str, tenant_schema: str | None) -> str:
        if tenant_schema:
            return validate_tenant_schema(tenant_schema)
        if self._enforce_platform:
            raise ValueError("X-Tenant-Schema is required when platform enforcement is enabled")
        return tenant_schema_name(tenant_id)

    def _prepare_schema(self, conn: psycopg.Connection, schema: str) -> None:
        if self._enforce_platform:
            if not self._schema_exists(conn, schema):
                raise TenantSchemaNotFoundError(schema)
            return
        self._ensure_schema(conn, schema)

    def list_notes(
        self, tenant_id: str, user_id: str, tenant_schema: str | None = None
    ) -> list[Note]:
        schema = self._resolve_schema(tenant_id, tenant_schema)
        with self._connection() as conn:
            self._prepare_schema(conn, schema)
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

    def create_note(
        self, tenant_id: str, user_id: str, body: str, tenant_schema: str | None = None
    ) -> Note:
        schema = self._resolve_schema(tenant_id, tenant_schema)
        with self._connection() as conn:
            self._prepare_schema(conn, schema)
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

    def replace_note(
        self,
        tenant_id: str,
        user_id: str,
        note_id: int,
        body: str,
        tenant_schema: str | None = None,
    ) -> Note | None:
        schema = self._resolve_schema(tenant_id, tenant_schema)
        with self._connection() as conn:
            self._prepare_schema(conn, schema)
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

    def delete_note(
        self, tenant_id: str, user_id: str, note_id: int, tenant_schema: str | None = None
    ) -> bool:
        schema = self._resolve_schema(tenant_id, tenant_schema)
        with self._connection() as conn:
            self._prepare_schema(conn, schema)
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
