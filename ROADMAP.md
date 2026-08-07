# Chinta Platform — Development Roadmap

## Vision

A multitenant SaaS platform where customers purchase subscriptions to independent modules. Each module is a microservice that can be developed, deployed, and scaled independently. The platform provides common infrastructure for auth, observability, rate-limiting, inter-service authorization, and deployment.

See `PLATFORM_PLAN.md` for the detailed architecture plan and `docs/` for v1 specifications.

---

## Milestone 1 — Stateless Backbone (no multitenancy, single user)

**Goal:** A working end-to-end system with auth, one business-logic service, structured logging, Docker Compose orchestration, functional tests, and basic CI/CD.

| Component | Description |
|---|---|
| **chinta-db** | PostgreSQL with schema for notes + users (single user, orgs disabled) |
| **chinta-auth** | OIDC authentication service (Authlib + FastAPI) |
| **chinta-notebook** | Simple notebook CRUD — create/list/get/delete notes with tags |
| **chinta-gateway** | Edge API gateway routing `/auth/*` → auth, `/api/notes/*` → notebook |
| **Logging** | Structured JSON logs (python-json-logger) in every service |
| **Functional tests** | pytest + httpx hitting real services (docker-compose) |
| **CI/CD** | GitHub Actions: lint (ruff), test, build Docker images, push to GHCR |

### What "done" looks like

- `docker compose up` starts db, auth, notebook, gateway
- `curl localhost:8084/health` → ok
- `curl localhost:8084/api/notes` → `[]` (empty notebook)
- `curl -X POST localhost:8084/api/notes -d '{"title":"hello","body":"world","tags":["demo"]}'` → note created
- `pytest tests/` passes against running services
- GitHub Actions green on push

---

## Milestone 2 — Observability & Deployment Artifacts

**Goal:** Production-grade observability and deployable artifacts.

| Component | Description |
|---|---|
| **Structured logs → Loki** | Promtail/Loki collecting JSON logs from all containers |
| **Metrics → Prometheus** | Each service exposes `/metrics` (starlette-prometheus); Prometheus scrapes |
| **Dashboards → Grafana** | Pre-provisioned dashboards: request rate, latency p50/p95/p99, error rate, DB connections |
| **Health probes** | Liveness + readiness probes in all services, wired into compose healthchecks |
| **Helm charts** | Kubernetes Helm charts for each service (or Compose → K8s via Kompose as stepping stone) |
| **Image registry** | GitHub Container Registry (GHCR) with semver tags |
| **Deploy CLI** | `chinta deploy --env staging` script wrapping Helm/docker-compose for a given cloud |

---

## Milestone 3 — Multitenancy & Scalability

**Goal:** Multiple users, organizations, tenant isolation. See `PLATFORM_PLAN.md` sections 3–6 and `docs/CONTROL_PLANE_DDL_V1.sql`.

---

## Milestone 4 — Service Mesh & Module Authorization

**Goal:** Inter-service authorization, subscription-gated module access. See `PLATFORM_PLAN.md` sections 5, 7 and `docs/API_CONTRACTS_V1.md`.

---

## Milestone 5 — Full IaaC & Advanced CI/CD

**Goal:** One-command deployment to any cloud, GitOps, canary releases. See `PLATFORM_PLAN.md` section 9.
