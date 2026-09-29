"""Validate Bearer tokens and load OIDC userinfo from chinta-auth."""
from __future__ import annotations

from dataclasses import dataclass

import httpx
from fastapi import HTTPException


@dataclass(frozen=True)
class AuthenticatedUser:
    access_token: str
    subject: str


async def fetch_authenticated_user(auth_base_url: str, access_token: str) -> AuthenticatedUser:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{auth_base_url.rstrip('/')}/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
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
    subject = claims.get("sub")
    if not subject:
        raise HTTPException(status_code=502, detail="Userinfo missing sub claim")
    return AuthenticatedUser(access_token=access_token, subject=str(subject))
