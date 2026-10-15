"""
Chinta web UI — server-rendered login, app shell, and notes module.
Proxied at the gateway under CHINTA_UI_MOUNT_PATH (default /ui).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from chinta_observability import configure_logging, install_request_logging

from config import get_config
from gateway_client import GatewayError, create_note, fetch_me, list_notes

APP_DIR = Path(__file__).resolve().parent

SERVICE_NAME = "chinta-ui"
configure_logging(SERVICE_NAME)

app = FastAPI(title="Chinta UI", version="1.0.0")
install_request_logging(app, SERVICE_NAME)
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


def _url(path: str) -> str:
    base = get_config()["mount_path"].rstrip("/")
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}" if base else path


templates.env.globals["url"] = _url


def _access_token(request: Request) -> str | None:
    token = request.cookies.get(get_config()["session_cookie"])
    if token:
        return token
    return None


def _redirect_login() -> RedirectResponse:
    return RedirectResponse(_url("/login"), status_code=302)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return RedirectResponse(_url("/login"), status_code=302)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None):
    if _access_token(request):
        return RedirectResponse(_url("/app"), status_code=302)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"company_name": get_config()["company_name"], "error": error},
    )


@app.get("/auth/start")
async def auth_start():
    cfg = get_config()
    redirect_uri = f"{cfg['public_url']}/auth/callback"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{cfg['auth_url']}/auth/authorize",
            params={"redirect_uri": redirect_uri},
            timeout=10.0,
        )
    if resp.status_code != 200:
        return RedirectResponse(
            _url(f"/login?error=Could+not+start+sign-in"),
            status_code=302,
        )
    data = resp.json()
    return RedirectResponse(data["authorize_url"], status_code=302)


@app.get("/app", response_class=HTMLResponse)
async def app_shell(request: Request):
    token = _access_token(request)
    if not token:
        return _redirect_login()

    display_name = "User"
    notes: list[dict[str, Any]] = []
    error: str | None = None
    cfg = get_config()
    try:
        me = await fetch_me(cfg["gateway_url"], token)
        display_name = (me.get("name") or me.get("email") or me.get("sub") or "User").strip()
        notes = await list_notes(
            cfg["gateway_url"],
            token,
            cfg["default_tenant_slug"],
            limit=10,
        )
    except GatewayError as exc:
        if exc.status_code in (401, 403):
            response = _redirect_login()
            response.delete_cookie(cfg["session_cookie"], path="/")
            return response
        error = "Could not load notes. Try again later."

    page_title = f"{cfg['company_name']}: Notes - {display_name}"
    return templates.TemplateResponse(
        request,
        "app.html",
        {
            "company_name": cfg["company_name"],
            "module_name": "Notes",
            "display_name": display_name,
            "page_title": page_title,
            "notes": notes,
            "error": error,
        },
    )


@app.post("/notes")
async def notes_create(request: Request, body: str = Form(...)):
    token = _access_token(request)
    if not token:
        return _redirect_login()
    cfg = get_config()
    try:
        await create_note(cfg["gateway_url"], token, cfg["default_tenant_slug"], body)
    except GatewayError as exc:
        if exc.status_code in (401, 403):
            response = _redirect_login()
            response.delete_cookie(cfg["session_cookie"], path="/")
            return response
    return RedirectResponse(_url("/app"), status_code=303)


@app.get("/logout")
async def logout():
    cfg = get_config()
    response = RedirectResponse(_url("/login"), status_code=302)
    response.delete_cookie(cfg["session_cookie"], path="/")
    return response


if __name__ == "__main__":
    import uvicorn

    port = int(get_config()["port"])
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
