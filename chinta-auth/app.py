"""
Chinta Auth — OpenID Connect authentication service using Authlib.
Interface described in api/auth-openapi.yml.
"""
import base64
import json
import os
from pathlib import Path
from urllib.parse import urljoin

import httpx
import yaml
from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi import FastAPI, HTTPException, Depends, Security
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

# OAuth 2.0 (RFC 6749 §5.1) requires these on any response that contains tokens.
_TOKEN_RESPONSE_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
}

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

def default_redirect_uri() -> str:
    """Public OAuth callback URL. IdPs never echo redirect_uri back on callback."""
    cfg = get_config()
    return cfg["redirect_uri_base"].rstrip("/") + "/auth/callback"


async def get_oidc_metadata() -> dict:
    """Fetch OIDC discovery document (.well-known/openid-configuration)."""
    global _oidc_metadata
    if _oidc_metadata is not None:
        return _oidc_metadata
    cfg = get_config()
    issuer = cfg["issuer"].rstrip("/")
    url = urljoin(issuer + "/", ".well-known/openid-configuration")
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        _oidc_metadata = resp.json()
    return _oidc_metadata


async def get_oidc_client(redirect_uri: str | None = None) -> AsyncOAuth2Client:
    """Create Authlib OIDC client with endpoints from discovery.

    Callers must ``await close_oidc_client(client)`` (or use try/finally) so the
    underlying httpx pool does not leak across /userinfo requests.
    """
    cfg = get_config()
    metadata = await get_oidc_metadata()
    redirect = redirect_uri or default_redirect_uri()
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


async def close_oidc_client(client: object) -> None:
    """Close Authlib/httpx client; no-op for test doubles without aclose."""
    aclose = getattr(client, "aclose", None)
    if aclose is None:
        return
    result = aclose()
    if hasattr(result, "__await__"):
        await result


def get_token_from_header(credentials: HTTPAuthorizationCredentials | None = Security(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    return credentials.credentials


def audiences_from_claims(claims: dict) -> set[str]:
    out: set[str] = set()
    aud = claims.get("aud")
    if isinstance(aud, str) and aud:
        out.add(aud)
    elif isinstance(aud, (list, tuple)):
        out.update(str(item) for item in aud if item)
    azp = claims.get("azp")
    if isinstance(azp, str) and azp:
        out.add(azp)
    return out


def decode_jwt_payload_unverified(token: str) -> dict | None:
    """Return JWT payload dict without verifying the signature, or None if not a JWT."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1]
    padded = payload + "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


async def assert_access_token_audience(access_token: str) -> None:
    """Reject access tokens that were not issued to this OIDC client.

    IdP ``/userinfo`` alone accepts any valid access token for that user, so a
    token minted for another OAuth app (same Google account) would authenticate
    to Chinta. Require azp/aud (introspection, JWT claims, or Google tokeninfo)
    to include ``OIDC_CLIENT_ID``.
    """
    cfg = get_config()
    client_id = (cfg["client_id"] or "").strip()
    if not client_id:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "oidc_not_configured",
                "error_description": "OIDC_CLIENT_ID is not set",
            },
        )

    metadata = await get_oidc_metadata()
    claims: dict | None = None

    introspection = metadata.get("introspection_endpoint")
    if introspection:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                introspection,
                data={"token": access_token, "token_type_hint": "access_token"},
                auth=(client_id, cfg["client_secret"] or ""),
                timeout=10.0,
            )
        if resp.status_code == 200:
            try:
                payload = resp.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                if payload.get("active") is False:
                    raise HTTPException(
                        status_code=401,
                        detail={
                            "error": "invalid_token",
                            "error_description": "Access token is inactive",
                        },
                    )
                claims = payload

    if claims is None:
        jwt_claims = decode_jwt_payload_unverified(access_token)
        if jwt_claims is not None and audiences_from_claims(jwt_claims):
            # Signature is not verified here; /userinfo still validates the
            # token with the IdP. Forged JWTs fail userinfo; foreign-app JWTs
            # fail the audience membership check below.
            claims = jwt_claims

    if claims is None:
        issuer = cfg["issuer"].rstrip("/").lower()
        if "accounts.google.com" in issuer or issuer.endswith("googleapis.com"):
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://oauth2.googleapis.com/tokeninfo",
                    params={"access_token": access_token},
                    timeout=10.0,
                )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=401,
                    detail={
                        "error": "invalid_token",
                        "error_description": "Access token failed Google tokeninfo",
                    },
                )
            try:
                claims = resp.json()
            except ValueError as exc:
                raise HTTPException(
                    status_code=401,
                    detail={
                        "error": "invalid_token",
                        "error_description": "Google tokeninfo returned non-JSON",
                    },
                ) from exc

    if claims is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_token_audience",
                "error_description": "Cannot verify access token audience for this IdP",
            },
        )

    if client_id not in audiences_from_claims(claims):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_token_audience",
                "error_description": "Access token was not issued to this client",
            },
        )


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
    try:
        authorize_url, _ = client.create_authorization_url(
            client.authorization_endpoint,
            redirect_uri=redirect_uri,
            state=state,
            nonce=nonce,
        )
    finally:
        await close_oidc_client(client)
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
    finally:
        await close_oidc_client(client)
    return JSONResponse(content=token, headers=_TOKEN_RESPONSE_HEADERS)


@app.get("/auth/callback")
async def auth_callback(
    code: str,
    redirect_uri: str | None = None,
    state: str | None = None,
    nonce: str | None = None,
):
    """
    Same as POST /authenticate but for GET (e.g. browser redirect with code in query).
    Keeps OAuth code exchange entirely inside auth service; gateway can proxy blindly.

    redirect_uri is optional: real IdPs only return code/state on the callback redirect.
    When omitted, use the configured public callback URL (same value sent at authorize time).
    """
    redirect = redirect_uri or default_redirect_uri()
    client = await get_oidc_client(redirect_uri=redirect)
    try:
        try:
            token = await client.fetch_token(
                client.token_endpoint,
                code=code,
                redirect_uri=redirect,
            )
        except Exception as e:
            raise HTTPException(
                status_code=401,
                detail={"error": "token_exchange_failed", "error_description": str(e)},
            )
    finally:
        await close_oidc_client(client)
    return JSONResponse(content=token, headers=_TOKEN_RESPONSE_HEADERS)


@app.get("/userinfo")
async def userinfo(access_token: str = Depends(get_token_from_header)):
    """Return OpenID Connect userinfo claims for the given access token."""
    await assert_access_token_audience(access_token)
    client = await get_oidc_client()
    try:
        if not client.userinfo_endpoint:
            raise HTTPException(
                status_code=501,
                detail={
                    "error": "userinfo_unsupported",
                    "error_description": "IdP has no userinfo endpoint",
                },
            )
        # Authlib's httpx AsyncOAuth2Client attaches the bearer via client.token;
        # get() does not accept a token= kwarg (TypeError on every /userinfo call).
        client.token = {"access_token": access_token, "token_type": "Bearer"}
        try:
            resp = await client.get(client.userinfo_endpoint)
            resp.raise_for_status()
            return resp.json()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=401,
                detail={"error": "userinfo_failed", "error_description": str(e)},
            )
    finally:
        await close_oidc_client(client)


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
