# Messaging events v2 (delta)

Status: Draft v2  
Last updated: 2026-09-28  
Base: `docs/MESSAGING_ARCHITECTURE_V1.md`

Adds subjects for authz matrix invalidation and audit fan-out. Stream layout unchanged (`platform-events` still covers `platform.>` and `entitlements.>`; add `authz.>` to the same stream or document as `platform.authz.*` — below uses `platform.*` and `authz.*` prefixes).

---

## New subjects

| Subject | When emitted | Invalidation consumer |
|---------|--------------|------------------------|
| `platform.membership.updated.v1` | Membership upsert/remove | Gateway/authz cache: purge keys for `(tenant_id, user_id)` |
| `authz.catalog.updated.v1` | Role grant replace | Gateway/authz: global catalog purge or bump local `authz_cv` |
| `audit.action.recorded.v1` | After `audit.events` insert via outbox | SIEM / long-term archive (optional) |

### `platform.membership.updated.v1` payload (additive)

```json
{
  "tenant_id": "a5f3f3d2-3e34-4c88-a08c-f114f357ddf9",
  "user_id": "7d7a5f16-a948-4d39-b83d-d3219f7a2f80",
  "membership_revision": 5,
  "role_code": "member",
  "membership_status": "ACTIVE",
  "previous_role_code": "viewer"
}
```

### `authz.catalog.updated.v1` payload

```json
{
  "authz_catalog_revision": 4
}
```

---

## Gateway cache invalidation policy (normative)

1. **On message** — delete matching keys in L1 (in-process) and L2 (Redis if configured).
2. **On miss or after purge** — next request calls `POST /v1/authz/decide` uncached.
3. **TTL ceiling** — never exceed `cache_ttl_seconds` from last decision even if no event received.
4. **Revision guard** — if JWT `mbr_v` &lt; server `membership_revision` for write class operations, force refresh before allow.

Consumers must be idempotent (at-least-once delivery).
