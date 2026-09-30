"""Resolve tenant access via chinta-platform (gateway critical path)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    deny_reason: str | None
    tenant_id: str | None
    tenant_status: str | None
    schema_name: str | None
    role_code: str | None


def platform_enforced(platform_base_url: str | None = None) -> bool:
    if platform_base_url is not None:
        return bool(platform_base_url.strip())
    import os

    return bool(os.environ.get("CHINTA_PLATFORM_URL", "").strip())


def operation_for_method(method: str) -> str:
    return "read" if method.upper() == "GET" else "write"


async def resolve_tenant_access(
    platform_base_url: str,
    tenant_slug: str,
    user_subject: str,
    http_method: str,
    *,
    module_code: str = "notes",
) -> AccessDecision:
    payload = {
        "tenant_slug": tenant_slug,
        "user_external_subject": user_subject,
        "module_code": module_code,
        "operation": operation_for_method(http_method),
    }
    url = f"{platform_base_url.rstrip('/')}/v1/access/resolve"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10.0)
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Platform service unavailable")

    if resp.status_code != 200:
        raise HTTPException(
            status_code=503,
            detail=f"Platform access resolve failed (HTTP {resp.status_code})",
        )

    try:
        data: dict[str, Any] = resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Platform returned non-JSON access decision")

    return AccessDecision(
        allowed=bool(data.get("allowed")),
        deny_reason=data.get("deny_reason"),
        tenant_id=data.get("tenant_id"),
        tenant_status=data.get("tenant_status"),
        schema_name=data.get("schema_name"),
        role_code=data.get("role_code"),
    )


def http_status_for_deny(reason: str | None) -> int:
    if reason == "TENANT_NOT_FOUND":
        return 404
    return 403


def deny_detail(reason: str | None) -> dict:
    code = reason or "ENTITLEMENT_DENIED"
    messages = {
        "TENANT_NOT_FOUND": "Tenant not found",
        "TENANT_STATUS_BLOCKED": "Tenant access blocked",
        "MEMBERSHIP_NOT_FOUND": "No active membership for tenant",
        "ENTITLEMENT_DENIED": "Access denied",
    }
    return {
        "error": {
            "code": code,
            "message": messages.get(code, "Access denied"),
            "details": {},
        }
    }
