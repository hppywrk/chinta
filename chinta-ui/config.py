"""Environment configuration for chinta-ui."""
from __future__ import annotations

import os


def get_config() -> dict[str, str]:
    mount = os.environ.get("CHINTA_UI_MOUNT_PATH", "/ui").strip() or "/ui"
    if not mount.startswith("/"):
        mount = f"/{mount}"
    mount = mount.rstrip("/") or "/ui"

    public = os.environ.get("CHINTA_PUBLIC_URL", "http://localhost:8084").rstrip("/")
    gateway = os.environ.get("CHINTA_GATEWAY_URL", "http://chinta-gateway:8084").rstrip("/")

    return {
        "mount_path": mount,
        "public_url": public,
        "gateway_url": gateway,
        "default_tenant_slug": os.environ.get("CHINTA_DEFAULT_TENANT_SLUG", "demo").strip() or "demo",
        "company_name": os.environ.get("CHINTA_COMPANY_NAME", "Chinta").strip() or "Chinta",
        "auth_url": os.environ.get("CHINTA_AUTH_URL", "http://chinta-auth:8083").rstrip("/"),
        "session_cookie": os.environ.get("CHINTA_SESSION_COOKIE", "chinta_access_token"),
        "port": os.environ.get("CHINTA_UI_PORT", "8086"),
    }
