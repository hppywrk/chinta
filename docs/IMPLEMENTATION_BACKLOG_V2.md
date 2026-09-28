# Implementation Backlog v2

Status: Draft v2  
Last updated: 2026-09-28  
Prerequisite: v1 first execution slice green (see `IMPLEMENTATION_BACKLOG_V1.md` §9)

v2 delivers:

1. **Unified grants matrix** — user × tenant × feature (with HTTP route bindings).
2. **Decision cache + invalidation** — revisions, Redis-ready, event-driven purge.
3. **Platform logging system** — structured logs, collection profile, authz decision telemetry.

Reference specs:

- `docs/API_CONTRACTS_V2.md`
- `docs/CONTROL_PLANE_DDL_V2.sql`
- `docs/LOGGING_OBSERVABILITY_V2.md`
- `docs/MESSAGING_EVENTS_V2.md`

---

## 0) v1 gap explicitly deferred to v2

| Gap in v1 | v2 item |
|-----------|---------|
| No operational logging standard | **B8V.1**–**B8V.3** |
| User not in entitlement resolve | **B2V.1** `/v1/authz/decide` |
| No membership APIs / revision | **B1V.1**, DDL v2 |
| No role × feature matrix | **B2V.2**, DDL v2 |
| Gateway cache invalidation consumer unspecified | **B2V.3**, **B4V.2** |
| Route → feature mapping implicit | **B4V.1** |

---

## 1) Logging and observability foundation

### B8V.1 Shared structured logging library
Priority: P0  
Dependencies: none

Tasks:

- Add small Python package (e.g. `chinta_logging`) with JSON formatter, required fields, PII redaction helpers.
- Env: `CHINTA_LOG_FORMAT=json`, `CHINTA_LOG_LEVEL`.
- Wire into `chinta-auth`, `chinta-gateway`, `chinta` backend.

Definition of done:

- Every service emits parseable JSON lines on stdout.
- Unit test asserts `request_id` propagation on a sample handler.

### B8V.2 Access and authz decision logging at gateway
Priority: P0  
Dependencies: B8V.1, B4V.1 (route templates known)

Tasks:

- Log `http.request.completed` with status, duration, route template.
- Log `authz.decision` per `/api/*` with reason codes from v2 contract.
- Document fields in `LOGGING_OBSERVABILITY_V2.md` (keep in sync).

Definition of done:

- Integration test captures deny log line with `decision_reason`.
- No bearer token in log fixtures.

### B8V.3 Local observability compose profile
Priority: P1  
Dependencies: B8V.1

Tasks:

- Add compose profile `observability` (Loki + Grafana or documented alternative).
- Ship example dashboard: authz deny rate, request rate, p95 latency.

Definition of done:

- `docker compose --profile observability up` shows gateway logs in Grafana within 2 minutes.

### B8V.4 OpenTelemetry tracing (optional hardening)
Priority: P2  
Dependencies: B8V.1, B2V.1

Tasks:

- OTLP exporter env vars; instrument gateway → authz HTTP client.
- Correlate logs with `trace_id`.

Definition of done:

- Single trace visible across two hops in local Jaeger/Tempo.

### B8V.5 Audit outbox for membership mutations
Priority: P1  
Dependencies: B1V.1, B0.4

Tasks:

- On membership write: `audit.events` + outbox → `audit.action.recorded.v1`.

Definition of done:

- Test proves audit row and event for membership role change.

---

## 2) Authz catalog and membership

### B1V.1 Membership CRUD APIs
Priority: P0  
Dependencies: B0.1 (v1), DDL v2 applied

Reference: `API_CONTRACTS_V2.md` §3

Tasks:

- Implement list/upsert/delete under tenant registry (or dedicated membership module).
- Call `platform.bump_membership_revision` on every change.
- Emit `platform.membership.updated.v1` via outbox.

Definition of done:

- Cannot remove last active owner.
- API tests for revision increment.

### B2V.2 Role × feature grants catalog
Priority: P0  
Dependencies: DDL v2

Tasks:

- Seed default grants for notes module (viewer read, member write, admin delete).
- Internal `GET /v1/authz/catalog`, `PUT /v1/authz/role-grants`.
- Bump `authz.catalog_revision` on grant replace; emit `authz.catalog.updated.v1`.

Definition of done:

- Matrix unit tests for all four roles on notes features.
- DENY override wins over ALLOW.

### B2V.1 Authz decision service (`POST /v1/authz/decide`)
Priority: P0  
Dependencies: B2.2 (v1 entitlements), B1.1 (v1 tenants), B1V.1, B2V.2

