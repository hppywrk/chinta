# Product slice v1

Status: Draft  
Last updated: 2026-10-08  
Owners: Platform / product

North-star for the **first deployable product**: localhost Docker Compose, browser login, notes UI, admin CLI, unit tests, and functional smoke—without waiting for billing, NATS, or the full control-plane backlog in `IMPLEMENTATION_BACKLOG_V1.md`.

Related:

- `docs/LOCAL_DEPLOY_V1.md` — copy-paste localhost runbook
- `docs/ADMIN_V1.md` — tenant/user CLI
- `docs/IMPLEMENTATION_BACKLOG_V1.md` — § Product track (execution order)
- `docs/LOGGING_OBSERVABILITY_V2.md` — full observability (v1 takes a thin subset)

---

## 1) Goals

| Goal | v1 outcome |
|------|------------|
| **UT / FT** | Pytest per service; CI smoke; compose-level functional test (planned) |
| **Core stack** | `chinta-db`, `chinta-auth`, `chinta-gateway`, `chinta-backend` (notes), `chinta-platform` (minimal control plane) |
| **Logging** | JSON structured logs on stdout in every Python service |
| **Log rotation** | Docker `json-file` driver limits per service in compose |
| **Metrics** | `GET /metrics` (Prometheus) per service + optional `prometheus` in compose |
| **Admin CLI** | `chinta-admin` (done) |
| **Web auth** | Simple login page (UI service) via gateway OAuth |
| **Notes UI** | Top 10 by date desc, textarea + submit, minimal CSS |
| **App shell** | Title `{company}: {module} - {user}`, module region, logout |
| **UI ownership** | Server-rendered pages from **`chinta-ui`** (planned) |
| **Deploy** | `docker compose` on localhost |

---

## 2) Out of scope (product v1)

Deferred to platform v1.5 / v2 (see `IMPLEMENTATION_BACKLOG_V1.md` tracks B and `IMPLEMENTATION_BACKLOG_V2.md`):

- NATS JetStream (B0.4), billing, dedicated-runtime promotion
- Full entitlements service and grants matrix
- Repository / `UnitOfWork` framework (B0.2), deployment profiles (B0.3)
- Loki/Grafana compose profile (optional later; subset of B8V.3)
- **chinta-net** C++ stack (`full-stack` compose profile)

---

## 3) Architecture (localhost)

```text
Browser → chinta-gateway :8084
            ├─ /auth/*     → chinta-auth :8083
            ├─ /api/*      → chinta-backend :8080 (+ platform access resolve)
            ├─ /me         → gateway → auth /userinfo
            └─ /           → redirect → chinta-ui :8086 (planned)

chinta-platform :8085 → PostgreSQL (platform schema)
chinta-backend    → PostgreSQL (per-tenant note schemas)

prometheus :9090  → scrapes /metrics on all services (planned)

chinta-admin (CLI) → chinta-platform admin API
```

**Human entry URL:** `http://localhost:8084`  
**OAuth redirect base:** `OIDC_REDIRECT_URI_BASE=http://localhost:8084` → callback `{base}/auth/callback`.

---

## 4) Functional requirements

### F1 — Web authentication

- Login page with a single **Sign in** action.
- Flow uses existing auth APIs proxied at gateway `/auth/*` (`GET /auth/authorize`, token exchange on callback).
- After login, UI establishes a **server-side session** (httpOnly cookie). Tokens must not be stored in `localStorage` for v1.
- Unauthenticated requests to shell or notes routes redirect to login.
- **Logout** clears the UI session and returns to login.

**Open design point (implementation epic E1/E2):** Auth callback today returns JSON. Product v1 adds a **browser completion** step (e.g. gateway or UI route that exchanges the code, sets the session cookie, redirects to `/app`).

### F2 — Application shell

- HTML `<title>`: `{company}: {module} - {display_name}`
  - `company`: `CHINTA_COMPANY_NAME` (default `Chinta`)
  - `module`: e.g. `Notes`
  - `display_name`: from `GET /me` (`name` or `email`)
- Layout: header (user identity) + **Logout** + **module content area** (notes embedded in v1; iframe optional later).
- Default module for v1: **Notes** only.

### F3 — Notes module UI

- List **10** most recently modified notes (`modified_at` descending).
- Textarea + **Submit** → create note via `POST /api/notes` with JSON `{"body": "..."}`.
- One static CSS file.
- Tenant: `X-Tenant-Id` header = tenant **slug**; v1 default `CHINTA_DEFAULT_TENANT_SLUG` (e.g. `demo`) after bootstrap.

### F4 — Notes API (backend)

- Existing CRUD under `/notes` (gateway: `/api/notes`).
- Add **`GET /notes?limit=10`** (cap optional max, default list behavior unchanged when `limit` omitted). OpenAPI updated in `chinta-openapi.yml`.

### F5 — Control plane (minimal)

