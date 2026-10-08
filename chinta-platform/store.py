from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row

from errors import api_error
from migrate import apply_platform_migrations
from provision import provision_notes_schema
from schema_naming import tenant_schema_name, validate_slug

_BLOCKED_STATUSES = frozenset({"SUSPENDED", "DEPROVISIONED"})
_WRITE_ROLES = frozenset({"owner", "admin", "member"})
_MEMBERSHIP_STATUSES = frozenset({"INVITED", "ACTIVE", "SUSPENDED", "REMOVED"})


def would_orphan_last_active_owner(
    *,
    existing_role: str | None,
    existing_status: str | None,
    new_role: str,
    new_status: str,
    active_owner_count: int,
) -> bool:
    """Return True if an upsert would leave the tenant with zero ACTIVE owners.

    ``remove_membership`` already blocks deleting the last ACTIVE owner;
    upsert must apply the same invariant (API_CONTRACTS_V2 §3.2).
    """
    was_active_owner = existing_role == "owner" and existing_status == "ACTIVE"
    will_be_active_owner = new_role == "owner" and new_status == "ACTIVE"
    if not was_active_owner or will_be_active_owner:
        return False
    return active_owner_count <= 1



@dataclass(frozen=True)
class PlatformStore:
    database_url: str

    @contextmanager
    def _connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            yield conn

    def _ensure_ready(self) -> None:
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema = 'platform' AND table_name = 'tenants'"
                    )
                    missing = cur.fetchone() is None
            if missing:
                # Startup migrate may have been skipped (DB not ready yet); retry once.
                apply_platform_migrations(self.database_url)
                with self._connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT 1 FROM information_schema.tables "
                            "WHERE table_schema = 'platform' AND table_name = 'tenants'"
                        )
                        if cur.fetchone() is None:
                            raise api_error(
                                503,
                                "PLATFORM_SCHEMA_MISSING",
                                "Apply chinta-platform/migrations/001_platform_core.sql",
                            )
        except HTTPException:
            raise
        except psycopg.Error as exc:
            raise api_error(503, "DATABASE_UNAVAILABLE", "database unavailable") from exc
        except OSError as exc:
            raise api_error(503, "PLATFORM_SCHEMA_MISSING", str(exc)) from exc

    def create_user(
        self,
        email: str,
        display_name: str | None,
        external_subject: str | None,
    ) -> dict[str, Any]:
        self._ensure_ready()
        email = email.strip().lower()
        if not email or "@" not in email:
            raise api_error(400, "VALIDATION_ERROR", "email is required")

        subject = (external_subject or "").strip() or f"unlinked:{email}"
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO platform.users (external_subject, email, display_name)
                    VALUES (%s, %s, %s)
                    RETURNING id, external_subject, email, display_name, is_active
                    """,
                    (subject, email, display_name),
                )
                row = cur.fetchone()
            conn.commit()
        return self._user_row(row)

    def get_user(self, user_id: uuid.UUID) -> dict[str, Any]:
        self._ensure_ready()
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, external_subject, email, display_name, is_active
                    FROM platform.users WHERE id = %s
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
        if not row:
            raise api_error(404, "USER_NOT_FOUND", "User not found")
        return self._user_row(row)

    def get_user_by_email(self, email: str) -> dict[str, Any]:
        self._ensure_ready()
        email = email.strip().lower()
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, external_subject, email, display_name, is_active
                    FROM platform.users WHERE email = %s
                    """,
                    (email,),
                )
                row = cur.fetchone()
        if not row:
            raise api_error(404, "USER_NOT_FOUND", "User not found")
        return self._user_row(row)

    def create_tenant(
        self,
        slug: str,
        display_name: str,
        owner_user_id: uuid.UUID,
    ) -> dict[str, Any]:
        self._ensure_ready()
        slug = validate_slug(slug)
        schema_name = tenant_schema_name(slug)
        self.get_user(owner_user_id)

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO platform.tenants (slug, display_name, schema_name, status)
                    VALUES (%s, %s, %s, 'ACTIVE_SHARED')
                    RETURNING id, slug, display_name, status, schema_name
                    """,
                    (slug, display_name.strip(), schema_name),
                )
                tenant = cur.fetchone()
                cur.execute(
                    """
                    INSERT INTO platform.memberships
                        (tenant_id, user_id, role_code, membership_status, joined_at)
                    VALUES (%s, %s, 'owner', 'ACTIVE', now())
                    """,
                    (tenant["id"], owner_user_id),
                )
            provision_notes_schema(conn, schema_name)
        return self._tenant_row(tenant)

    def get_tenant(self, tenant_id: uuid.UUID) -> dict[str, Any]:
        self._ensure_ready()
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, slug, display_name, status::text AS status, schema_name
                    FROM platform.tenants WHERE id = %s
                    """,
                    (tenant_id,),
                )
                row = cur.fetchone()
        if not row:
            raise api_error(404, "TENANT_NOT_FOUND", "Tenant not found")
        return self._tenant_row(row)

    def get_tenant_by_slug(self, slug: str) -> dict[str, Any]:
        self._ensure_ready()
        slug = validate_slug(slug)
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, slug, display_name, status::text AS status, schema_name
                    FROM platform.tenants WHERE slug = %s
                    """,
                    (slug,),
                )
                row = cur.fetchone()
        if not row:
            raise api_error(404, "TENANT_NOT_FOUND", "Tenant not found")
        return self._tenant_row(row)

    def list_tenants(self, limit: int = 50) -> list[dict[str, Any]]:
        self._ensure_ready()
        limit = max(1, min(limit, 200))
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, slug, display_name, status::text AS status, schema_name
                    FROM platform.tenants
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
        return [self._tenant_row(r) for r in rows]

    def list_memberships(self, tenant_id: uuid.UUID) -> dict[str, Any]:
        self._ensure_ready()
        self.get_tenant(tenant_id)
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT m.user_id, m.role_code, m.membership_status
                    FROM platform.memberships m
                    WHERE m.tenant_id = %s AND m.membership_status != 'REMOVED'
                    ORDER BY m.created_at
                    """,
                    (tenant_id,),
                )
                items = [
                    {
                        "user_id": str(r["user_id"]),
                        "role_code": r["role_code"],
                        "membership_status": r["membership_status"],
                    }
                    for r in cur.fetchall()
                ]
        return {"tenant_id": str(tenant_id), "items": items}

    def upsert_membership(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        role_code: str,
        membership_status: str = "ACTIVE",
    ) -> dict[str, Any]:
        self._ensure_ready()
        if role_code not in ("owner", "admin", "member", "viewer"):
            raise api_error(400, "VALIDATION_ERROR", "invalid role_code")
        if membership_status not in _MEMBERSHIP_STATUSES:
            raise api_error(400, "VALIDATION_ERROR", "invalid membership_status")
        self.get_tenant(tenant_id)
        self.get_user(user_id)

        with self._connection() as conn:
            with conn.cursor() as cur:
                # Serialize membership mutations per tenant so concurrent demotions
                # of different ACTIVE owners cannot both pass the last-owner check
                # (READ COMMITTED TOCTOU → zero owners; API_CONTRACTS_V2 §3.2).
                self._lock_tenant(cur, tenant_id)
                cur.execute(
                    """
                    SELECT role_code, membership_status FROM platform.memberships
                    WHERE tenant_id = %s AND user_id = %s
                    FOR UPDATE
                    """,
                    (tenant_id, user_id),
                )
                existing = cur.fetchone()
                active_owners = self._count_active_owners(cur, tenant_id)
                if would_orphan_last_active_owner(
                    existing_role=existing["role_code"] if existing else None,
                    existing_status=existing["membership_status"] if existing else None,
                    new_role=role_code,
                    new_status=membership_status,
                    active_owner_count=active_owners,
                ):
                    raise api_error(
                        409,
                        "VALIDATION_ERROR",
                        "Cannot remove the last active owner",
                    )
                cur.execute(
                    """
                    INSERT INTO platform.memberships
                        (tenant_id, user_id, role_code, membership_status, joined_at)
                    VALUES (%s, %s, %s, %s, now())
                    ON CONFLICT (tenant_id, user_id) DO UPDATE SET
                        role_code = EXCLUDED.role_code,
                        membership_status = EXCLUDED.membership_status,
                        updated_at = now()
                    RETURNING role_code, membership_status
                    """,
                    (tenant_id, user_id, role_code, membership_status),
                )
                row = cur.fetchone()
            conn.commit()
        return {
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
            "role_code": row["role_code"],
            "membership_status": row["membership_status"],
        }

    def remove_membership(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self._ensure_ready()
        with self._connection() as conn:
            with conn.cursor() as cur:
                self._lock_tenant(cur, tenant_id)
                cur.execute(
                    """
                    SELECT role_code, membership_status FROM platform.memberships
                    WHERE tenant_id = %s AND user_id = %s
                    FOR UPDATE
                    """,
                    (tenant_id, user_id),
                )
                existing = cur.fetchone()
                if not existing or existing["membership_status"] == "REMOVED":
                    raise api_error(404, "MEMBERSHIP_NOT_FOUND", "Membership not found")
                # Only ACTIVE owners count toward the invariant; suspending/removing
                # a non-ACTIVE owner must not be blocked by the sole ACTIVE owner.
                if (
                    existing["role_code"] == "owner"
                    and existing["membership_status"] == "ACTIVE"
                    and self._count_active_owners(cur, tenant_id) <= 1
                ):
                    raise api_error(
                        409,
                        "VALIDATION_ERROR",
                        "Cannot remove the last active owner",
                    )
                cur.execute(
                    """
                    UPDATE platform.memberships
                    SET membership_status = 'REMOVED', updated_at = now()
                    WHERE tenant_id = %s AND user_id = %s
                    """,
                    (tenant_id, user_id),
                )
            conn.commit()

    def resolve_access(
        self,
        tenant_slug: str,
        user_external_subject: str,
        operation: str,
    ) -> dict[str, Any]:
        self._ensure_ready()
        slug = validate_slug(tenant_slug)
        subject = user_external_subject.strip()
        if not subject:
            raise api_error(400, "VALIDATION_ERROR", "user_external_subject is required")

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT t.id, t.slug, t.status::text AS status, t.schema_name,
                           m.role_code, m.membership_status
                    FROM platform.tenants t
                    JOIN platform.users u ON u.external_subject = %s AND u.is_active
                    JOIN platform.memberships m
                      ON m.tenant_id = t.id AND m.user_id = u.id
                    WHERE t.slug = %s
                    """,
                    (subject, slug),
                )
                row = cur.fetchone()

        if not row:
            return {
                "allowed": False,
                "deny_reason": "MEMBERSHIP_NOT_FOUND",
                "tenant_id": None,
                "tenant_status": None,
                "schema_name": None,
                "role_code": None,
            }

        status = row["status"]
        if status in _BLOCKED_STATUSES:
            return {
                "allowed": False,
                "deny_reason": "TENANT_STATUS_BLOCKED",
                "tenant_id": str(row["id"]),
                "tenant_status": status,
                "schema_name": row["schema_name"],
                "role_code": row["role_code"],
            }

        if row["membership_status"] != "ACTIVE":
            return {
                "allowed": False,
                "deny_reason": "MEMBERSHIP_NOT_FOUND",
                "tenant_id": str(row["id"]),
                "tenant_status": status,
                "schema_name": row["schema_name"],
                "role_code": row["role_code"],
            }

        if operation == "write" and row["role_code"] not in _WRITE_ROLES:
            return {
                "allowed": False,
                "deny_reason": "ENTITLEMENT_DENIED",
                "tenant_id": str(row["id"]),
                "tenant_status": status,
                "schema_name": row["schema_name"],
                "role_code": row["role_code"],
            }

        return {
            "allowed": True,
            "deny_reason": None,
            "tenant_id": str(row["id"]),
            "tenant_status": status,
            "schema_name": row["schema_name"],
            "role_code": row["role_code"],
        }

    @staticmethod
    def _lock_tenant(cur: Any, tenant_id: uuid.UUID) -> None:
        """Row-lock the tenant so membership invariant checks are serialized."""
        cur.execute(
            "SELECT id FROM platform.tenants WHERE id = %s FOR UPDATE",
            (tenant_id,),
        )
        if cur.fetchone() is None:
            raise api_error(404, "TENANT_NOT_FOUND", "Tenant not found")

    @staticmethod
    def _count_active_owners(cur: Any, tenant_id: uuid.UUID) -> int:
        cur.execute(
            """
            SELECT count(*) AS n FROM platform.memberships
            WHERE tenant_id = %s AND role_code = 'owner'
              AND membership_status = 'ACTIVE'
            """,
            (tenant_id,),
        )
        return int(cur.fetchone()["n"])

    @staticmethod
    def _user_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "user_id": str(row["id"]),
            "external_subject": row["external_subject"],
            "email": row["email"],
            "display_name": row["display_name"],
            "is_active": row["is_active"],
        }

    @staticmethod
    def _tenant_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "tenant_id": str(row["id"]),
            "slug": row["slug"],
            "display_name": row["display_name"],
            "status": row["status"],
            "schema_name": row["schema_name"],
        }
