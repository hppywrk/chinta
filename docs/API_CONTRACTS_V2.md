# API Contracts v2 (Authz Matrix + Unified Decision)

Status: Draft v2  
Last updated: 2026-09-28  
Depends on: `docs/API_CONTRACTS_V1.md` (v1 remains valid; v2 is additive)

v2 closes the gap between **tenant commercial entitlements** (v1) and **per-request authorization** for **user × tenant × operation**. It introduces:

- A **grants matrix** (role × module × feature, with optional HTTP binding catalog).
- A **unified authz decision** endpoint for the gateway critical path.
- **Membership revisions** and cache-friendly invalidation metadata.
- **Structured decision logging** hooks (see `docs/LOGGING_OBSERVABILITY_V2.md`).

---

## 1) Design principles

1. **One composed decision per request** — gateway evaluates identity, routing, tenant state, commercial entitlements, and RBAC in one place (or one RPC), then caches the outcome.
2. **HTTP method is explicit in the contract** — `feature_code` remains the stable product permission; `http_method` + `route_template` tie gateway routes to features.
3. **Revisions, not pub/sub alone** — every cacheable dimension exposes a monotonic revision; events accelerate invalidation but TTL + revision compare remain mandatory.
4. **Deny by default** — missing grant, stale membership, or unknown route binding yields `allowed: false` with a machine-readable reason.

---

## 2) Grants matrix model

### 2.1 Dimensions

| Dimension | Source | Cache revision key |
|-----------|--------|-------------------|
| User membership | `platform.memberships` | `membership_revision` per `(tenant_id, user_id)` |
| Role grants | `authz.role_feature_grants` | `authz_catalog_revision` (global) |
| Tenant commercial access | entitlements service (v1) | `entitlements_revision` per `tenant_id` |
| Routing / freeze | routing service (v1) | `routing_version` per `tenant_id` |
| Tenant lifecycle policy | gateway config matrix (v1 B4.2) | `policy_config_version` (config hash) |

### 2.2 Evaluation order (normative)

For each request the gateway (or authz service) applies:

1. Authenticate JWT → `user_id`, optional JWT hints (`tid`, `roles`, `ent_v`, `mbr_v`).
2. Resolve **route binding** → `(module_code, feature_code, min_role_code)`.
3. Deny if **routing** blocks (missing target, `freeze_mode` + write class).
4. Deny if **tenant status policy** blocks (`SUSPENDED`, `DEPROVISIONED`, etc.).
5. Deny if **commercial entitlement** denies module/feature for tenant.
6. Deny if **membership** missing, not `ACTIVE`, or role below `min_role_code`.
7. Deny if **role × feature** matrix has no `ALLOW` (or explicit `DENY`).
8. Allow; attach limits and revision bundle to downstream headers.

`http_method` participates in step 2 (write vs read class) and in route binding lookup, not as a separate commercial dimension.

### 2.3 Role × feature catalog (control plane)

Stored in DB (`docs/CONTROL_PLANE_DDL_V2.sql`). Admin/internal APIs:

- `GET /v1/authz/catalog` — list modules, features, role grants (paginated).
- `PUT /v1/authz/role-grants` — replace grants for one `role_code` (bumps `authz_catalog_revision`).

v1 role codes remain: `owner`, `admin`, `member`, `viewer`.

Example grant row semantics:

- `viewer` + `notes` + `note.read` → `ALLOW`
- `viewer` + `notes` + `note.create` → absent → **deny** at step 7
- `member` + `notes` + `note.create` → `ALLOW`

---

## 3) Membership service (tenant registry extension)

Base path: `/v1/tenants/{tenant_id}/memberships`

### 3.1 List memberships

`GET /v1/tenants/{tenant_id}/memberships`

Response `200`:

```json
{
  "tenant_id": "a5f3f3d2-3e34-4c88-a08c-f114f357ddf9",
  "items": [
    {
      "user_id": "7d7a5f16-a948-4d39-b83d-d3219f7a2f80",
      "role_code": "admin",
      "membership_status": "ACTIVE",
      "membership_revision": 4
    }
  ]
}
```

### 3.2 Upsert membership

`PUT /v1/tenants/{tenant_id}/memberships/{user_id}`

Request:

```json
{
  "role_code": "member",
  "membership_status": "ACTIVE"
}
```

Behavior:

- Increments `membership_revision` for `(tenant_id, user_id)`.
- Emits `platform.membership.updated.v1` (see messaging v2 delta).
- Owner role: at least one `owner` with `ACTIVE` membership must remain.

Response `200`:

```json
{
  "tenant_id": "a5f3f3d2-3e34-4c88-a08c-f114f357ddf9",
  "user_id": "7d7a5f16-a948-4d39-b83d-d3219f7a2f80",
  "role_code": "member",
  "membership_status": "ACTIVE",
  "membership_revision": 5
}
```

### 3.3 Remove membership

`DELETE /v1/tenants/{tenant_id}/memberships/{user_id}`

Sets status `REMOVED`, bumps revision, emits event.

---

## 4) Unified authz decision (gateway critical path)

Base path: `/v1/authz`

Preferred endpoint (supersedes calling v1 resolve alone on the gateway hot path):

### 4.1 Decide access

`POST /v1/authz/decide`

Request:

```json
{
  "tenant_id": "a5f3f3d2-3e34-4c88-a08c-f114f357ddf9",
  "user_id": "7d7a5f16-a948-4d39-b83d-d3219f7a2f80",
  "module_code": "notes",
  "feature_code": "note.create",
  "http_method": "POST",
  "route_template": "/api/notes",
  "at_time": "2026-09-28T12:00:00Z",
  "client_revisions": {
    "entitlements_revision": 12,
    "routing_version": 9,
    "membership_revision": 5,
    "authz_catalog_revision": 3
  }
}
```

