"""
Chinta Platform — control plane for tenants, users, and memberships.
Interface described in api/platform-openapi.yml and docs/API_CONTRACTS_V1.md.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, AsyncIterator

import yaml
from fastapi import Depends, FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from admin_auth import require_admin
from config import get_config
from errors import api_error
from migrate import apply_platform_migrations
from store import PlatformStore

APP_DIR = Path(__file__).resolve().parent
API_SPEC_PATH = APP_DIR / "api" / "platform-openapi.yml"

_log = logging.getLogger("chinta-platform")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Apply platform DDL on startup so gateway /v1/access/resolve is usable."""
    url = get_config().database_url
    if url:
        try:
            apply_platform_migrations(url)
        except Exception:
            # Fail soft: /health stays up; mutating/resolve paths surface 503 via store.
            _log.exception("Platform DDL apply failed; admin/resolve will return 503 until fixed")
    yield


app = FastAPI(
    title="Chinta Platform API",
    version="1.0.0",
    description="Control plane for tenants, users, and memberships (v1 admin slice)",
    lifespan=lifespan,
)


def get_store() -> PlatformStore:
    url = get_config().database_url
    if not url:
        raise api_error(
            503,
            "PLATFORM_NOT_CONFIGURED",
            "CHINTA_PLATFORM_DATABASE_URL is not set",
        )
    return PlatformStore(url)


class CreateUserRequest(BaseModel):
    email: str
    display_name: str | None = None
    external_subject: str | None = None


class CreateTenantRequest(BaseModel):
    slug: str
    display_name: str
    owner_user_id: str


class UpsertMembershipRequest(BaseModel):
    role_code: str
    membership_status: str = "ACTIVE"


class AccessResolveRequest(BaseModel):
    tenant_slug: str
    user_external_subject: str
    module_code: str = "notes"
    operation: str = Field(description="read or write")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/v1/users", dependencies=[Depends(require_admin)])
def create_user(body: CreateUserRequest, store: Annotated[PlatformStore, Depends(get_store)]):
    return store.create_user(body.email, body.display_name, body.external_subject)


@app.get("/v1/users/{user_id}", dependencies=[Depends(require_admin)])
def get_user(user_id: uuid.UUID, store: Annotated[PlatformStore, Depends(get_store)]):
    return store.get_user(user_id)


@app.get("/v1/users/by-email/{email}", dependencies=[Depends(require_admin)])
def get_user_by_email(email: str, store: Annotated[PlatformStore, Depends(get_store)]):
    return store.get_user_by_email(email)


@app.post("/v1/tenants", status_code=201, dependencies=[Depends(require_admin)])
def create_tenant(body: CreateTenantRequest, store: Annotated[PlatformStore, Depends(get_store)]):
    try:
        owner_id = uuid.UUID(body.owner_user_id)
    except ValueError:
        raise api_error(400, "VALIDATION_ERROR", "owner_user_id must be a UUID")
    return store.create_tenant(body.slug, body.display_name, owner_id)


@app.get("/v1/tenants", dependencies=[Depends(require_admin)])
def list_tenants(
    store: Annotated[PlatformStore, Depends(get_store)],
    limit: int = 50,
):
    return {"items": store.list_tenants(limit=limit)}


@app.get("/v1/tenants/by-slug/{slug}", dependencies=[Depends(require_admin)])
def get_tenant_by_slug(slug: str, store: Annotated[PlatformStore, Depends(get_store)]):
    return store.get_tenant_by_slug(slug)


@app.get("/v1/tenants/{tenant_id}", dependencies=[Depends(require_admin)])
def get_tenant(tenant_id: uuid.UUID, store: Annotated[PlatformStore, Depends(get_store)]):
    return store.get_tenant(tenant_id)


@app.get("/v1/tenants/{tenant_id}/memberships", dependencies=[Depends(require_admin)])
def list_memberships(tenant_id: uuid.UUID, store: Annotated[PlatformStore, Depends(get_store)]):
    return store.list_memberships(tenant_id)


@app.put("/v1/tenants/{tenant_id}/memberships/{user_id}", dependencies=[Depends(require_admin)])
def upsert_membership(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    body: UpsertMembershipRequest,
    store: Annotated[PlatformStore, Depends(get_store)],
):
    return store.upsert_membership(
        tenant_id, user_id, body.role_code, body.membership_status
    )


@app.delete(
    "/v1/tenants/{tenant_id}/memberships/{user_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
def remove_membership(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    store: Annotated[PlatformStore, Depends(get_store)],
):
    store.remove_membership(tenant_id, user_id)


@app.post("/v1/access/resolve")
def access_resolve(body: AccessResolveRequest, store: Annotated[PlatformStore, Depends(get_store)]):
    """Gateway-facing read; no admin token (internal network in production)."""
    op = body.operation.strip().lower()
    if op not in ("read", "write"):
        raise api_error(400, "VALIDATION_ERROR", "operation must be read or write")
    return store.resolve_access(body.tenant_slug, body.user_external_subject, op)


@app.get("/openapi.yaml", include_in_schema=False)
async def openapi_yaml():
    if API_SPEC_PATH.is_file():
        return PlainTextResponse(API_SPEC_PATH.read_text(), media_type="application/yaml")
    return PlainTextResponse("paths: {}\n", media_type="application/yaml")


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    if API_SPEC_PATH.is_file():
        with API_SPEC_PATH.open() as f:
            app.openapi_schema = yaml.safe_load(f)
            return app.openapi_schema
    app.openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    return app.openapi_schema


app.openapi = custom_openapi
