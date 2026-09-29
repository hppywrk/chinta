# Logging and Observability v2

Status: Draft v2  
Last updated: 2026-09-28  
Depends on: v1 audit table (`audit.events` in `CONTROL_PLANE_DDL_V1.sql`); complements `MESSAGING_ARCHITECTURE_V1.md`

v1 delivers **audit persistence** in DDL and mentions metrics in messaging/backlog, but lacks a **platform-wide operational logging contract**. v2 defines that contract so authz, gateway, and control-plane services emit consistent, correlatable logs and metrics.

---

## 1) Goals

1. **Debug production** — trace a single `X-Request-Id` across gateway → authz → module.
2. **Security review** — every authz deny and sensitive allow is searchable without storing secrets.
3. **SLO operations** — cache hit rate, decision latency, log pipeline health.
4. **Compliance-ready audit** — distinguish **operational logs** (volume, short retention) from **audit events** (immutable, longer retention, `audit.events` + `audit.>` stream).

---

## 2) Log types

| Type | Purpose | Primary sink | Retention (default) |
|------|---------|--------------|---------------------|
| **Application** | Errors, startup, background jobs | stdout JSON → collector | 14–30 days |
| **Access / request** | One line per HTTP request (edge) | stdout + optional access index | 30 days |
| **Authz decision** | Allow/deny with reason codes | stdout + security index | 90 days |
| **Audit** | Legally/security sensitive mutations | Postgres `audit.events` + `audit.>` NATS | 1+ years (policy) |

Modules should not write audit rows directly for every read; use audit for **state changes** (membership change, subscription change, promotion).

---

## 3) Structured log format (application + access + authz)

All Python services (and new control-plane services) emit **one JSON object per line** to stdout.

Required fields:

| Field | Type | Description |
|-------|------|-------------|
| `ts` | string | ISO-8601 UTC |
| `level` | string | `DEBUG`, `INFO`, `WARN`, `ERROR` |
| `service` | string | `chinta-gateway`, `chinta-auth`, `authz`, `tenant-registry`, … |
| `msg` | string | Human-readable summary |
| `event` | string | Stable machine name, e.g. `http.request.completed`, `authz.decision` |

Correlation (include when known):

| Field | Description |
|-------|-------------|
| `request_id` | From `X-Request-Id` |
| `trace_id` | W3C `traceparent` trace id when tracing enabled |
| `span_id` | Current span |
| `tenant_id` | UUID |
| `user_id` | UUID (`sub`) |
| `duration_ms` | For completed requests/decisions |

Authz decision event (`event: authz.decision`):

```json
{
  "ts": "2026-09-28T12:00:01.123Z",
  "level": "INFO",
  "service": "chinta-gateway",
  "event": "authz.decision",
  "msg": "access denied",
  "request_id": "req-7eeabc",
  "tenant_id": "a5f3f3d2-3e34-4c88-a08c-f114f357ddf9",
  "user_id": "7d7a5f16-a948-4d39-b83d-d3219f7a2f80",
  "allowed": false,
  "decision_reason": "ROLE_FEATURE_DENIED",
  "module_code": "notes",
  "feature_code": "note.create",
  "http_method": "POST",
  "route_template": "/api/notes",
  "cache_hit": true,
  "duration_ms": 2
}
```

Never log: bearer tokens, passwords, full PII payloads, payment card data.

---

## 4) Central collection (reference architecture)

Deployment target (aligns with `PLATFORM_PLAN.md`):

```text
Service pods → stdout JSON
     ↓
Log agent (e.g. Fluent Bit / Alloy) on node or sidecar
     ↓
Central store (e.g. Loki, OpenSearch, or cloud logging)
     ↓
Dashboards + alerts (Grafana or equivalent)
```

Local / Compose profile **v2-logging**:

- Optional `loki` + `grafana` services in compose profile `observability`.
- All services set `CHINTA_LOG_FORMAT=json` (default in v2).

OpenTelemetry (optional v2 phase **B8V.2**):

- Trace gateway → authz → backend with shared `trace_id`.
- Export OTLP to collector; logs carry `trace_id` for jump from trace to log line.

---

## 5) Metrics (minimum set)

Expose Prometheus-style metrics from gateway and authz service:

| Metric | Labels | Use |
|--------|--------|-----|
| `authz_decisions_total` | `allowed`, `reason`, `service` | Deny rate spikes |
| `authz_decision_duration_seconds` | `cache_hit` | Latency SLO |
| `authz_cache_operations_total` | `op=hit\|miss\|evict` | Cache effectiveness |
| `http_requests_total` | `method`, `route`, `status` | Edge SLO |

Initial SLO ideas (v2):

- Gateway authz path p95 &lt; 50ms with cache hit rate &gt; 80% under steady load.
- Log delivery lag &lt; 60s p95 from emit to queryable in central store.

---

## 6) Audit integration

When a control-plane API mutates state (membership, subscription, tenant status):

1. Write domain row in transaction.
2. Insert `audit.events` row (`action` e.g. `membership.updated`).
3. Outbox → `audit.action.recorded.v1` for SIEM fan-out.

Operational logs reference audit via `audit_event_id` when both are written for the same action.

---

## 7) Implementation checklist (services)

| Service | Application logs | Access log | Authz decision log |
|---------|------------------|------------|-------------------|
| chinta-gateway | yes | yes | yes (per `/api/*`) |
| authz (new) | yes | yes (internal) | yes |
| chinta-auth | yes | yes | no (identity only) |
| tenant-registry | yes | yes | no |
| entitlements | yes | yes | optional (if resolve called directly) |
| chinta (notes) | yes | yes | no (trust gateway headers; log `tenant_id`, `user_id`) |

---

## 8) Non-goals for v2

- Full SIEM rule pack.
- Log-based billing metering (use `billing.usage_events`).
- Storing request/response bodies in logs.
