# API Contracts v1 (Control Plane)

Status: Draft v1  
Last updated: 2026-04-03

This document defines initial service contracts for:

- Tenant Registry
- Entitlements Decision
- Runtime Routing

It is designed to be implemented behind `chinta-gateway` and consumed by module services.

## 1) Conventions

- API style: JSON over HTTPS.
- Authentication:
  - External/client endpoints: bearer JWT from `chinta-auth`.
  - Internal service endpoints: service JWT or mTLS identity.
- Correlation: accept and forward `X-Request-Id`.
- Time format: ISO-8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`).
- IDs: UUID strings.
- Errors:
  ```json
  {
    "error": {
      "code": "TENANT_NOT_FOUND",
      "message": "Tenant not found",
      "details": {}
    }
  }
  ```

## 2) Tenant Registry Service

Base path: `/v1/tenants`

### 2.1 Create tenant

`POST /v1/tenants`

Request:
```json
{
  "slug": "acme",
  "display_name": "Acme Inc",
  "owner_user_id": "7d7a5f16-a948-4d39-b83d-d3219f7a2f80",
  "platform_trial_days": 14
}
```

Behavior:
- Creates row in `platform.tenants` with status `TRIAL_SHARED`.
- Allocates deterministic schema name (for example `t_acme` or `t_<shortid>`).
- Adds owner membership role.
- Creates a default shared runtime target if needed.

Response `201`:
```json
{
  "tenant_id": "a5f3f3d2-3e34-4c88-a08c-f114f357ddf9",
  "slug": "acme",
  "status": "TRIAL_SHARED",
  "schema_name": "t_acme",
  "platform_trial_ends_at": "2026-04-17T00:00:00Z"
}
```

### 2.2 Get tenant

`GET /v1/tenants/{tenant_id}`

Response `200`:
```json
{
  "tenant_id": "a5f3f3d2-3e34-4c88-a08c-f114f357ddf9",
  "slug": "acme",
  "display_name": "Acme Inc",
  "status": "ACTIVE_SHARED",
  "current_target_type": "SHARED",
  "schema_name": "t_acme",
  "platform_trial_ends_at": "2026-04-17T00:00:00Z",
  "dedicated_target_id": null
}
```

### 2.3 Update tenant status (controlled transition)

`POST /v1/tenants/{tenant_id}/status-transitions`

Request:
```json
{
  "target_status": "MIGRATING_TO_DEDICATED",
  "reason": "paid-upgrade-dedicated"
}
```

Rules:
- Transition matrix is enforced server-side.
- Invalid transitions return `409`.

Response `200`:
```json
{
  "tenant_id": "a5f3f3d2-3e34-4c88-a08c-f114f357ddf9",
  "previous_status": "ACTIVE_SHARED",
  "current_status": "MIGRATING_TO_DEDICATED"
}
```

### 2.4 Register dedicated runtime target

`POST /v1/tenants/{tenant_id}/runtime-targets`

Request:
```json
{
  "target_type": "DEDICATED",
  "api_base_url": "https://acme-runtime.example.com",
  "db_dsn_secret_ref": "secret://prod/acme/dsn",
  "set_active": false
}
```

Response `201`:
```json
{
  "target_id": "840f8af1-92bf-4420-98da-e9a1539a293d",
  "tenant_id": "a5f3f3d2-3e34-4c88-a08c-f114f357ddf9",
  "target_type": "DEDICATED",
  "is_active": false
}
```

### 2.5 Switch active runtime target

`POST /v1/tenants/{tenant_id}/runtime-targets/{target_id}/activate`

Response `200`:
```json
{
  "tenant_id": "a5f3f3d2-3e34-4c88-a08c-f114f357ddf9",
  "active_target_id": "840f8af1-92bf-4420-98da-e9a1539a293d",
  "active_target_type": "DEDICATED"
}
```

## 3) Entitlements Service

Base path: `/v1/entitlements`

### 3.1 Resolve effective access (gateway critical path)

`POST /v1/entitlements/resolve`

Request:
```json
{
  "tenant_id": "a5f3f3d2-3e34-4c88-a08c-f114f357ddf9",
  "module_code": "tasks",
  "feature_code": "task.create",
  "at_time": "2026-04-03T12:00:00Z"
}
```

Response `200`:
```json
{
  "tenant_id": "a5f3f3d2-3e34-4c88-a08c-f114f357ddf9",
  "module_code": "tasks",
  "allowed": true,
  "decision_reason": "MODULE_TRIAL_ACTIVE",
  "effective_state": {
    "tenant_status": "TRIAL_SHARED",
    "platform_access": "TRIAL",
    "module_access": "TRIAL"
  },
  "limits": {
    "task_count_max": 5000
  },
  "entitlements_revision": 12,
  "cache_ttl_seconds": 60
}
```

Notes:
- Gateway should cache decision for `cache_ttl_seconds`.
- Include `entitlements_revision` in downstream headers for consistency checks.

### 3.2 Record trial (platform or module)

`POST /v1/entitlements/trials`

Request:
```json
{
  "tenant_id": "a5f3f3d2-3e34-4c88-a08c-f114f357ddf9",
  "scope": "MODULE",
  "module_code": "analytics",
  "starts_at": "2026-04-03T00:00:00Z",
  "ends_at": "2026-04-17T00:00:00Z"
}
```

Response `201`:
```json
{
  "trial_id": "b878cb61-8cb0-496f-a7f6-0fc52f8f7e47",
  "status": "ACTIVE"
}
```

### 3.3 Upsert subscription

`PUT /v1/entitlements/subscriptions/{tenant_id}`

Request:
```json
{
  "plan_code": "pro",
  "status": "ACTIVE",
  "period_start": "2026-04-01T00:00:00Z",
  "period_end": "2026-05-01T00:00:00Z",
  "source_ref": "sub_12345"
}
```

Response `200`:
```json
{
  "tenant_id": "a5f3f3d2-3e34-4c88-a08c-f114f357ddf9",
  "status": "ACTIVE",
  "entitlements_revision": 13
}
```

## 4) Routing Service

Base path: `/v1/routing`

### 4.1 Resolve runtime target for tenant

`GET /v1/routing/tenants/{tenant_id}/target`

Response `200`:
```json
{
  "tenant_id": "a5f3f3d2-3e34-4c88-a08c-f114f357ddf9",
  "tenant_status": "ACTIVE_SHARED",
  "freeze_mode": false,
  "target": {
    "target_type": "SHARED",
    "api_base_url": "https://shared-runtime.example.com",
    "schema_name": "t_acme"
  },
  "version": 9,
  "cache_ttl_seconds": 30
}
```

Behavior:
- If status is `MIGRATING_TO_DEDICATED`, return `freeze_mode=true`.
- Gateway can enforce read-only/deny policy from this field.

## 5) Gateway integration contract

`chinta-gateway` should:

1. Validate JWT and extract:
   - `sub` (user id)
   - `tid` (tenant id)
   - `roles`
   - `ent_v` (optional optimization)
2. Call routing target endpoint (cached).
3. Call entitlement resolve endpoint for module/feature.
4. Apply tenant state policy:
   - `SUSPENDED`, `DEPROVISIONED`: deny
   - `MIGRATING_TO_DEDICATED`: read-only or deny writes
   - `PAST_DUE`: restricted per configured policy
5. Forward to runtime with headers:
   - `X-Request-Id`
   - `X-Tenant-Id`
   - `X-Tenant-Schema` (shared runtime only)
   - `X-Entitlements-Revision`

## 6) Error code catalog (v1)

- `TENANT_NOT_FOUND` -> 404
- `TENANT_STATUS_BLOCKED` -> 403
- `INVALID_TENANT_STATUS_TRANSITION` -> 409
- `ENTITLEMENT_DENIED` -> 403
- `RUNTIME_TARGET_NOT_FOUND` -> 404
- `FREEZE_MODE_WRITE_BLOCKED` -> 423
- `VALIDATION_ERROR` -> 400
- `INTERNAL_ERROR` -> 500

## 7) Asynchronous event integration contract (v1)

Reference specification: `docs/MESSAGING_ARCHITECTURE_V1.md`

Guidelines:
- HTTP APIs above are source-of-truth command endpoints.
- Services emit async domain events after successful state changes.
- Event publication is at-least-once; consumers must be idempotent.
- For DB-backed producers, use outbox pattern for transactional consistency.

Initial event set tied to these APIs:
- tenant create/status/target activation endpoints emit `platform.*` events.
- subscription/trial updates emit `entitlements.*` events.
- usage ingest/invoice generation emit `billing.*` events.

## 8) Non-goals for v1

- Full OpenAPI generation in repo for every service.
- Complex pricing model APIs (tiered volume/proration details).
- Cross-region active-active routing semantics.
