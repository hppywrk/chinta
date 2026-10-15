from __future__ import annotations


def redact_bearer_token(value: str | None) -> str:
    """Return a safe placeholder for Authorization headers or raw tokens."""
    if not value:
        return ""
    stripped = value.strip()
    if not stripped:
        return ""
    if stripped.lower().startswith("bearer "):
        return "Bearer ***"
    return "***"
