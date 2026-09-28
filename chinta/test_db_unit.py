"""Pure unit tests (no database)."""
import pytest

from db import validate_tenant_id


def test_validate_tenant_id_accepts_safe_values():
    assert validate_tenant_id("acme") == "acme"
    assert validate_tenant_id("t1.dev") == "t1.dev"


def test_validate_tenant_id_rejects_empty():
    with pytest.raises(ValueError):
        validate_tenant_id("")
