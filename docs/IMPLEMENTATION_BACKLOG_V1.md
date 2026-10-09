# Implementation Backlog v1

Status: Draft v1  
Last updated: 2026-10-08

This file has **two execution tracks**. Use **Track A** for the first deployable product; use **Track B** for long-horizon control-plane and billing work.

| Track | Goal | Spec |
|-------|------|------|
| **A — Product slice v1** | Localhost Compose, browser login, notes UI, logging/metrics basics, UT/FT | `docs/PRODUCT_SLICE_V1.md`, `docs/LOCAL_DEPLOY_V1.md` |
| **B — Control plane expansion** | Registry, entitlements service, billing, NATS, promotion | Sections **0–8** below (original ordering) |

Track A does **not** block on Track B items such as B0.4 (NATS), billing (§7), or B0.2 (repository framework).

---

## Product track (Track A)

Reference: `docs/PRODUCT_SLICE_V1.md` §7. Suggested implementation order: **E0 → E3 → E4/E5 → E1 → E2 → E6 → E7**.

### E0 — Documentation and version alignment
Priority: P0  
Dependencies: none

Tasks:

- Maintain `docs/PRODUCT_SLICE_V1.md`, `docs/LOCAL_DEPLOY_V1.md`, `docs/examples/deploy.local.env.example`.
- Link product track from `AGENTS.md` and `docs/CI_CD.md`.

Definition of done:

- New contributors can find product v1 scope and localhost steps without reading the full control-plane backlog.

### E1 — `chinta-ui` service
Priority: P0  
Dependencies: E3 (bootstrap), E2 (compose)

Tasks:

- FastAPI + Jinja2 + static CSS; Dockerfile; port **8086**.
- Login, session cookie, shell layout, notes page, logout.
- Browser login completion for OAuth callback (see `PRODUCT_SLICE_V1.md` §F1).

Definition of done:

- Manual browser flow via `http://localhost:8084` creates a note in tenant `demo`.

### E2 — Gateway and Compose integration
Priority: P0  
Dependencies: E1

Tasks:

- Add `chinta-ui` to `docker-compose.yml`; set `CHINTA_WEB_URL`.
- Optional same-origin `/ui` proxy through gateway.
- Docker `json-file` log rotation on services.
- Align `scripts/deploy/vm-deploy.sh` default services with `x-chinta-vm.default_services`.

Definition of done:

- `docker compose up` brings UI up; `GET /` redirects to UI.

### E3 — Platform database bootstrap
Priority: P0  
Dependencies: none

Tasks:

- Apply `chinta-platform/migrations/001_platform_core.sql` on fresh DB (init script or platform entrypoint).
- `scripts/seed-demo-tenant.sh` for demo user + tenant.

Definition of done:

- Fresh volume: platform health OK and seed script succeeds without manual `psql`.

### E4 — Structured logging (product subset)
Priority: P1  
Dependencies: none

Tasks:

- Shared package (e.g. `packages/chinta_observability`) with JSON formatter and HTTP middleware.
- Wire into auth, gateway, backend, platform, ui.
- Env: `CHINTA_LOG_FORMAT`, `CHINTA_LOG_LEVEL`.

Definition of done:

- `docker compose logs` shows parseable JSON; unit test for `request_id` propagation.

### E5 — Metrics and Prometheus
Priority: P1  
Dependencies: E4 (optional)

Tasks:

- `GET /metrics` on each Python service.
- `prometheus` service + `deploy/prometheus.yml` in compose.

Definition of done:

- Prometheus UI shows all scrape targets up locally.

### E6 — Notes list limit
Priority: P2  
Dependencies: none

Tasks:

- `GET /notes?limit=` on backend; update `chinta-openapi.yml` and gateway proxy tests if needed.

Definition of done:

- UI can request exactly 10 notes without client-side truncation.

### E7 — Tests (UT + FT)
Priority: P1  
Dependencies: E1–E3

Tasks:

- `chinta-ui` pytest in CI.
- Compose functional test job (health, seed, notes via gateway).

Definition of done:

- CI green on PRs including product FT or documented interim smoke until FT is stable.

### Track A — Explicitly deferred to Track B / v2

| Product v1 skip | Track B / v2 item |
|-----------------|-------------------|
| NATS, billing, dedicated promotion | B0.4, §6–7 |
| Full entitlements service | B_GW.1 (beyond admin access resolve) |
| Loki/Grafana profile | `IMPLEMENTATION_BACKLOG_V2.md` B8V.3 |
| Grants matrix | `API_CONTRACTS_V2.md` |

