"""
Chinta API Gateway — edge proxy in front of auth and backend services.
Interface described in api/gateway-openapi.yml.
"""
import os
from pathlib import Path
from typing import Optional

import httpx
import yaml
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_access import (
    AccessDecision,
    deny_detail,
    http_status_for_deny,
    platform_enforced,
    resolve_tenant_access,
)
from chinta_observability import configure_logging, install_metrics, install_request_logging
from userinfo import AuthenticatedUser, fetch_authenticated_user

SERVICE_NAME = "chinta-gateway"
configure_logging(SERVICE_NAME)

APP_DIR = Path(__file__).resolve().parent
API_SPEC_PATH = APP_DIR / "api" / "gateway-openapi.yml"

app = FastAPI(
    title="Chinta API Gateway",
    version="1.0.0",
    description="Edge gateway in front of internal Chinta services",
)
install_request_logging(app, SERVICE_NAME)
install_metrics(app, SERVICE_NAME)

security = HTTPBearer(auto_error=False)

AUTH_BASE_URL = os.environ.get("CHINTA_AUTH_URL", "http://chinta-auth:8083")
WEB_UI_URL = os.environ.get("CHINTA_WEB_URL", "http://localhost:8084/ui")
MOBILE_UI_URL = os.environ.get("CHINTA_MOBILE_URL", WEB_UI_URL)
UI_INTERNAL_URL = os.environ.get("CHINTA_UI_URL", "http://chinta-ui:8086").rstrip("/")
BACKEND_URL = os.environ.get("CHINTA_BACKEND_URL", "http://chinta-backend:8080")
PLATFORM_BASE_URL = os.environ.get("CHINTA_PLATFORM_URL", "").strip()
PUBLIC_BASE_URL = os.environ.get("OIDC_REDIRECT_URI_BASE", "http://localhost:8084").rstrip("/")
SESSION_COOKIE_NAME = os.environ.get("CHINTA_SESSION_COOKIE", "chinta_access_token")

# Headers set by the gateway; clients must not spoof them on /api.
_GATEWAY_INJECTED_HEADERS = frozenset(
    {
        "x-tenant-schema",
        "x-platform-user-role",
    }
)

# Framing / hop-by-hop headers must not be blindly forwarded. httpx auto-decodes
# Content-Encoding (e.g. gzip) but leaves the upstream Content-Length, which then
# crashes Starlette/uvicorn with "Response content longer than Content-Length".
_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
        "content-encoding",
    }
)


async def get_access_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """Extract Bearer token from Authorization header."""
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return credentials.credentials


async def require_authenticated_user(
    access_token: str = Depends(get_access_token),
) -> AuthenticatedUser:
    """
    Require a Bearer token that the auth service accepts.

    Presence checks alone are not enough: /api used to forward any
    non-empty Bearer string to the backend (auth bypass). Validate via
    auth /userinfo before proxying.
    """
    return await fetch_authenticated_user(AUTH_BASE_URL, access_token)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root(request: Request):
    """
    Convenience redirect to web/mobile UI (not part of gateway OpenAPI v1 contract).
    See docs/SPEC_DRIVEN_DEVELOPMENT.md backlog B_GW.2.
    """
    target = request.query_params.get("target")
    if target == "mobile":
        return RedirectResponse(MOBILE_UI_URL)
    if target == "web":
        return RedirectResponse(WEB_UI_URL)

    ua = request.headers.get("user-agent", "").lower()
    if "mobile" in ua or "android" in ua or "iphone" in ua:
        return RedirectResponse(MOBILE_UI_URL)
    return RedirectResponse(WEB_UI_URL)


@app.get("/auth/callback")
async def browser_auth_callback(
    request: Request,
    code: str,
    state: str | None = None,
    redirect_uri: str | None = None,
):
    """
    Browser OAuth completion: exchange code via auth, set httpOnly session cookie,
    redirect into the web UI. API clients should call auth :8083 directly for JSON.
    """
    if request.query_params.get("format") == "json":
        return await _proxy_auth_request(request, "callback")

    redirect = redirect_uri or f"{PUBLIC_BASE_URL}/auth/callback"
    params = {"code": code, "redirect_uri": redirect}
    if state is not None:
        params["state"] = state
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{AUTH_BASE_URL}/auth/callback",
            params=params,
            timeout=15.0,
        )
    if resp.status_code != 200:
        try:
            detail = resp.json()
        except ValueError:
            detail = resp.text
        raise HTTPException(status_code=resp.status_code, detail=detail)
    try:
        token_data = resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Auth returned non-JSON token response")
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="Auth response missing access_token")

    target = WEB_UI_URL.rstrip("/") + "/app"
    response = RedirectResponse(url=target, status_code=302)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        access_token,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


async def _proxy_auth_request(request: Request, path: str) -> Response:
    url = f"{AUTH_BASE_URL}/auth/{path}"
    method = request.method
    params = list(request.query_params.multi_items())
    body = await request.body() if method in ("POST", "PUT", "PATCH") else None
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS
    }
    async with httpx.AsyncClient() as client:
        resp = await client.request(
            method,
            url,
            params=params,
            content=body,
            headers=headers,
            timeout=10.0,
        )
    response_headers = {
        k: v
        for k, v in resp.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS
    }
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=response_headers,
        media_type=resp.headers.get("content-type"),
    )


