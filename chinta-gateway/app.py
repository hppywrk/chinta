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
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

APP_DIR = Path(__file__).resolve().parent
API_SPEC_PATH = APP_DIR / "api" / "gateway-openapi.yml"

app = FastAPI(
    title="Chinta API Gateway",
    version="1.0.0",
    description="Edge gateway in front of internal Chinta services",
)

security = HTTPBearer(auto_error=False)

AUTH_BASE_URL = os.environ.get("CHINTA_AUTH_URL", "http://chinta-auth:8083")
WEB_UI_URL = os.environ.get("CHINTA_WEB_URL", "http://chinta-web:8000")
MOBILE_UI_URL = os.environ.get("CHINTA_MOBILE_URL", "http://chinta-web:8000/m")
BACKEND_URL = os.environ.get("CHINTA_BACKEND_URL", "http://chinta-backend:8080")


async def get_access_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """Extract Bearer token from Authorization header."""
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return credentials.credentials


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


@app.api_route("/auth/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_auth(request: Request, path: str):
    """
    Blind proxy to the auth service. Gateway does not interpret auth semantics;
    it only forwards requests and responses. Authentication flow (login, callback,
    token exchange) is entirely owned by the auth service.
    """
    url = f"{AUTH_BASE_URL}/auth/{path}"
    method = request.method
    params = dict(request.query_params)
    body = await request.body() if method in ("POST", "PUT", "PATCH") else None
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "connection", "content-length")
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
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=dict(resp.headers),
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
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_api(
    path: str,
    request: Request,
    access_token: str = Depends(get_access_token),
):
    """
    Very simple example of gateway → backend proxy with auth.

    - Validates the token via dependency.
    - Forwards method, path, query and JSON body to backend.
    - Injects Authorization header so backend can trust user info later
      (or rely on gateway-only auth).
    """
    url = f"{BACKEND_URL}/{path}"
    method = request.method
    query = dict(request.query_params)
    try:
        body = await request.json()
    except Exception:
        body = None

    headers = dict(request.headers)
    headers["Authorization"] = f"Bearer {access_token}"

    async with httpx.AsyncClient() as client:
        resp = await client.request(
            method,
            url,
            params=query,
            json=body,
            headers=headers,
            timeout=15.0,
        )

    return JSONResponse(
        status_code=resp.status_code,
        content=resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text,
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
