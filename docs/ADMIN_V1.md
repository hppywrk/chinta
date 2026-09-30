# Admin tooling and platform service (v1)

Status: Draft  
Last updated: 2026-09-30

This document is the practical v1 slice for **tenant onboarding**, **platform users**, **memberships**, and a **CLI** that will not be thrown away when entitlements and v2 authz land.

Related specs:

- `docs/API_CONTRACTS_V1.md` (tenants, access resolve)
- `docs/CONTROL_PLANE_DDL_V1.sql` (`platform.tenants`, `platform.users`, `platform.memberships`)
- `docs/IMPLEMENTATION_BACKLOG_V1.md` (**B0.1**, **B1.1**, **B5.1**)

---

## Components

| Piece | Role in v1 |
|--------|------------|
| **chinta-platform** | HTTP control plane: tenants, users, memberships, `POST /v1/access/resolve` for the gateway. Provisions per-tenant note schemas on tenant create. |
| **chinta-admin** | Thin CLI over the platform admin API (`CHINTA_PLATFORM_URL`, `CHINTA_PLATFORM_ADMIN_TOKEN`). |
| **chinta-gateway** | When `CHINTA_PLATFORM_URL` is set: JWT validation, access resolve, forward `X-Tenant-Schema` / `X-Platform-User-Role` to the backend. |
| **chinta-backend** | Honors `X-Tenant-Schema`; `CHINTA_ENFORCE_PLATFORM=1` (compose default) disables lazy schema creation. |

Admin mutations use a **bootstrap admin token**, not end-user OIDC JWTs. User-facing traffic continues to use **chinta-auth**.

---

## Authentication

```
chinta-admin  --Authorization: Bearer <admin-token>-->  chinta-platform /v1/*
Browser/app   --Bearer OIDC + X-Tenant-Id: <slug>-->   gateway --> access resolve --> backend
```

Environment:

| Variable | Purpose |
|----------|---------|
| `CHINTA_PLATFORM_ADMIN_TOKEN` | Required on platform for mutating routes; CLI reads the same value. |
| `CHINTA_PLATFORM_DATABASE_URL` | PostgreSQL URL (same DB as notes runtime in dev). |
| `CHINTA_PLATFORM_URL` | CLI / gateway base URL (e.g. `http://localhost:8085`). |

---

## Client tenant identity

- **`X-Tenant-Id`** on API traffic: tenant **slug** (`acme`), not UUID.
- **`X-Tenant-Schema`**: authoritative PostgreSQL schema from `platform.tenants.schema_name` (gateway sets this after resolve).
- Schema naming matches notes backend: `sha256(slug)` → `t_<60 hex chars>` (see `chinta/db.py` and `chinta-platform/schema_naming.py`).

---

## CLI command map

Global flags: `--platform-url`, `--token`, `--output json|table` (env vars override defaults).

| Command | HTTP |
|---------|------|
| `user create --email … [--sub OIDC_SUB] [--name …]` | `POST /v1/users` |
| `user get --id UUID` | `GET /v1/users/{id}` |
| `user get --email …` | `GET /v1/users/by-email/{email}` |
| `tenant create --slug … --name … --owner-user-id UUID` | `POST /v1/tenants` |
| `tenant get --slug …` | `GET /v1/tenants/by-slug/{slug}` |
| `tenant list` | `GET /v1/tenants` |
| `member list --tenant SLUG` | `GET /v1/tenants/{id}/memberships` (CLI resolves slug) |
| `member set --tenant SLUG --user-id UUID --role member` | `PUT /v1/tenants/{id}/memberships/{user_id}` |
| `member remove --tenant SLUG --user-id UUID` | `DELETE /v1/tenants/{id}/memberships/{user_id}` |

### Bootstrap example

```bash
export CHINTA_PLATFORM_URL=http://localhost:8085
export CHINTA_PLATFORM_ADMIN_TOKEN=dev-admin-token-change-me

# Apply platform DDL once (see chinta-platform/migrations/001_platform_core.sql)
psql "$CHINTA_PLATFORM_DATABASE_URL" -f chinta-platform/migrations/001_platform_core.sql

python chinta-admin/cli.py user create --email you@example.com --sub "google-oauth2|…"
python chinta-admin/cli.py tenant create --slug demo --name "Demo" --owner-user-id "<uuid from user create>"
```

---

## Gateway middleware

When `CHINTA_PLATFORM_URL` is configured:

1. Require `X-Tenant-Id` on `/api/*`.
2. Validate JWT via auth `/userinfo` (unchanged).
3. `POST /v1/access/resolve` with `tenant_slug`, `user_external_subject` (= OIDC `sub`), `module_code=notes`, `operation=read|write`.
4. On deny → 403/404 with contract error codes.
5. Forward to backend: `X-Tenant-Id`, `X-Tenant-Schema`, `X-Platform-User-Role` (client-supplied schema headers are stripped).

If `CHINTA_PLATFORM_URL` is unset, gateway `/api` proxy behavior matches the pre-platform passthrough (used in some unit tests).

---

## Implementation status

| Item | Status |
|------|--------|
| `docs/ADMIN_V1.md` | This file |
| `chinta-platform` service | Health, admin auth, OpenAPI; store wired when DDL present |
| `chinta-admin` CLI | Commands above |
| Gateway resolve middleware | **Done** (`CHINTA_PLATFORM_URL` on gateway) |
| Backend `X-Tenant-Schema` + `CHINTA_ENFORCE_PLATFORM` | **Done** (compose defaults enforce on) |
| Full entitlements / NATS / v2 authz matrix | v2 |

---

## Suggested build order

1. **B0.1** — Apply `001_platform_core.sql` (or full `CONTROL_PLANE_DDL_V1.sql`) via migration tooling.
2. **B1.1** — Flesh out platform handlers + tests against PostgreSQL.
3. **chinta-admin** — Already calls live APIs.
4. **B_GW.1** (minimal) — Gateway access resolve + headers (**landed**; full entitlements path still backlog).
5. **B5.1** — Idempotent module migrations on tenant create (notes baseline today).