Reference: `API_CONTRACTS_V2.md` §4

Tasks:

- Compose v1 routing + entitlements + membership + role matrix per evaluation order.
- Return revision bundle + `cache_ttl_seconds` + `cache_key_hint`.
- Emit metrics from `LOGGING_OBSERVABILITY_V2.md` §5.

Definition of done:

- Decision matrix integration tests: commercial deny, role deny, membership inactive, allow path.
- p95 uncached decision documented; cached path meets backlog target.

### B2V.3 Decision cache layer
Priority: P0  
Dependencies: B2V.1

Tasks:

- Gateway L1 cache (in-process LRU) keyed by `cache_key_hint`.
- Optional L2 Redis via `CHINTA_AUTHZ_CACHE_REDIS_URL` for multi-instance gateways.
- Honor TTL; compare client revisions when provided.

Definition of done:

- Cache hit/miss metrics exposed.
- Test: second identical request hits cache within TTL.

### B4V.2 Cache invalidation subscriber
Priority: P0  
Dependencies: B2V.3, B0.4 (v1 messaging)

Reference: `MESSAGING_EVENTS_V2.md`

Tasks:

- Durable consumer in gateway (or sidecar) for membership, entitlements revision, catalog, routing activation events.
- Purge L1/L2 keys by tenant and global catalog revision.

Definition of done:

- Test: membership update evicts cache; next request sees new role outcome.

---

## 3) Gateway route matrix

### B4V.1 Gateway route binding catalog
Priority: P0  
Dependencies: none (YAML)

Tasks:

- Add `chinta-gateway/config/gateway-route-bindings.yml` for notes API.
- Startup validation: every `/api/*` OpenAPI path has binding; no overlaps.
- Map proxy paths to module/feature/min_role/operation_class.

Definition of done:

- CI fails if gateway OpenAPI adds route without binding.
- Unbound route never proxies in strict mode.

### B4V.3 Gateway uses `/v1/authz/decide` on critical path
Priority: P0  
Dependencies: B4V.1, B2V.1, B2V.3, B3.1 (v1 JWT claims extended)

Tasks:

- Replace direct v1-only entitlement call with authz decide.
- Forward v2 headers (`X-Membership-Revision`, `X-Effective-Role`, …).
- Extend **B3.1** to issue `mbr_v`, optional `authz_cv`.

Definition of done:

- Viewer cannot POST note via gateway; member can.
- Integration test matches matrix.

### B4V.4 Policy config version for tenant state matrix
Priority: P1  
Dependencies: B4.2 (v1)

Tasks:

- Hash tenant state policy YAML → `policy_config_version`.
- Include in cache key for authz decisions affected by freeze/PAST_DUE rules.

Definition of done:

- Policy file change clears relevant cache entries on gateway reload.

---

## 4) Auth service and backend alignment

### B3V.1 JWT claims `mbr_v` and `authz_cv`
Priority: P0  
Dependencies: B1V.1, B2V.2, B3.1 (v1)

Tasks:

- On login and tenant switch, embed revisions from control plane.
- Document in auth OpenAPI extension or `API_CONTRACTS_V2.md` §7.

Definition of done:

- Tenant switch updates `mbr_v` in new token.

### B5V.1 Notes backend trusts gateway context (defense in depth light)
Priority: P2  
Dependencies: B4V.3

Tasks:

- Optional: reject writes if `X-Effective-Role` is viewer (header only if gateway signed internal token — or skip until mTLS).
- Minimum: structured logs with `tenant_id`, `user_id` per **B8V.1**.

Definition of done:

- Document trust boundary: gateway is SOA for external clients; modules may add checks later.

---

## 5) Suggested v2 execution slice

Target scope (after v1 slice):

- B8V.1, B8V.2  
- B1V.1, B2V.2, B2V.1  
- B4V.1, B4V.3, B2V.3  

Outcome:

- Observable gateway with authz allow/deny logs.
- Role matrix enforced for notes API.
- Cached decisions with TTL; manual test of membership invalidation.

Follow-on:

- B4V.2, B8V.3, B8V.5, B3V.1

---

## 6) Risks and mitigations (v2-specific)

- **Stale JWT roles after membership change** — Mitigation: `mbr_v` + short access token TTL + gateway revision check on writes.
- **Cache stampede on catalog bump** — Mitigation: single-flight refresh per key; short TTL on deny paths.
- **Log volume / cost** — Mitigation: sample DEBUG; full authz decision logs at INFO for denies, INFO sampled for allows (configurable).
- **Route binding drift from OpenAPI** — Mitigation: CI binding validator (**B4V.1**).
