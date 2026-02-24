import os
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


app = FastAPI(
    title="Chinta API Gateway",
    version="0.1.0",
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
    """Redirect to desktop or mobile UI based on a simple hint."""
    # Very simple heuristic: explicit query wins, otherwise User-Agent sniff
    target = request.query_params.get("target")
    if target == "mobile":
        return RedirectResponse(MOBILE_UI_URL)
    if target == "web":
        return RedirectResponse(WEB_UI_URL)

    ua = request.headers.get("user-agent", "").lower()
    if "mobile" in ua or "android" in ua or "iphone" in ua:
        return RedirectResponse(MOBILE_UI_URL)
    return RedirectResponse(WEB_UI_URL)


@app.get("/auth/login")
async def login(redirect_uri: Optional[str] = None):
    """
    Start login by asking Auth service for an authorization URL.

    In a browser flow the frontend would call this, then redirect the user
    to the returned URL.
    """
    # Where should the IdP send the user back? By default, our own /auth/callback
    redirect = redirect_uri or os.environ.get(
        "CHINTA_AUTH_CALLBACK_URL",
        "http://localhost:8084/auth/callback",
    )
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{AUTH_BASE_URL}/auth/authorize",
            params={"redirect_uri": redirect},
            timeout=10.0,
        )
    resp.raise_for_status()
    data = resp.json()
    return data


@app.get("/auth/callback")
async def auth_callback(code: str, state: Optional[str] = None, nonce: Optional[str] = None):
    """
    Receive code from IdP (via Auth service redirect).

    For now we just exchange it for tokens via Auth service and return them
    to the caller. A real system would set cookies, etc.
    """
    redirect_uri = os.environ.get(
        "CHINTA_AUTH_CALLBACK_URL",
        "http://localhost:8084/auth/callback",
    )
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{AUTH_BASE_URL}/authenticate",
            json={
                "code": code,
                "redirect_uri": redirect_uri,
                "state": state,
                "nonce": nonce,
            },
            timeout=10.0,
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


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


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("CHINTA_GATEWAY_PORT", "8084"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)

