"""Deterministic per-tenant PostgreSQL schema names (aligned with chinta/db.py)."""
from __future__ import annotations

import hashlib
import re

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PG_IDENT_MAX = 63


def validate_slug(slug: str) -> str:
    slug = slug.strip().lower()
    if not slug or not _SLUG_RE.match(slug):
        raise ValueError("invalid slug")
    return slug


def tenant_schema_name(slug: str) -> str:
    """Map tenant slug to a unique schema within PostgreSQL identifier limits."""
    validate_slug(slug)
    digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()
    name = f"t_{digest[:60]}"
    assert len(name) <= _PG_IDENT_MAX
    return name


def tenant_notes_index_name(schema: str) -> str:
    digest = hashlib.sha256(schema.encode("utf-8")).hexdigest()
    name = f"i_{digest[:60]}"
    assert len(name) <= _PG_IDENT_MAX
    return name
