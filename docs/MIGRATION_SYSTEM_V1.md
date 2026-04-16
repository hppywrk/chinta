# Migration System v1 (Schema + Data)

Status: Draft v1  
Last updated: 2026-04-03

This document specifies the migration subsystem for a schema-per-tenant platform and defines an MVP-first path to operational maturity.

It covers:
- control-plane migrations
- tenant runtime schema migrations
- tenant runtime data migrations (backfills/transforms)
- release orchestration and rollback strategy
- module-provided migration SDK contract

---

## 1) Objectives

The migration subsystem must:

1. deliver fast MVP capability for shipping product features early
2. support safe rollout across many tenant schemas
3. allow module teams to ship schema and data changes independently
4. be resumable, observable, and auditable
5. stay reusable across deployment profiles:
   - full multi-tenant
   - simplified shared
   - single-tenant

Non-goals for v1:
- fully online no-freeze tenant promotion
- automatic down-migration for destructive changes
- cross-region orchestration

---

## 2) Migration domains

Treat migrations as three separate domains with different blast radius.

### 2.1 Control-plane migrations (shared schemas)

Schemas:
- `platform`
- `entitlements`
- `billing`
- `audit`

Scope:
- run once per environment/release
- standard linear migration chain

Failure impact:
- platform-wide

### 2.2 Tenant runtime schema migrations

Scope:
- one module migration chain applied per tenant schema (`t_<id>`)
- large fan-out execution (many tenants)

Failure impact:
- tenant- and module-scoped if isolated correctly

### 2.3 Tenant runtime data migrations

Scope:
- data transforms/backfills tied to schema/version changes
- executed per tenant with idempotent semantics

Failure impact:
- tenant/module scoped; should be resumable from checkpoints

---

## 3) Versioning model

Each module has its own semantic migration stream:

- `module_code` (for example `tasks`)
- `version` (monotonic integer for execution order)
- optional `release_tag` for human grouping

Recommended release units:
- schema step(s) (DDL)
- data step(s) (DML/backfill)
- verification step(s)

Execution rule:
- all steps in a unit are executed in order for each tenant
- next version starts only when prior version is successful

---

## 4) Migration metadata and ledger

Use immutable migration definitions plus mutable execution ledger.

### 4.1 Migration catalog (definition)

`platform.migration_definitions`

Suggested fields:
- `module_code`
- `version`
- `step_order`
- `step_type` (`SCHEMA`, `DATA`, `VERIFY`)
- `step_name`
- `artifact_ref` (path/container ref)
- `checksum`
- `is_idempotent`
- `requires_write_lock` (bool)
- `created_at`

Uniqueness:
- (`module_code`, `version`, `step_order`)

### 4.2 Execution ledger (runtime state)

`platform.migration_runs`

Suggested fields:
- `run_id` (UUID)
- `scope_type` (`CONTROL_PLANE`, `TENANT_BATCH`, `TENANT_SINGLE`, `DEDICATED_TARGET`)
- `module_code` nullable for control-plane
- `requested_by`
- `status` (`PENDING`, `RUNNING`, `PAUSED`, `SUCCEEDED`, `FAILED`, `CANCELLED`)
- `options_json` (batch size, dry run, canary tenants)
- `created_at`, `started_at`, `ended_at`

`platform.migration_run_items`

