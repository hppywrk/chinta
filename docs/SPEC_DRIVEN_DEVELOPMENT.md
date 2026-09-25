# Spec-driven development (Chinta)

Status: Adopted v1  
Last updated: 2026-09-25

This document is the practical guide for contract-first work in this repository: where specs live, how to change them, what is in **v1 scope**, and what stays on the backlog until control-plane services exist.

---

## 1) Principles

1. **The spec is the public interface** for each **HTTP service** in the repo (any language). Change that service’s `api/*-openapi.yml` first, then implement. Today auth and gateway are Python and already serve the spec; the C++ backend (`chinta/`) has a draft `chinta-openapi.yml` to implement against when the service is runnable; future control-plane services follow the same layout regardless of stack.
2. **Markdown + SQL specs** remain the source of truth for not-yet-built control-plane APIs (`docs/API_CONTRACTS_V1.md`, `docs/CONTROL_PLANE_DDL_V1.sql`, etc.). Promote sections to OpenAPI when a service is implemented—not before.
3. **Manual alignment** between OpenAPI and code is acceptable in v1 (e.g. Pydantic in Python, hand-written types in C++). CI only validates that specs are well-formed YAML and OpenAPI 3.0. Stricter linting (Spectral) and contract tests (schemathesis) are backlog items.
4. **Undocumented behavior is not part of the contract.** Endpoints may exist in code for local convenience but are excluded from v1 OpenAPI until promoted (see gateway `/` redirect).

---

## 2) Repository layout

```text
chinta-auth/
  api/auth-openapi.yml      # Auth service contract (v1)
  app.py                    # Implements contract; serves /openapi.yaml

chinta-gateway/
  api/gateway-openapi.yml   # Gateway edge contract (v1)
  app.py

chinta/
  api/chinta-openapi.yml    # Backend module API (draft; implement in C++ when runnable)

docs/
  API_CONTRACTS_V1.md       # Control-plane HTTP design (pre-OpenAPI)
  SPEC_DRIVEN_DEVELOPMENT.md  # This file
  IMPLEMENTATION_BACKLOG_V1.md

scripts/
  validate_openapi_specs.py # Local/CI: parse and sanity-check all *-openapi.yml
```

Naming: `{service}-openapi.yml` under `{service}/api/`.

Served URLs (operational services today; others when implemented):

| Service   | Language | Spec file              | `GET /openapi.yaml` | `GET /openapi.json` |
|-----------|----------|------------------------|---------------------|---------------------|
| Auth      | Python   | `auth-openapi.yml`     | yes                 | yes (YAML merged)   |
| Gateway   | Python   | `gateway-openapi.yml`  | yes                 | yes (YAML merged)   |
| Backend   | C++      | `chinta-openapi.yml`   | backlog             | backlog             |

When the backend is operational, it should expose the same spec files (or equivalent static routes) so gateway and clients can discover the module API without reading source.

---

## 3) Day-to-day workflow

1. Edit the service `api/*-openapi.yml` (paths, schemas, error shapes).
2. Update the service implementation to match (Python: handlers + Pydantic in `app.py`; C++: routes/handlers and DTOs under `chinta/`; other stacks: same idea).
3. Run validation:

   ```bash
   source /workspace/.venv/bin/activate
   python /workspace/scripts/validate_openapi_specs.py
   ```

4. Smoke the served spec:

   ```bash
   curl -s http://localhost:8083/openapi.yaml | head
   curl -s http://localhost:8084/openapi.yaml | head
   ```

5. When adding a **new HTTP service**, add `api/{service}-openapi.yml`, register it in `validate_openapi_specs.py`, and serve the spec at `/openapi.yaml` (Python services can reuse the pattern in `chinta-auth/app.py`; other languages serve the file statically or generate JSON from the same YAML).

---

## 4) Gateway v1 scope (frozen)

These routes are the **only** gateway behaviors guaranteed in v1. They match `chinta-gateway/api/gateway-openapi.yml`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness |
| GET | `/me` | Return OIDC userinfo via auth service (Bearer JWT) |
| * | `/auth/{path}` | Opaque passthrough to `CHINTA_AUTH_URL` (auth owns semantics) |
| * | `/api/{path}` | Authenticated passthrough to `CHINTA_BACKEND_URL` |

**Explicitly out of v1 contract** (implemented or planned elsewhere; do not rely on them without promoting the spec):

| Item | Where tracked |
|------|----------------|
| `/` UI redirect (web/mobile heuristics) | Backlog **B_GW.2** |
| Tenant resolution, entitlements, routing headers (`API_CONTRACTS_V1` §5) | Backlog **B2.x** |
| Control-plane paths `/v1/tenants`, `/v1/entitlements/...` on gateway | Backlog **B1.x**, **B2.x** |
| OpenAPI lint / schemathesis / codegen | Backlog **B0.5** |

Passthrough routes are documented in OpenAPI with generic responses; exact status codes and bodies are defined by auth or backend services.

---

## 5) Auth v1 scope (reference)

Canonical file: `chinta-auth/api/auth-openapi.yml`.

| In v1 OpenAPI | Notes |
|---------------|-------|
| `POST /authenticate` | Code exchange |
| `GET /auth/authorize` | Authorization URL helper |
| `GET /userinfo` | Bearer userinfo |
| `GET /health` | Liveness (added with spec-driven adoption) |

**Backlog (auth spec gaps):**

| Item | Backlog |
|------|---------|
| `GET /auth/callback` (browser redirect code exchange) | **B_AUTH.1** — add to OpenAPI or fold into documented proxy-only flow |
| Automated spec ↔ implementation drift check | **B0.5** |

---

## 6) Control plane and backend (not v1 OpenAPI)

| Artifact | Role | Next step |
|----------|------|-----------|
| `docs/API_CONTRACTS_V1.md` | Tenant registry, entitlements, routing | OpenAPI per service when B1/B2 land |
| `chinta/api/chinta-openapi.yml` | Messages API for C++ backend | Implement routes to match spec; serve `/openapi.yaml` when service runs |
| `docs/MESSAGING_ARCHITECTURE_V1.md` | Event envelope | AsyncAPI or JSON Schema in backlog **B0.4** |

`API_CONTRACTS_V1.md` §8 still applies: full OpenAPI for every service is not a v1 platform goal—but **edge + auth** are fully OpenAPI-driven now.

---

## 7) CI recommendations (when GitHub Actions exists)

Minimal job (no new runtime deps beyond PyYAML already in auth/gateway):

```yaml
- run: python scripts/validate_openapi_specs.py
```

Later (**B0.5**):

- [Spectral](https://stoplight.io/open-source/spectral) ruleset for naming, operationIds, error schema consistency.
- Optional `schemathesis run` against `/openapi.json` on a test instance with dummy OIDC env.
- Optional diff gate: fail PR if `openapi.yaml` changes without `api/*-openapi.yml` change (or vice versa).

---

## 8) Related documents

- Platform plan: `PLATFORM_PLAN.md`
- Control-plane API design: `docs/API_CONTRACTS_V1.md`
- Ordered delivery: `docs/IMPLEMENTATION_BACKLOG_V1.md` (sections **B0.5**, **B_GW.x**, **B_AUTH.1**)

---

## Change log

- v1 (2026-09-25): Initial adoption guide; gateway OpenAPI v1; validation script; backlog entries for deferred gateway/auth/CI work.
- v1.1 (2026-09-25): Clarify contract-first applies to all HTTP services/languages, not Python only (PR #16 review).
