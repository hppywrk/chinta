"""
Chinta Auth — OpenID Connect authentication service using Authlib.
Interface described in api/auth-openapi.yml.
"""
import os
from pathlib import Path
from urllib.parse import urljoin

import httpx
import yaml
from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi import FastAPI, HTTPException, Depends, Security
from fastapi.openapi.utils import get_openapi
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from config import get_config

APP_DIR = Path(__file__).resolve().parent
API_SPEC_PATH = APP_DIR / "api" / "auth-openapi.yml"

app = FastAPI(
    title="Chinta Auth API",
    version="1.0.0",
    description="OpenID Connect authentication service",
)

security = HTTPBearer(auto_error=False)

# Cached OIDC metadata (authorization_endpoint, token_endpoint, userinfo_endpoint)
_oidc_metadata: dict | None = None


# --- Request/Response models (aligned with auth-openapi.yml) ---

class AuthenticateRequest(BaseModel):
    code: str
    redirect_uri: str
    state: str | None = None
    nonce: str | None = None


class AuthorizeUrlResponse(BaseModel):
    authorize_url: str
    state: str
    nonce: str | None = None


class ErrorResponse(BaseModel):
    error: str
    error_description: str | None = None


# --- OIDC discovery and client helpers ---

async def get_oidc_metadata() -> dict:
    """Fetch OIDC discovery document (.well-known/openid-configuration)."""
    global _oidc_metadata
    if _oidc_metadata is not None:
        return _oidc_metadata
    cfg = get_config()
    issuer = cfg["issuer"].rstrip("/")
    url = urljoin(issuer + "/", ".well-known/openid-configuration")
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        _oidc_metadata = resp.json()
    return _oidc_metadata


async def get_oidc_client(redirect_uri: str | None = None) -> AsyncOAuth2Client:
    """Create Authlib OIDC client with endpoints from discovery."""
    cfg = get_config()
    metadata = await get_oidc_metadata()
    redirect = redirect_uri or (cfg["redirect_uri_base"].rstrip("/") + "/callback")
    client = AsyncOAuth2Client(
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        redirect_uri=redirect,
        scope="openid profile email",
    )
    client.authorization_endpoint = metadata["authorization_endpoint"]
    client.token_endpoint = metadata["token_endpoint"]
    client.userinfo_endpoint = metadata.get("userinfo_endpoint")
    return client


def get_token_from_header(credentials: HTTPAuthorizationCredentials | None = Security(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    return credentials.credentials


# --- Routes ---

@app.get("/auth/authorize", response_model=AuthorizeUrlResponse)
async def get_authorize_url(
    redirect_uri: str,
    state: str | None = None,
    nonce: str | None = None,
):
    """Return OpenID Connect authorization URL for redirecting the user to the IdP."""
    import secrets
    state = state or secrets.token_urlsafe(32)
    nonce = nonce or secrets.token_urlsafe(32)
    client = await get_oidc_client(redirect_uri=redirect_uri)
    authorize_url, _ = client.create_authorization_url(
        client.authorization_endpoint,
        redirect_uri=redirect_uri,
        state=state,
        nonce=nonce,
    )
    return AuthorizeUrlResponse(
        authorize_url=authorize_url,
        state=state,
        nonce=nonce,
    )


@app.post("/authenticate")
async def authenticate(body: AuthenticateRequest):
    """Exchange authorization code for tokens."""
    client = await get_oidc_client(redirect_uri=body.redirect_uri)
    try:
        token = await client.fetch_token(
            client.token_endpoint,
            code=body.code,
            redirect_uri=body.redirect_uri,
        )
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail={"error": "token_exchange_failed", "error_description": str(e)},
        )
    return token


@app.get("/userinfo")
async def userinfo(access_token: str = Depends(get_token_from_header)):
    """Return OpenID Connect userinfo claims for the given access token."""
    client = await get_oidc_client()
    if not client.userinfo_endpoint:
        raise HTTPException(
            status_code=501,
            detail={"error": "userinfo_unsupported", "error_description": "IdP has no userinfo endpoint"},
        )
    token = {"access_token": access_token, "token_type": "Bearer"}
    try:
        resp = await client.get(client.userinfo_endpoint, token=token)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail={"error": "userinfo_failed", "error_description": str(e)},
        )


# --- Serve OpenAPI spec from YAML ---

@app.get("/openapi.json", include_in_schema=False)
async def openapi_json():
    """Serve OpenAPI schema. Built from api/auth-openapi.yml with FastAPI overlay."""
    with open(API_SPEC_PATH) as f:
        spec = yaml.safe_load(f)
    # Merge FastAPI-generated OpenAPI for accurate paths/servers if needed
    openapi_schema = get_openapi(
        title=spec["info"]["title"],
        version=spec["info"]["version"],
        description=spec["info"].get("description", ""),
        routes=app.routes,
    )
    # Prefer YAML spec for components and paths so interface is exactly as in yml
    openapi_schema["paths"] = spec.get("paths", openapi_schema["paths"])
    openapi_schema["components"] = spec.get("components", openapi_schema.get("components", {}))
    return openapi_schema


@app.get("/openapi.yaml", include_in_schema=False, response_class=PlainTextResponse)
async def openapi_yaml():
    """Serve OpenAPI schema as YAML."""
    with open(API_SPEC_PATH) as f:
        return f.read()


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8083"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
