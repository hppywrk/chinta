"""Resolve caller identity via the auth service userinfo endpoint."""
from __future__ import annotations

from dataclasses import dataclass

import httpx
from fastapi import HTTPException, Request


@dataclass(frozen=True)
class RequestContext:
    user_id: str
    tenant_id: str


async def resolve_request_context(request: Request, auth_base_url: str) -> RequestContext:
    tenant_id = request.headers.get("X-Tenant-Id", "").strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-Id header is required")

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{auth_base_url}/userinfo",
                headers={"Authorization": auth_header},
                timeout=10.0,
            )
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Auth service unavailable")

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired access token")

    try:
        claims = resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Auth service returned non-JSON userinfo")

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=502, detail="Userinfo missing sub claim")

    return RequestContext(user_id=str(user_id), tenant_id=tenant_id)
