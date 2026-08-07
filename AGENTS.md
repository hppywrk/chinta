# AGENTS.md

## Cursor Cloud specific instructions

### Project Overview

Chinta is a multi-tenant microservices platform. See `PLATFORM_PLAN.md` for the full architecture vision and `ROADMAP.md` for the iterative milestone plan.

**M1 services (all implemented and working):**

| Service | Port | Description |
|---|---|---|
| `chinta-db` | 5432 | PostgreSQL 16 (Alpine) — notes, users, tags schema |
| `chinta-auth` | 8083 | FastAPI OIDC authentication service |
| `chinta-notebook` | 8085 | FastAPI note CRUD (create/list/get/delete with tags) |
| `chinta-gateway` | 8084 | FastAPI edge proxy routing to auth + notebook |

### Repository layout

- `/chinta-auth/` — working Python/FastAPI OIDC auth service
- `/chinta-gateway/` — working Python/FastAPI edge gateway
- `/chinta-notebook/` — working Python/FastAPI note CRUD service
- `/chinta-db/` — PostgreSQL init SQL
- `/tests/` — functional tests (pytest + httpx)
- `/docs/` — v1 architecture specs (DDL, API contracts, migration system, messaging)
- `PLATFORM_PLAN.md` — full multi-tenant platform architecture plan
- `ROADMAP.md` — iterative milestone roadmap
- `.github/workflows/ci.yml` — GitHub Actions CI (lint, test, build images)

### Running the Stack

All services are orchestrated via Docker Compose:

```bash
docker compose up -d --build
```

Health check all services:
```bash
curl http://localhost:8083/health  # auth
curl http://localhost:8084/health  # gateway
curl http://localhost:8085/health  # notebook
```

### Running Without Docker

Each Python service can run standalone with the shared virtualenv at `/workspace/.venv`:

```bash
source /workspace/.venv/bin/activate

# Auth (needs dummy OIDC env vars to start):
cd /workspace/chinta-auth && OIDC_CLIENT_ID=test OIDC_CLIENT_SECRET=test uvicorn app:app --port 8083 --reload

# Notebook (needs a running PostgreSQL):
cd /workspace/chinta-notebook && DATABASE_URL=postgresql://chinta_user:chinta_password@localhost:5432/chinta uvicorn app:app --port 8085 --reload

# Gateway:
cd /workspace/chinta-gateway && CHINTA_AUTH_URL=http://localhost:8083 CHINTA_NOTEBOOK_URL=http://localhost:8085 uvicorn app:app --port 8084 --reload
```

### Linting

```bash
ruff check .
ruff check . --fix   # auto-fix
```

### Testing

Functional tests require running services (via `docker compose up` or manual startup):

```bash
pip install -r tests/requirements.txt
pytest tests/ -v
```

### Key Gotchas

- `python3.12-venv` must be installed before creating the virtualenv.
- The auth service starts without real OIDC credentials, but OIDC flows (token exchange, userinfo) need valid `OIDC_CLIENT_ID`/`OIDC_CLIENT_SECRET`.
- The notebook service requires PostgreSQL to be running and the `DATABASE_URL` env var set.
- FastAPI Swagger UI is available at `/docs` on each service for interactive API exploration.

### Boundaries

- Всегда обновляй AGENTS.md при изменении структуры проекта