Suggested fields:
- `run_id`
- `tenant_id` (nullable for control-plane)
- `schema_name` (nullable for control-plane)
- `module_code`
- `target_version`
- `status` (`PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `SKIPPED`)
- `attempt_count`
- `last_error_code`
- `last_error_message`
- `started_at`, `ended_at`

`platform.tenant_schema_versions` (already planned)

Suggested extension:
- include `module_code`
- `current_version`
- `updated_at`

---

## 5) Orchestrator architecture

## 5.1 Components

1. **Migration API/CLI**
   - starts, pauses, resumes, and observes runs
2. **Planner**
   - resolves target set and computes pending steps
3. **Executor**
   - executes per-tenant/per-module steps with concurrency limits
4. **Lock manager**
   - advisory lock per (`tenant_id`, `module_code`) and global lock for control-plane runs
5. **Reporter**
   - writes ledger updates and emits audit/metrics events

## 5.2 Execution modes

- `single-tenant`
- `tenant-batch` (shared runtime)
- `dedicated-target` (single tenant dedicated DB)
- `control-plane`
- `dry-run` (plan only, no execution)

## 5.3 Concurrency and safety

- never run two migrations for same tenant/module simultaneously
- cap concurrent tenants per batch
- enforce lock timeout and deadlock retry policy
- support pause on error-rate threshold (post-MVP hardening)

---

## 6) SDK contract for module-owned migrations

Module teams can provide migration bundles using a strict contract.

Directory convention (example):

```text
modules/
  tasks/
    migrations/
      0001/
        schema.sql
        data.py
        verify.py
        manifest.json
```

`manifest.json` example:

```json
{
  "module_code": "tasks",
  "version": 1,
  "steps": [
    {
      "order": 1,
      "type": "SCHEMA",
      "artifact": "schema.sql",
      "idempotent": true
    },
    {
      "order": 2,
      "type": "DATA",
      "artifact": "data.py",
      "idempotent": true
    },
    {
      "order": 3,
      "type": "VERIFY",
      "artifact": "verify.py",
      "idempotent": true
    }
  ]
}
```

Python script contract (example):

```python
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class MigrationContext:
    run_id: str
    module_code: str
    version: int
    tenant_id: str
    schema_name: str
    dry_run: bool

class MigrationDb(Protocol):
    def execute(self, sql: str, params: dict | None = None) -> None: ...
    def fetch_one(self, sql: str, params: dict | None = None) -> dict | None: ...
    def commit(self) -> None: ...

def upgrade(ctx: MigrationContext, db: MigrationDb) -> None:
    # must be idempotent and safe on retry
    ...
```

Contract rules:
- `upgrade` is mandatory for DATA and VERIFY scripts
- script must be deterministic and idempotent
- no network calls to external systems
- no writes outside current tenant scope
- long-running transforms must checkpoint progress in DB

---

## 7) Transaction and locking model

SCHEMA steps:
- execute in explicit transaction when possible
- if operation is not transaction-safe in Postgres, isolate and guard with prechecks

DATA steps:
- chunk large updates to avoid long locks
- commit per chunk
- maintain checkpoint markers for resume

VERIFY steps:
- read-only checks by default
- may mark run item failed when thresholds are violated

Tenant context safety:
- prefer explicit schema qualification in generated SQL
- if `SET LOCAL search_path` is used, always inside transaction scope

---

## 8) Release workflow (expand -> migrate -> contract)

For schema/data changes affecting running services:

1. **Expand**
   - deploy backward-compatible application code
   - apply additive schema migration
2. **Migrate**
   - run data backfill/transform across target tenants
   - monitor lag and failures
3. **Contract**
   - switch reads/writes to new shape
   - remove deprecated columns in a later release

For tenant batch runs:
- start with canary tenant set (post-MVP stage)
- continue to full batches after canary health is green

---

## 9) Failure handling and recovery

Failure classes:
- artifact validation failure (checksum mismatch, bad manifest)
- lock/acquire timeout
- SQL/runtime execution error
- verification threshold failure

Recovery rules:
- mark item `FAILED` with error code and message
- keep succeeded tenants untouched
- allow `resume` after fix without re-running successful steps
- support `skip` for quarantined tenants (with audit record)

Operator commands (minimum):
- `run create`
- `run pause`
- `run resume`
- `run cancel`
- `run status`
- `run export-report`

Rollback strategy:
- default is forward-fix and resume
- destructive rollback only with explicit runbook and manual approval
- tenant promotion failures must restore previous active routing target

---

## 10) Observability and SLOs

Required telemetry:
- run duration, step duration
- tenant success/failure counters
- retries and lock wait durations
- rows affected (for data steps)
- canary vs non-canary outcomes

Audit events:
- run created/started/paused/resumed/cancelled/completed
- per-tenant failure reasons
- operator identity for all control actions

Target SLOs (post-MVP):
- run state updates visible within 5 seconds
- resume operation restarts failed items within 1 minute
- no duplicate successful step execution for idempotent scripts

---

## 11) MVP-to-stable roadmap for this subsystem

### Stage M0 (MVP)
- single-tenant and small-batch runner
- schema migrations first; minimal data migration hook
- basic ledger and CLI

### Stage M1 (Operational)
- robust batch execution and retries
- dry-run planner and preflight checks
- better reporting and audit coverage

### Stage M2 (Extensible)
- full module SDK for data/verify steps
- CI validation for migration bundles
- standardized checkpoints for long data jobs

### Stage M3 (Stabilized)
- canary rollout mode
- pause thresholds and guarded automation
- formal rollback playbooks and runbooks

---

## 12) Integration points with existing plan

- API contracts: `docs/API_CONTRACTS_V1.md`
  - `/v1/migrations/*`
  - `/v1/tenants/{id}/promotion-jobs/*`
- DDL baseline: `docs/CONTROL_PLANE_DDL_V1.sql`
  - extend with migration definitions and run ledger tables
- backlog: `docs/IMPLEMENTATION_BACKLOG_V1.md`
  - B5.2, B5.3, B5.4 map directly to this document

---

## 13) Open design decisions

1. Canonical runner implementation language (Python-only vs polyglot runtime support)
2. Whether module migrations execute in-process or in isolated workers
3. Max allowed freeze window for promotion before auto-abort
4. Policy for skipping failed tenants in global release gates