- Keep `chinta-platform` when `CHINTA_ENFORCE_PLATFORM=1` (compose default).
- Bootstrap: platform DDL + `chinta-admin` user/tenant/membership (see `LOCAL_DEPLOY_V1.md`).

---

## 5) Non-functional requirements

### N1 — Structured logging

Each Python service logs **one JSON object per line** to stdout:

| Field | Required | Notes |
|-------|----------|--------|
| `ts` | yes | ISO-8601 UTC |
| `level` | yes | INFO, WARN, ERROR, … |
| `service` | yes | e.g. `chinta-gateway` |
| `msg` | yes | Short summary |
| `event` | yes | e.g. `http.request.completed` |
| `request_id` | when known | From `X-Request-Id` |
| `duration_ms` | on request completion | |

Environment:

- `CHINTA_LOG_FORMAT=json` (default in compose for product v1)
- `CHINTA_LOG_LEVEL=INFO`

Shared library: `chinta-observability` (or `packages/chinta_observability`) — epic E4.

### N2 — Log rotation (Compose)

Per-service logging driver:

```yaml
logging:
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"
```

### N3 — Metrics

- `GET /metrics` on auth, gateway, backend, platform, ui (Prometheus text exposition).
- Minimum: `http_requests_total`, `http_request_duration_seconds` (or equivalent), process uptime / `service_up`.
- Compose service **`prometheus`** with scrape config for all targets (epic E5).

### N4 — Tests

| Layer | Scope |
|-------|--------|
| **UT** | Per-service pytest; logging/metrics helpers; UI templates and session helpers |
| **FT** | `docker compose up` → health → seed tenant → notes via gateway; optional browser FT with real IdP |
| **CI** | Extend `.github/workflows/ci.yml` with `chinta-ui` tests and compose FT job when stable |

---

## 6) Configuration reference

See `docs/examples/deploy.local.env.example`.

| Variable | Purpose |
|----------|---------|
| `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | IdP client |
| `OIDC_REDIRECT_URI_BASE` | Public gateway origin (`http://localhost:8084`) |
| `CHINTA_PLATFORM_ADMIN_TOKEN` | Platform admin + CLI |
| `CHINTA_DEFAULT_TENANT_SLUG` | UI default tenant slug |
| `CHINTA_COMPANY_NAME` | Shell HTML title |
| `CHINTA_WEB_URL` / `CHINTA_UI_URL` | Gateway `GET /` redirect target (`http://localhost:8086`) |

---

## 7) Implementation backlog (product track)

Ordered epics; detail and DoD live in `IMPLEMENTATION_BACKLOG_V1.md` § Product track.

| Epic | Summary |
|------|---------|
| **E0** | Docs alignment (`PRODUCT_SLICE_V1`, `LOCAL_DEPLOY_V1`, env example) |
| **E1** | New `chinta-ui` (FastAPI + Jinja2 + static CSS) |
| **E2** | Compose + gateway integration (`chinta-ui`, logging driver, service list parity) |
| **E3** | Platform DDL on first boot + `scripts/seed-demo-tenant.sh` |
| **E4** | Shared JSON logging in all Python services |
| **E5** | Prometheus `/metrics` + compose `prometheus` |
| **E6** | `GET /notes?limit=` |
| **E7** | UT/FT and CI jobs |

**Suggested order:** E0 → E3 → E4/E5 (parallel) → E1 → E2 → E6 → E7.

---

## 8) Code change map (when implementing)

| Area | Action |
|------|--------|
| `chinta-ui/` | New service: templates, session, gateway client, Dockerfile, tests |
| `docker-compose.yml` | `chinta-ui`, `prometheus`, logging options, env wiring |
| `chinta-gateway/` | `CHINTA_WEB_URL`; optional `/ui` proxy; observability middleware |
| `chinta-auth`, `chinta`, `chinta-platform` | Logging + `/metrics` |
| `packages/chinta_observability/` | Shared logging and metrics |
| `chinta/app.py`, `chinta/db.py`, OpenAPI | `limit` query param |
| DB bootstrap | Apply `chinta-platform/migrations/001_platform_core.sql` on init or platform startup |
| `scripts/seed-demo-tenant.sh` | Demo user + tenant + membership |
| `deploy/prometheus.yml` | Scrape targets |
| `.github/workflows/ci.yml` | UI tests, compose FT |
| `scripts/deploy/vm-deploy.sh` | Align default services with product stack (platform + ui) |
| `AGENTS.md` | Ports, bootstrap, observability env |

---

## 9) Acceptance checklist (product v1 done)

- [ ] `docker compose up -d --build` with `.env` from example
- [ ] Platform DDL applied without manual `psql` (or documented one-liner until E3 lands)
- [ ] `./scripts/seed-demo-tenant.sh` succeeds
- [ ] Browser: login → shell title correct → notes list (≤10) → add note → logout
- [ ] `curl` health on 8083–8086; `curl` `/metrics` on each service
- [ ] Prometheus shows all targets up
- [ ] `pytest` green for all Python packages in CI
- [ ] Compose functional test green in CI
