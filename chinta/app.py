"""
Chinta backend — multi-tenant notes editor (PostgreSQL, schema-per-tenant).
Interface described in api/chinta-openapi.yml.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from auth_context import RequestContext, resolve_request_context
from config import get_config
from db import NotesStore, TenantSchemaNotFoundError, validate_tenant_id, validate_tenant_schema

APP_DIR = Path(__file__).resolve().parent
API_SPEC_PATH = APP_DIR / "api" / "chinta-openapi.yml"

_cfg = get_config()
_store = NotesStore(_cfg["database_url"], enforce_platform=_cfg["enforce_platform"])
_auth_url = _cfg["auth_url"]

app = FastAPI(
    title="Chinta API",
    version="1.0.0",
    description="Multi-tenant notes editor backend",
)


class NoteCreate(BaseModel):
    body: str = Field(..., min_length=0)


class NoteReplace(BaseModel):
    body: str = Field(..., min_length=0)


async def get_context(request: Request) -> RequestContext:
    ctx = await resolve_request_context(request, _auth_url)
    try:
        validate_tenant_id(ctx.tenant_id)
        if ctx.tenant_schema:
            validate_tenant_schema(ctx.tenant_schema)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ctx


def _handle_store_errors(exc: Exception) -> None:
    if isinstance(exc, TenantSchemaNotFoundError):
        raise HTTPException(status_code=404, detail="Tenant schema not found")
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc))
    raise exc


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/notes")
async def list_notes(ctx: RequestContext = Depends(get_context)):
    try:
        notes = _store.list_notes(ctx.tenant_id, ctx.user_id, ctx.tenant_schema)
    except (TenantSchemaNotFoundError, ValueError) as exc:
        _handle_store_errors(exc)
    return [n.as_dict() for n in notes]


@app.post("/notes", status_code=201)
async def create_note(payload: NoteCreate, ctx: RequestContext = Depends(get_context)):
    try:
        note = _store.create_note(ctx.tenant_id, ctx.user_id, payload.body, ctx.tenant_schema)
    except (TenantSchemaNotFoundError, ValueError) as exc:
        _handle_store_errors(exc)
    return note.as_dict()


@app.put("/notes/{note_id}")
async def replace_note(
    note_id: int,
    payload: NoteReplace,
    ctx: RequestContext = Depends(get_context),
):
    try:
        note = _store.replace_note(
            ctx.tenant_id, ctx.user_id, note_id, payload.body, ctx.tenant_schema
        )
    except (TenantSchemaNotFoundError, ValueError) as exc:
        _handle_store_errors(exc)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return note.as_dict()


@app.delete("/notes/{note_id}", status_code=204)
async def delete_note(note_id: int, ctx: RequestContext = Depends(get_context)):
    try:
        deleted = _store.delete_note(ctx.tenant_id, ctx.user_id, note_id, ctx.tenant_schema)
    except (TenantSchemaNotFoundError, ValueError) as exc:
        _handle_store_errors(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found")


@app.get("/openapi.json", include_in_schema=False)
async def openapi_json():
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
    with open(API_SPEC_PATH) as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("CHINTA_BACKEND_PORT", "8080"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