---

## Control plane track (Track B)

Original backlog ordering for lowest-risk delivery and quickest path to full platform:

1) control-plane foundations  
2) gateway enforcement  
3) migration/promotion flows  
4) billing maturity

Additionally, complex subsystems are intentionally split into MVP-first and hardening tasks so delivery can start early without blocking on full automation.

---

## 0) Foundations and guardrails

### B0.1 Adopt control-plane schemas and migration tooling
Priority: P0  
Dependencies: none

Tasks:
- Add migration framework for shared schemas (`platform`, `entitlements`, `billing`, `audit`).
- Import `docs/CONTROL_PLANE_DDL_V1.sql` into migration chain.
- Add migration CI check (`up` on clean DB).

Definition of done:
- Fresh DB bootstrap succeeds in CI.
- Migration artifacts are versioned and repeatable.

### B0.2 Define architecture boundaries for data access layer
Priority: P0  
Dependencies: none

Tasks:
- Define repository and `UnitOfWork` interfaces in a shared package.
- Keep domain/application code free of ORM-specific imports.
- Define `TenantContextProvider` contract for tenant-aware query execution.

Definition of done:
- At least one service compiles and runs against interface-only data access contracts.
- Adapter swap (full ORM vs simplified adapter) is possible without domain changes.

### B0.3 Create deployment profiles (full vs simplified)
Priority: P1  
Dependencies: B0.2

Tasks:
- Define profile toggles: `full-multitenant`, `shared-simplified`, `single-tenant`.
- Document which components are mandatory/optional per profile.
- Add startup validation so invalid profile combinations fail fast.

Definition of done:
- Profile matrix is documented and executable in local/dev environments.
- CI runs at least one simplified profile smoke test.

### B0.4 Introduce messaging backbone baseline (NATS JetStream)
Priority: P0  
Dependencies: none

Reference specification: `docs/MESSAGING_ARCHITECTURE_V1.md`

Tasks:
- Provision NATS JetStream in local/dev and environment manifests.
- Define initial streams/subjects for platform, billing, module, and audit events.
- Define shared event envelope package and schema versioning conventions.

Definition of done:
- Platform services can publish/consume a test event end-to-end.
- Streams and durable consumers are created reproducibly from code/config.

### B0.5 Spec-driven OpenAPI guardrails
Priority: P1  
Dependencies: none (baseline landed in repo)

Reference: `docs/SPEC_DRIVEN_DEVELOPMENT.md`

Tasks:
- Run `scripts/validate_openapi_specs.py` in CI when GitHub Actions is added.
- Add Spectral ruleset for naming, operationIds, shared error schemas.
- Optional schemathesis smoke against auth/gateway `/openapi.json`.
- Optional drift check between registered HTTP routes and YAML paths.

Definition of done:
- PRs cannot merge with invalid OpenAPI YAML.
- Documented process for promoting `API_CONTRACTS_V1.md` sections to new `api/*-openapi.yml` files.

### B_GW.1 Gateway tenant and entitlements enforcement
Priority: P0  
Dependencies: B1.1, B2.1

Reference: `docs/API_CONTRACTS_V1.md` §5

Tasks:
- Resolve tenant context on `/api/*` (not v1 passthrough-only behavior).
- Call entitlements service on gateway critical path.
- Propagate `X-Tenant-Id`, `X-Request-Id`, and related headers to backend.
- **Partial (v1 admin slice):** when `CHINTA_PLATFORM_URL` is set, gateway calls `POST /v1/access/resolve`, requires `X-Tenant-Id` (slug), and forwards `X-Tenant-Schema` / `X-Platform-User-Role` (`docs/ADMIN_V1.md`). Full entitlements service still backlog.

Definition of done:
- Gateway OpenAPI updated with any new first-class routes or documented middleware behavior.
- Integration tests for denied vs allowed module access.

### B_GW.2 Gateway UI root redirect (`GET /`)
Priority: P2  
Dependencies: chinta-web availability

Tasks:
- Decide whether `/` remains a convenience redirect or moves behind a static CDN.
- If kept, add to `gateway-openapi.yml` or document as non-gateway concern.

Definition of done:
- Product decision recorded; spec and implementation aligned.

### B_AUTH.1 Document auth callback in OpenAPI
Priority: P2  
Dependencies: none

Tasks:
- Add `GET /auth/callback` to `auth-openapi.yml` or explicitly defer to gateway auth proxy only.

Definition of done:
- Auth spec matches all auth-owned entry points used in production login flows.

---

