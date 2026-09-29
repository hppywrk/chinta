"""Pure unit tests (no database)."""
import pytest

from db import (
    tenant_notes_index_name,
    tenant_schema_name,
    validate_tenant_id,
    validate_tenant_schema,
)


def test_validate_tenant_id_accepts_safe_values():
    assert validate_tenant_id("acme") == "acme"
    assert validate_tenant_id("t1.dev") == "t1.dev"


def test_validate_tenant_schema_accepts_platform_names():
    assert validate_tenant_schema("t_abc123def") == "t_abc123def"


def test_validate_tenant_schema_rejects_unsafe():
    with pytest.raises(ValueError):
        validate_tenant_schema("public")


def test_validate_tenant_id_rejects_empty():
    with pytest.raises(ValueError):
        validate_tenant_id("")


def test_tenant_schema_name_separates_hyphen_dot_underscore():
    """Folding -/. to _ used to map distinct tenants onto one schema."""
    names = {
        tenant_schema_name("acme-corp"),
        tenant_schema_name("acme.corp"),
        tenant_schema_name("acme_corp"),
    }
    assert len(names) == 3
    assert all(n.startswith("t_") and len(n) <= 63 for n in names)


def test_tenant_schema_name_stable_and_bounded():
    name = tenant_schema_name("acme-corp")
    assert name == tenant_schema_name("acme-corp")
    assert len(name) <= 63
    assert len(tenant_notes_index_name(name)) <= 63


def test_long_tenant_ids_do_not_collide_after_pg_ident_limit():
    """PG silently truncates identifiers to 63 bytes; naive t_<id> collided."""
    t1 = "a" + ("x" * 61) + "1"
    t2 = "a" + ("x" * 61) + "2"
    assert len(t1) == 63 and len(t2) == 63
    s1 = tenant_schema_name(t1)
    s2 = tenant_schema_name(t2)
    assert s1 != s2
    assert len(s1) <= 63 and len(s2) <= 63
    assert tenant_notes_index_name(s1) != tenant_notes_index_name(s2)
