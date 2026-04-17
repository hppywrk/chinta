# Messaging Architecture v1

Status: Draft v1  
Last updated: 2026-04-03

This document defines message-broker strategy for the platform, including broker choice, event patterns, reliability model, and incremental rollout.

---

## 1) Recommendation

Preferred broker for this platform: **NATS JetStream**.

Why it is preferable for this project stage:
- lower operational overhead than Kafka for MVP and early growth
- strong support for pub/sub, durable consumers, replay, and at-least-once delivery
- very low latency for service-to-service async workflows
- simple fit for both shared runtime and dedicated runtime topologies
- easy local/dev setup

When to revisit this decision:
- if analytics/event volume grows into very high sustained throughput and long-retention stream-processing requirements, evaluate Kafka as an additional analytics/event-lake pipeline rather than replacing all operational messaging.

---

## 2) Broker options (decision summary)

### 2.1 NATS JetStream (chosen)
- Strengths:
  - simple operations and cluster management
  - high performance, low latency
  - durable streams and consumer state
  - straightforward subject-based routing
- Tradeoffs:
  - fewer built-in stream-processing ecosystem tools than Kafka

### 2.2 RabbitMQ
- Strengths:
  - mature queue semantics and routing options
  - good for classic work queues
- Tradeoffs:
  - stream/replay model less natural than JetStream/Kafka for event-first architecture
  - less attractive for future event-history/replay-heavy patterns

### 2.3 Kafka
- Strengths:
  - excellent ecosystem for large-scale event streaming and analytics
  - long retention and replay at scale
- Tradeoffs:
  - higher operational complexity for MVP
  - heavier platform burden early

---

## 3) Messaging responsibilities in this platform

Use async messaging for:
- side effects from synchronous API commands
- cross-service state propagation
- billing usage ingestion
- audit event fan-out
- long-running workflow orchestration signals

Keep synchronous HTTP/gRPC for:
- user request critical-path reads/writes requiring immediate consistency
- gateway authorization path (routing + entitlements decision)

Design rule:
- commands are synchronous
- events are asynchronous

---

## 4) Event contract (v1)

Use a stable envelope for all emitted events:

```json
{
  "event_id": "a0b6c2ef-3d3f-4a67-b07a-8ec17f1e35f9",
  "event_type": "tenant.created.v1",
  "event_version": 1,
  "occurred_at": "2026-04-03T12:00:00Z",
  "producer": "tenant-registry",
  "tenant_id": "a5f3f3d2-3e34-4c88-a08c-f114f357ddf9",
  "correlation_id": "req-7eeabc",
  "idempotency_key": "tenant-created:a5f3f3d2-3e34-4c88-a08c-f114f357ddf9:v1",
  "payload": {}
}
```

Contract rules:
- `event_id` unique per publish attempt
- `idempotency_key` stable for semantic deduplication
- `tenant_id` required for tenant-scoped events
- additive schema evolution only in v1 (do not remove/rename existing fields)
- consumers must ignore unknown fields

---

## 5) Subject and stream design (NATS JetStream)

Subject naming:
- `platform.tenant.created.v1`
- `platform.tenant.status-changed.v1`
- `entitlements.revision.bumped.v1`
- `billing.usage.recorded.v1`
- `billing.invoice.generated.v1`
- `migration.run.status-changed.v1`
- `module.tasks.task.created.v1`

Important multi-tenant rule:
- do **not** encode `tenant_id` in subject names (avoids unbounded subject cardinality)
- include `tenant_id` in envelope and use consumer-side filtering/authorization

Initial stream layout:
- `platform-events` (subjects `platform.>`, `entitlements.>`, `migration.>`)
- `billing-events` (subjects `billing.>`)
- `module-events` (subjects `module.>`)
- `audit-events` (subjects `audit.>`)

---

## 6) Delivery guarantees and processing model

Target guarantee: **at-least-once**.

Implications:
- producers and consumers must be idempotent
- consumers ack only after successful processing
- retries are expected behavior, not exceptional behavior

Ordering:
- no global ordering guarantee
- maintain logical ordering at consumer level per `(tenant_id, aggregate_id)` where needed

Exactly-once:
- not required in v1
- simulate effectively-once outcomes using idempotency keys + dedupe table + transactional writes

---

## 7) Reliability patterns

### 7.1 Outbox pattern (recommended for DB-backed services)

For services that write Postgres state and emit events:
1. write domain row(s)
2. write event row into local outbox table in same transaction
3. outbox publisher process sends event to NATS
4. mark outbox row as published

This avoids dual-write inconsistency.

### 7.2 Retry and dead-letter policy

Consumer strategy:
- immediate retries for transient failures (small count)
- exponential backoff retries
- move permanently failing messages to DLQ subject/stream

DLQ conventions:
- mirror original envelope + failure metadata (`error_code`, `error_message`, `attempt_count`)
- provide replay tooling after fix

### 7.3 Timeout and poison-message handling

- enforce max processing time per message
- cap retry count
- route poison messages to DLQ with alerting

---

## 8) Multi-tenant security and isolation considerations

- tenant identity is carried in event envelope (`tenant_id`)
- service credentials authorize publish/consume subjects
- consumers must verify tenant-level authorization before side effects
- audit sensitive event consumption paths
- avoid tenant-specific subject ACL explosion; prefer domain-level subject ACL + in-message tenant validation

Dedicated runtime note:
- control-plane events remain in shared broker initially
- dedicated module runtime may use dedicated broker only for tenant-local high-volume events (future optimization)

---

## 9) Initial event catalog (MVP)

Control-plane:
- `platform.tenant.created.v1`
- `platform.tenant.status-changed.v1`
- `platform.runtime-target.activated.v1`

Entitlements:
- `entitlements.subscription.updated.v1`
- `entitlements.trial.updated.v1`
- `entitlements.revision.bumped.v1`

Billing:
- `billing.usage.recorded.v1`
- `billing.invoice.generated.v1`
- `billing.payment.status-updated.v1`

Migration:
- `migration.run.started.v1`
- `migration.run-item.failed.v1`
- `migration.run.completed.v1`

---

## 10) Rollout phases (MVP -> stable)

### M0 (MVP)
- single NATS JetStream cluster
- basic streams and durable consumers
- outbox only for billing + tenant-registry events
- manual replay commands

### M1 (Operational)
- standardized outbox library for all DB-backed services
- retry/DLQ conventions enforced in shared consumer SDK
- event schemas in repo with compatibility checks

### M2 (Stabilized)
- consumer lag/error SLOs and alerts
- canary rollout for consumer version upgrades
- automated replay tooling with guardrails

---

## 11) Observability and SLOs

Track:
- publish success/failure rate
- consumer lag by stream/consumer
- retry count and DLQ ingress rate
- median and p95 end-to-end event latency

Initial SLO ideas:
- publish success >= 99.9%
- critical consumer lag < 60s (p95)
- DLQ ratio < 0.1% of consumed messages for critical domains

---

## 12) Implementation notes for this repo

- start with Docker Compose NATS JetStream for local development
- define shared event envelope package in Python services
- implement outbox in first two producers:
  - tenant registry
  - billing usage ingest path
- add integration test that verifies:
  1) API write
  2) outbox row creation
  3) event publish
  4) consumer side effect with idempotency