## 1) Tenant registry service

### B1.1 Implement tenant CRUD + status transitions
Priority: P0  
Dependencies: B0.1

Tasks:
- Create service endpoints from `API_CONTRACTS_V1.md` section 2.
- Enforce tenant status transition matrix server-side.
- Create owner membership at tenant creation.
- **In progress (skeleton):** `chinta-platform` + `chinta-admin` per `docs/ADMIN_V1.md` (users, memberships, access resolve; gateway wiring deferred).

Definition of done:
- API tests cover valid and invalid transitions.
- Tenant status cannot be updated outside transition API.

### B1.2 Implement runtime target registration and activation
Priority: P0  
Dependencies: B1.1

Tasks:
- Add create target endpoint (`SHARED`/`DEDICATED`).
- Enforce one active target per tenant.
- Add optimistic version field for routing cache invalidation.

Definition of done:
- Activation swaps target atomically.
- Concurrent activation requests are safe.

---

## 2) Entitlements service

### B2.1 Model modules/plans/subscriptions/trials
Priority: P0  
Dependencies: B0.1

Tasks:
- Implement module and plan catalog management (admin/internal APIs).
- Implement subscription upsert endpoint.
- Implement trial creation endpoint (platform and module scope).

Definition of done:
- Unit tests cover trial scope validation and period validation.
- Entitlement revision increments on any access-impacting update.

### B2.2 Implement resolve decision endpoint (gateway critical path)
Priority: P0  
Dependencies: B2.1, B1.1

Tasks:
- Compute effective access based on tenant status + subscription + trials.
- Return limits and TTL for gateway cache.
- Return explicit denial reason codes.

Definition of done:
- Performance target met for cached and uncached paths.
- Decision matrix tests pass for all tenant statuses.

---

## 3) chinta-auth updates

### B3.1 Enrich JWT claims with tenant context
Priority: P0  
Dependencies: B1.1, B2.2

Tasks:
- Include `tid`, `roles`, `tst` (tenant status), `ent_v` in JWT or token exchange response.
- Ensure multi-tenant users can choose active tenant safely.

Definition of done:
- Claims are cryptographically signed and documented.
- Integration test validates tenant switch behavior.

---

## 4) chinta-gateway policy enforcement

### B4.1 Add tenant routing and entitlement middleware
Priority: P0  
Dependencies: B2.2, B1.2, B3.1

Tasks:
- Validate token and resolve tenant runtime target.
- Resolve module/feature entitlement decision.
- Enforce freeze/read-only behavior for `MIGRATING_TO_DEDICATED`.
- Forward normalized internal headers.

Definition of done:
- Unauthorized requests are blocked with consistent error payloads.
- Middleware unit tests cover blocked and allowed states.

### B4.2 Add policy matrix config
Priority: P1  
Dependencies: B4.1

Tasks:
- Externalize state-policy matrix (config-driven).
- Add policy for `PAST_DUE` limits by module/feature.

Definition of done:
- Policy updates do not require code changes.
- Config validation prevents invalid state definitions.

---

## 5) Shared runtime schema provisioning and migration runner

Reference specification: `docs/MIGRATION_SYSTEM_V1.md`

### B5.1 Provision tenant schema on onboarding
Priority: P0  
Dependencies: B1.1

Tasks:
- Implement schema creation helper with strict schema naming rules.
- Apply baseline module migrations to new tenant schema.

Definition of done:
- New tenant has expected tables and indexes.
- Provisioning is idempotent.

### B5.2 Build batch migration runner for tenant schemas
Priority: P1  
Dependencies: B5.1

Tasks:
- CLI modes: single tenant, all shared tenants batch, dedicated target.
- Persist per-tenant module migration version.
- Add resumable failure handling and reporting.

Definition of done:
- Interrupted migration can resume without corruption.
- Dry-run mode reports planned work.

### B5.3 Add data migration SDK contract (MVP)
Priority: P2  
Dependencies: B5.2, B0.2

Tasks:
- Define migration script interface (version metadata, tenant context, transaction contract).
- Add packaging convention for module-provided schema/data migration bundles.
- Add runner support to execute both DDL and data backfill steps in order.

Definition of done:
- One reference module includes a data migration script executed by CI.
- Failed data migration marks tenant/module state clearly and supports retry.

### B5.4 Migration hardening stages (post-MVP)
Priority: P2  
Dependencies: B5.2

Tasks:
- Add canary-tenant rollout mode before full tenant batches.
- Add automatic pause thresholds (error rate, runtime, lock contention).
- Add rollback playbook commands and operator runbook docs.

