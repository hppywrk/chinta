"""Last ACTIVE owner must survive upsert as well as delete (API_CONTRACTS_V2 §3.2)."""
from __future__ import annotations

import pytest

from store import would_orphan_last_active_owner


@pytest.mark.parametrize(
    ("existing_role", "existing_status", "new_role", "new_status", "owners", "expect"),
    [
        # Sole ACTIVE owner demoted → orphan
        ("owner", "ACTIVE", "member", "ACTIVE", 1, True),
        ("owner", "ACTIVE", "viewer", "ACTIVE", 1, True),
        ("owner", "ACTIVE", "admin", "ACTIVE", 1, True),
        # Sole ACTIVE owner soft-removed / suspended via upsert → orphan
        ("owner", "ACTIVE", "owner", "REMOVED", 1, True),
        ("owner", "ACTIVE", "owner", "SUSPENDED", 1, True),
        # Another ACTIVE owner remains → OK
        ("owner", "ACTIVE", "member", "ACTIVE", 2, False),
        ("owner", "ACTIVE", "owner", "REMOVED", 2, False),
        # Stays ACTIVE owner → OK
        ("owner", "ACTIVE", "owner", "ACTIVE", 1, False),
        # Non-owner changes cannot orphan
        ("member", "ACTIVE", "viewer", "ACTIVE", 1, False),
        ("owner", "SUSPENDED", "member", "ACTIVE", 0, False),
        # New membership (no existing row) cannot remove an owner
        (None, None, "member", "ACTIVE", 1, False),
        (None, None, "owner", "ACTIVE", 0, False),
    ],
)
def test_would_orphan_last_active_owner(
    existing_role, existing_status, new_role, new_status, owners, expect
):
    assert (
        would_orphan_last_active_owner(
            existing_role=existing_role,
            existing_status=existing_status,
            new_role=new_role,
            new_status=new_status,
            active_owner_count=owners,
        )
        is expect
    )