Notes:

- `client_revisions` is optional; when present and stale vs server, server returns fresh revisions even on cache hit path.
- `route_template` must match gateway binding catalog entry (normalized path template, not raw URL with IDs).

Response `200` (allowed):

```json
{
  "allowed": true,
  "decision_reason": "GRANTED",
  "effective_role_code": "member",
  "effective_state": {
    "tenant_status": "ACTIVE_SHARED",
    "platform_access": "ACTIVE",
    "module_access": "ACTIVE"
  },
  "limits": {
    "note_count_max": 10000
  },
  "revisions": {
    "entitlements_revision": 12,
    "routing_version": 9,
    "membership_revision": 5,
    "authz_catalog_revision": 3
  },
  "cache_ttl_seconds": 45,
  "cache_key_hint": "authz:v2:a5f3f3d2-3e34-4c88-a08c-f114f357ddf9:7d7a5f16:notes:note.create:POST"
}
```

Response `200` (denied — still 200 from decision service; gateway maps to 403):

```json
{
  "allowed": false,
  "decision_reason": "ROLE_FEATURE_DENIED",
  "effective_role_code": "viewer",
  "revisions": {
    "entitlements_revision": 12,
    "routing_version": 9,
    "membership_revision": 5,
    "authz_catalog_revision": 3
  },
  "cache_ttl_seconds": 30,
  "cache_key_hint": "authz:v2:..."
}
```

Decision reason codes (v2 additions to v1 catalog):

| Code | Meaning |
|------|---------|
| `MEMBERSHIP_NOT_FOUND` | No membership for user in tenant |
| `MEMBERSHIP_INACTIVE` | Status not `ACTIVE` |
| `ROLE_INSUFFICIENT` | Role below route `min_role_code` |
| `ROLE_FEATURE_DENIED` | Role × feature matrix denies |
| `ROUTE_UNBOUND` | No gateway binding for method + template |
| `STALE_CLIENT_REVISION` | Hint only; server still returns authoritative revisions |

v1 `POST /v1/entitlements/resolve` remains for **tenant-only** checks and admin tools; gateway should prefer `/v1/authz/decide` for user-facing traffic.

---

## 5) Gateway route binding catalog

Not HTTP on control plane in MVP: **versioned YAML** loaded by gateway (`gateway-route-bindings.yml`), validated at startup.

Schema (conceptual):

```yaml
version: 2
policy_config_version: "2026-09-28T00:00:00Z"
bindings:
  - methods: [GET]
    path_template: /api/notes
    module_code: notes
    feature_code: note.read
    min_role_code: viewer
    operation_class: read
  - methods: [POST]
    path_template: /api/notes
    module_code: notes
    feature_code: note.create
    min_role_code: member
    operation_class: write
```

Rules:

- First matching binding wins (order matters); CI test ensures no ambiguous overlaps.
- `operation_class: write` is denied when routing returns `freeze_mode=true` (v1 behavior).
- Changing the file bumps `policy_config_version`; gateway clears local binding cache.

Future (backlog): persist bindings in `authz.route_bindings` for dynamic admin UI.

---

## 6) Gateway integration contract (v2)

`chinta-gateway` should:

1. Validate JWT; extract `sub`, optional `tid`, `roles`, `ent_v`, `mbr_v`.
2. Resolve route binding → module, feature, min role, operation class.
3. Call `POST /v1/authz/decide` with `user_id`, tenant, module, feature, method, template (cached — see backlog **B2V.3**).
4. On deny → 403 with v1/v2 error envelope; log `authz.decision` (see logging spec).
5. Forward with v1 headers plus:
   - `X-Membership-Revision`
   - `X-Authz-Catalog-Revision`
   - `X-Effective-Role`

Cache:

- Key: `cache_key_hint` or structured tuple from response.
- TTL: `cache_ttl_seconds` from response.
- Invalidation: subscribe to `entitlements.revision.bumped.v1`, `platform.membership.updated.v1`, `platform.runtime-target.activated.v1`, `authz.catalog.updated.v1`; purge by tenant and/or global catalog revision.

---

## 7) JWT claim contract (v2 extension)

Adds to v1 claims (`tid`, `roles`, `tst`, `ent_v`):

| Claim | Description |
|-------|-------------|
| `mbr_v` | Membership revision for active `tid` + `sub` at token issue time |
| `authz_cv` | Optional snapshot of `authz_catalog_revision` at issue time |

Token issue / tenant switch must refresh `mbr_v`. Short access token TTL (e.g. 15m) limits stale RBAC exposure; gateway cache TTL must be ≤ min(token TTL, decision TTL).

---

## 8) Error code catalog (v2 additions)

- `MEMBERSHIP_NOT_FOUND` → 403
- `MEMBERSHIP_INACTIVE` → 403
- `ROLE_INSUFFICIENT` → 403
- `ROLE_FEATURE_DENIED` → 403
- `ROUTE_UNBOUND` → 500 (misconfiguration) or 404 (product choice; gateway should fail startup on unbound routes in strict mode)

---

## 9) Non-goals for v2

- Per-resource ACLs (row-level grants inside modules).
- ABAC with arbitrary attribute expressions.
- Cross-tenant delegated access.
- Dynamic route binding admin UI (YAML + CI is enough for v2).
