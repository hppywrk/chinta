# Multi-Tenant Microservices Platform Plan

Status: Draft v1 (editable)
Owner: Platform team
Last updated: 2026-04-03

## 1) Goal

Build a multi-tenant microservices platform with:

- A shared backbone platform (auth, routing, entitlements, billing, security, observability).
- An app/module layer where product modules run independently.
- A subscription model with platform-level and module-level trials.
- A billing model that supports both fixed and usage-based pricing.
- A tenant promotion path from shared runtime to dedicated runtime.

## 2) Architecture Overview

### 2.1 Backbone (Control Plane)

Services:

- Auth service (OIDC, JWT issuance, tenant-aware identity)
- Gateway (edge routing, policy enforcement, tenant context propagation)
- Tenant registry (tenant lifecycle and routing metadata)
- Entitlements service (module access decisions)
- Billing service (invoicing, payment status, usage ingestion)
- Messaging backbone (NATS JetStream for async event flow)
- Audit/observability services (logs, traces, metrics, audit events)

### 2.2 App Layer (Runtime Plane)

- Modules are independent services (tasks, notes, search, etc.).
- Each module owns its data model and exposes stable APIs.
- Modules rely on gateway/auth for identity and on entitlements for access checks.

## 3) Tenancy Model

Primary model: **schema-per-tenant** in shared Postgres runtime.

Control-plane data remains in shared schemas:

- `platform`
- `entitlements`
- `billing`
- `audit`

Tenant runtime data lives in schemas like `t_<tenant_id>`.

## 4) Tenant Lifecycle and Runtime Tiers

Tenant statuses:

- `TRIAL_SHARED`
- `ACTIVE_SHARED`
- `MIGRATING_TO_DEDICATED`
- `ACTIVE_DEDICATED`
- `PAST_DUE`
- `SUSPENDED`
- `DEPROVISIONED`

Runtime tiers:

- Shared runtime (default)
- Dedicated runtime (promoted tenants)

## 5) Trials and Subscription Semantics

The platform supports:

- Platform-wide trial windows
- Module-level trial windows
- Paid plan subscriptions
- Module add-ons

Access decision logic:

1. Validate tenant state (deny if suspended/deprovisioned).
2. Validate platform entitlement (active or trial).
3. Validate module entitlement (subscribed or module trial).
4. Apply billing policy (for grace period, past due, etc.).
5. Return effective access and limits.

## 6) Promotion to Dedicated Runtime (Freeze-and-Move)

Migration workflow:

1. Set tenant state to `MIGRATING_TO_DEDICATED`.
2. Gateway applies freeze/read-only policy for that tenant.
3. Provision dedicated runtime + database.
4. Apply baseline migrations.
5. Copy tenant data from shared schema.
6. Validate counts/checksums/schema version.
7. Switch tenant routing target to dedicated runtime.
8. Mark tenant as `ACTIVE_DEDICATED` and unfreeze traffic.

## 7) Security and Service-to-Service Authorization

- JWT validation at gateway.
- Tenant-scoped claims (`tenant_id`, roles, entitlement version).
- Internal service identity (mTLS or signed service tokens).
- Policy-controlled service-to-service calls.
- Full audit trail for authz-sensitive actions.

### 7.1 Messaging broker decision and eventing model

Detailed specification: `docs/MESSAGING_ARCHITECTURE_V1.md`

- Preferred broker: **NATS JetStream** for MVP and early growth.
- Async messaging is used for side effects, billing usage flow, audit fan-out, and workflow signals.
- Critical user request path remains synchronous at gateway/auth/entitlements.
- Delivery model is at-least-once with idempotent producers/consumers.
- Postgres-backed services use an outbox pattern to avoid dual-write inconsistency.
- DLQ and replay are mandatory for operational recovery.

## 8) Data and Migration Strategy

- Single migration source per module.
- Migration runner supports:
  - one tenant
  - all shared tenants in batches
  - dedicated target migration
- Track migration version per tenant schema.
- All migrations must be resumable and idempotent.

## 9) CI/CD and Deployment

CI per service:

- lint + static checks
- tests + contract checks
- image build + security scan

CD:

- staged deploy
- migration gate
- smoke tests
- progressive rollout and rollback controls

Deployment target:

- Kubernetes preferred
- managed Postgres + Redis + **NATS JetStream**
- centralized logging/metrics/traces

## 10) Initial Implementation Sequence (Repo-Oriented)

