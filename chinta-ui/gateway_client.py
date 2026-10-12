"""HTTP calls to the gateway on behalf of the logged-in browser session."""
from __future__ import annotations

from typing import Any

import httpx


class GatewayError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


async def fetch_me(gateway_url: str, access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{gateway_url}/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
    if resp.status_code != 200:
        raise GatewayError(resp.status_code, resp.text or "Failed to load profile")
    return resp.json()


async def list_notes(
    gateway_url: str,
    access_token: str,
    tenant_slug: str,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{gateway_url}/api/notes",
            params={"limit": limit},
            headers={
                "Authorization": f"Bearer {access_token}",
                "X-Tenant-Id": tenant_slug,
            },
            timeout=15.0,
        )
    if resp.status_code != 200:
        raise GatewayError(resp.status_code, resp.text or "Failed to list notes")
    return resp.json()


async def create_note(
    gateway_url: str,
    access_token: str,
    tenant_slug: str,
    body: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{gateway_url}/api/notes",
            json={"body": body},
            headers={
                "Authorization": f"Bearer {access_token}",
                "X-Tenant-Id": tenant_slug,
            },
            timeout=15.0,
        )
    if resp.status_code not in (200, 201):
        raise GatewayError(resp.status_code, resp.text or "Failed to create note")
    return resp.json()