Definition of done:
- Runner supports canary then full rollout strategy.
- Operators can pause/resume/rollback with audited commands.

---

## 6) Dedicated promotion worker (freeze/move/switch)

### B6.1 Implement promotion orchestrator
Priority: P1  
Dependencies: B1.2, B4.1, B5.2

Tasks:
- Transition to `MIGRATING_TO_DEDICATED`.
- Trigger runtime freeze/read-only.
- Execute data copy and validation checks.
- Activate dedicated target and mark `ACTIVE_DEDICATED`.

Definition of done:
- Full promotion runbook is automatable from one command/job.
- Rollback path tested (reactivate shared target).

### B6.2 Add consistency validation suite
Priority: P1  
Dependencies: B6.1

Tasks:
- Row counts by table.
- Optional checksums on key entities.
- Schema version parity checks.

Definition of done:
- Promotion fails safely if validation thresholds are not met.

---

## 7) Billing minimum viable implementation

### B7.1 Usage event ingestion
Priority: P1  
Dependencies: B0.1

Tasks:
- Internal API for usage event ingestion with idempotency key.
- Per-tenant/module aggregation jobs.

Definition of done:
- Duplicate event submissions do not double-charge.

### B7.2 Invoice generation (v1 simple)
Priority: P2  
Dependencies: B7.1, B2.1

Tasks:
- Generate monthly invoice drafts from subscription + usage.
- Produce line items by plan/module/usage.

Definition of done:
- Deterministic invoice output for same source period data.

### B7.3 Add billing outbox + async usage pipeline
Priority: P1  
Dependencies: B0.4, B7.1

Tasks:
- Implement Postgres outbox table and publisher worker for billing events.
- Emit `billing.usage.recorded.v1` and `billing.invoice.generated.v1`.
- Add idempotent consumer for aggregation path.

Definition of done:
- Duplicate deliveries do not alter final billed totals.
- Failed deliveries are retried and eventually sent to DLQ after threshold.

---

## 8) CI/CD and observability

### B8.1 Service CI templates
Priority: P0  
Dependencies: none

Tasks:
- Add lint/test/build/security scan pipeline per service.
- Add migration apply check per DB-touching service.

Definition of done:
- Required checks configured for protected branch merges.

### B8.2 Integration pipeline for trial -> paid -> dedicated
Priority: P1  
Dependencies: B4.1, B6.1

Tasks:
- Bring up ephemeral environment.
- Execute scripted flow:
  1) create tenant trial
  2) access module during trial
  3) convert to paid
  4) promote to dedicated
  5) validate continued access

Definition of done:
- Green integration run proves end-to-end lifecycle.

### B8.3 Messaging reliability and replay tooling
Priority: P1  
Dependencies: B0.4

Tasks:
- Add DLQ handling and replay command-line tooling.
- Add metrics for publish failures, consumer lag, retry counts, and DLQ rate.
- Add alerts for critical event flow degradation.

Definition of done:
- Operators can replay failed messages safely after fixes.
- Dashboards show stream health per domain and consumer group.

---

## 9) Deferred to v2 (explicit)

v1 intentionally omits a **platform logging contract** and a **user × tenant × operation grants matrix**. Those are specified in:

- `docs/IMPLEMENTATION_BACKLOG_V2.md`
- `docs/API_CONTRACTS_V2.md`
- `docs/LOGGING_OBSERVABILITY_V2.md`

---

## 10) Suggested first execution slice (smallest useful increment)

Target scope:
- B0.1, B1.1, B2.2 (minimal), B4.1 (minimal), B5.1

Outcome:
- New tenant can be created.
- Tenant schema is provisioned.
- Gateway allows/denies module access via entitlement decision.
- System is ready for one module to run in shared runtime.

---

## 11) Risks and mitigations

- Connection pool + tenant context leakage:
  - Mitigation: avoid global `search_path`; use explicit schema qualification or `SET LOCAL` in transaction.
- Migration blast radius across many schemas:
  - Mitigation: batch, canary tenants, resumable runner, detailed reporting.
- Policy drift between services:
  - Mitigation: central decision endpoint and shared error code catalog.
- Dedicated promotion downtime:
  - Mitigation: freeze protocol + strict validation + tested rollback.
- ORM lock-in / inability to reuse foundation:
  - Mitigation: strict repository interfaces, adapter isolation, and profile-based deployment modes.
- Message delivery duplication or backlog growth:
  - Mitigation: outbox pattern, idempotent consumers, retry/DLQ policy, and lag alerts.