1. Stabilize and harden `chinta-auth` and `chinta-gateway`.
2. Add tenant registry service + control-plane schema.
3. Add entitlements service (platform/module trials).
4. Add gateway middleware for tenant state and entitlement checks.
5. Add schema provisioning + tenant migration runner.
6. Add minimal billing ingestion and invoice generation.
7. Add dedicated promotion worker (freeze/move/switch).
8. Add end-to-end tests for trial -> paid -> dedicated flow.

## 11) Immediate Backlog (Next Iteration)

- Define v1 control-plane SQL DDL.
- Define API contracts:
  - tenant registry
  - entitlements decision endpoint
  - runtime routing lookup
- Add JWT claim contract for tenant context.
- Add gateway policy matrix for tenant states.
- Create first end-to-end integration test path.

## 12) Open Questions

- Dedicated runtime scope: modules + DB only, or full backbone copy?
- Which billing provider is first (Stripe or custom adapter)?
- What is acceptable freeze duration during dedicated promotion?
- Which modules launch in v1?
- At what scale do we introduce Kafka as an additional analytics/event-lake pipeline?

## 13) Iterative Subsystem Development Strategy (MVP -> Stable)

Complex subsystems (migration orchestration, dedicated promotion, billing) are delivered in maturity levels so the platform can ship a useful MVP early and harden over time.

Delivery principles:

- Keep one production path that works early, then add safety and automation in layers.
- Make advanced orchestration optional behind feature flags until it is proven.
- Prefer operator-assisted workflows first, then automate once behavior is understood.

Migration subsystem maturity:

Detailed specification: `docs/MIGRATION_SYSTEM_V1.md`

- **M0 (MVP):**
  - single-tenant and small-batch schema migrations
  - explicit operator command execution
  - basic migration ledger (`pending`, `running`, `succeeded`, `failed`)
- **M1 (Operational):**
  - batch execution across shared tenants
  - resumable runs with retry policy and lock guards
  - preflight checks and dry-run reports
- **M2 (Extensible):**
  - data migration hooks and script packaging conventions
  - module-owned migration bundles validated by CI
  - richer observability and failure diagnostics
- **M3 (Stabilized):**
  - progressive rollout (canary tenants first)
  - automated rollback playbooks for failed releases
  - SLO-backed migration orchestration

Dedicated promotion maturity:

- **P0 (MVP):** freeze-and-move via controlled maintenance workflow.
- **P1:** automated orchestration job with validation suite and rollback command.
- **P2:** reduced downtime with delta sync and stricter cutover SLAs.

## 14) ORM/Data Access Layer as Reusable Architecture

The ORM/data layer should be a separate architectural layer so the backbone services can be reused in simpler deployments.

Layering model:

- **Domain/Application Layer:** business use-cases and policies, no ORM imports.
- **Repository Interfaces:** tenant-aware contracts owned by domain modules.
- **Data Access Adapter Layer:** ORM implementation (SQLAlchemy or equivalent), query builders, mapping rules.
- **Storage Infrastructure:** Postgres schemas, migrations, pooling, indexing.

Design requirements:

- Tenant context is injected by a `TenantContextProvider`, not manually threaded through every query.
- Repositories receive a `UnitOfWork` abstraction so business code is ORM-agnostic.
- Mapping definitions live in adapter packages; domain entities stay persistence-neutral.
- Migration scripts target the adapter contract, not framework internals.

Reusability profiles:

- **Profile A (Full multi-tenant):** schema-per-tenant + migration runner + promotion support.
- **Profile B (Simplified shared):** single schema + same domain services + minimal migration mode.
- **Profile C (Single-tenant product):** reuse auth/gateway/module contracts with simplified repository adapters.

This allows building a smaller MVP quickly while preserving the same control-plane and service contracts.

## 15) Change Log

- v1 (2026-04-03): Initial plan created from architecture discussion.
- v1.1 (2026-04-03): Added concrete v1 artifacts:
  - `docs/CONTROL_PLANE_DDL_V1.sql`
  - `docs/API_CONTRACTS_V1.md`
  - `docs/IMPLEMENTATION_BACKLOG_V1.md`
- v1.2 (2026-04-03): Added MVP-to-stable subsystem strategy and reusable ORM/data-layer architecture.
- v1.3 (2026-04-03): Added `docs/MIGRATION_SYSTEM_V1.md` with migration runner architecture, SDK contract, release workflow, and recovery model.
- v1.4 (2026-04-03): Added `docs/MESSAGING_ARCHITECTURE_V1.md` with broker decision (NATS JetStream), event contract, retries/DLQ, and rollout phases.