@app.api_route("/auth/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_auth(request: Request, path: str):
    """
    Blind proxy to the auth service. Gateway does not interpret auth semantics;
    it only forwards requests and responses. Authentication flow (login, callback,
    token exchange) is entirely owned by the auth service.
    """
    return await _proxy_auth_request(request, path)


@app.api_route("/ui/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.api_route("/ui", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_ui(request: Request, path: str = ""):
    """Same-origin proxy to chinta-ui (session cookies use gateway host)."""
    suffix = path.strip("/")
    url = f"{UI_INTERNAL_URL}/{suffix}" if suffix else f"{UI_INTERNAL_URL}/"
    method = request.method
    params = list(request.query_params.multi_items())
    body = await request.body() if method in ("POST", "PUT", "PATCH") else None
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS
    }
    async with httpx.AsyncClient() as client:
        resp = await client.request(
            method,
            url,
            params=params,
            content=body,
            headers=headers,
            timeout=30.0,
        )
    response_headers = {
        k: v
        for k, v in resp.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS
    }
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=response_headers,
        media_type=resp.headers.get("content-type"),
    )


@app.get("/me")
async def me(access_token: str = Depends(get_access_token)):
    """
    Example of the gateway asking Auth service for user info.

    Other gateway routes can depend on this to get user_id, org_id, etc.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{AUTH_BASE_URL}/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
    # Auth (or a proxy in front of it) may return HTML/empty bodies on failure.
    # Unconditional resp.json() raises JSONDecodeError and turns those into opaque 500s.
    if resp.status_code != 200:
        try:
            detail = resp.json()
        except ValueError:
            detail = {
                "error": "auth_upstream_error",
                "error_description": resp.text
                or f"Auth service returned HTTP {resp.status_code}",
            }
        raise HTTPException(status_code=resp.status_code, detail=detail)
    try:
        return resp.json()
    except ValueError:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "invalid_userinfo_response",
                "error_description": "Auth service returned non-JSON userinfo",
            },
        )


async def _platform_decision(
    request: Request,
    user: AuthenticatedUser,
) -> AccessDecision | None:
    if not platform_enforced(PLATFORM_BASE_URL):
        return None
    tenant_slug = request.headers.get("X-Tenant-Id", "").strip()
    if not tenant_slug:
        raise HTTPException(status_code=400, detail="X-Tenant-Id header is required")
    decision = await resolve_tenant_access(
        PLATFORM_BASE_URL,
        tenant_slug,
        user.subject,
        request.method,
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=http_status_for_deny(decision.deny_reason),
            detail=deny_detail(decision.deny_reason),
        )
    return decision


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_api(
    path: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_authenticated_user),
):
    """
    Very simple example of gateway → backend proxy with auth.

    - Validates the token with the auth service before forwarding.
    - Forwards method, path, query and raw body to backend (no re-encoding).
    - Injects Authorization header so backend can trust user info later
      (or rely on gateway-only auth).
    """
    url = f"{BACKEND_URL}/{path}"
    method = request.method
    # Preserve repeated keys (dict(query_params) keeps only the last value).
    query = list(request.query_params.multi_items())
    # Forward the raw body. Re-serializing via json= changes Content-Length and
    # crashes httpx/h11 when the client sent pretty-printed or spaced JSON.
    body = await request.body() if method in ("POST", "PUT", "PATCH") else None

    decision = await _platform_decision(request, user)

    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS
        and k.lower() not in _GATEWAY_INJECTED_HEADERS
    }
    headers["Authorization"] = f"Bearer {user.access_token}"
    if decision and decision.schema_name:
        headers["X-Tenant-Schema"] = decision.schema_name
    if decision and decision.role_code:
        headers["X-Platform-User-Role"] = decision.role_code

    async with httpx.AsyncClient() as client:
        resp = await client.request(
            method,
            url,
            params=query,
            content=body,
            headers=headers,
            timeout=15.0,
        )

    # Forward upstream bytes as-is. Re-parsing via resp.json()/JSONResponse:
    # - crashes on empty application/json bodies (JSONDecodeError → 500)
    # - corrupts non-JSON payloads (e.g. PDF) by JSON-encoding resp.text
    response_headers = {
        k: v
        for k, v in resp.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS
    }
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=response_headers,
        media_type=resp.headers.get("content-type"),
    )


# --- Serve OpenAPI spec from YAML ---

@app.get("/openapi.json", include_in_schema=False)
async def openapi_json():
    """Serve OpenAPI schema. Built from api/gateway-openapi.yml with FastAPI overlay."""
    with open(API_SPEC_PATH) as f:
        spec = yaml.safe_load(f)
    openapi_schema = get_openapi(
        title=spec["info"]["title"],
        version=spec["info"]["version"],
        description=spec["info"].get("description", ""),
        routes=app.routes,
    )
    openapi_schema["paths"] = spec.get("paths", openapi_schema["paths"])
    openapi_schema["components"] = spec.get("components", openapi_schema.get("components", {}))
    return openapi_schema


@app.get("/openapi.yaml", include_in_schema=False, response_class=PlainTextResponse)
async def openapi_yaml():
    """Serve OpenAPI schema as YAML."""
    with open(API_SPEC_PATH) as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("CHINTA_GATEWAY_PORT", "8084"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
