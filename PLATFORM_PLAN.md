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
- managed Postgres + Redis + message broker
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

## 13) Change Log

- v1 (2026-04-03): Initial plan created from architecture discussion.
