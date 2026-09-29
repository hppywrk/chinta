from __future__ import annotations

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import get_config
from errors import api_error

_bearer = HTTPBearer(auto_error=False)


async def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    expected = get_config().admin_token
    if not expected:
        raise api_error(503, "PLATFORM_NOT_CONFIGURED", "CHINTA_PLATFORM_ADMIN_TOKEN is not set")

    token: str | None = None
    if credentials and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
    elif x_admin_token:
        token = x_admin_token.strip()

    if not token or token != expected:
        raise api_error(401, "UNAUTHORIZED", "Invalid or missing admin credentials")
