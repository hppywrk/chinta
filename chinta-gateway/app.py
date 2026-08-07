"""
Chinta API Gateway — edge proxy routing to internal services.

M1 routes:
  /health           → gateway health
  /auth/{path}      → chinta-auth
  /api/notes/{path} → chinta-notebook
  /me               → auth userinfo (bearer required)
"""
import logging
import os
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from log import setup_logging

setup_logging()
logger = logging.getLogger("chinta-gateway")

app = FastAPI(
    title="Chinta API Gateway",
    version="0.1.0",
    description="Edge gateway in front of internal Chinta services",
)

security = HTTPBearer(auto_error=False)

AUTH_BASE_URL = os.environ.get("CHINTA_AUTH_URL", "http://chinta-auth:8083")
NOTEBOOK_URL = os.environ.get("CHINTA_NOTEBOOK_URL", "http://chinta-notebook:8085")


async def get_access_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return credentials.credentials


@app.get("/health")
async def health():
    return {"status": "ok"}


# --- Auth proxy ---

@app.api_route("/auth/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_auth(request: Request, path: str):
    """Blind proxy to the auth service."""
    url = f"{AUTH_BASE_URL}/auth/{path}"
    method = request.method
    params = dict(request.query_params)
    body = await request.body() if method in ("POST", "PUT", "PATCH") else None
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "connection", "content-length")
    }
    logger.info("Proxying auth request", extra={"method": method, "path": path})
    async with httpx.AsyncClient() as client:
        resp = await client.request(method, url, params=params, content=body, headers=headers, timeout=10.0)
    return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))


# --- Notebook proxy (M1: no auth enforcement, single-user) ---

@app.api_route("/api/notes/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_notes_with_path(request: Request, path: str):
    return await _proxy_notebook(request, f"/notes/{path}")


@app.api_route("/api/notes", methods=["GET", "POST"])
async def proxy_notes_root(request: Request):
    return await _proxy_notebook(request, "/notes")


async def _proxy_notebook(request: Request, upstream_path: str):
    url = f"{NOTEBOOK_URL}{upstream_path}"
    method = request.method
    params = dict(request.query_params)
    body = await request.body() if method in ("POST", "PUT", "PATCH") else None
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "connection", "content-length")
    }
    logger.info("Proxying notebook request", extra={"method": method, "path": upstream_path})
    async with httpx.AsyncClient() as client:
        resp = await client.request(method, url, params=params, content=body, headers=headers, timeout=10.0)
    return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))


# --- Userinfo (requires bearer) ---

@app.get("/me")
async def me(access_token: str = Depends(get_access_token)):
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{AUTH_BASE_URL}/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("CHINTA_GATEWAY_PORT", "8084"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
