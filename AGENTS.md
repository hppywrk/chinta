# AGENTS.md

## Cursor Cloud specific instructions

### Project snapshot

Chinta is a multi-tenant microservices project. Operational Python services:

- **chinta-auth** (port 8083): FastAPI OIDC authentication service
- **chinta-gateway** (port 8084): FastAPI edge gateway
- **chinta** / **chinta-backend** (port 8080): FastAPI notes editor API (PostgreSQL, schema-per-tenant)

The C++ sources under `chinta/src/` are legacy placeholders for a future rewrite. **chinta-net** and root `Dockerfile.chinta` remain experimental (`full-stack` compose profile only).

### Current repository layout (practical view)

- `/chinta-auth`: working Python service (pytest under `chinta-auth/test_*.py`)
- `/chinta-gateway`: working Python service (`httpx` + `pyyaml` in requirements; pytest under `chinta-gateway/test_*.py`)
- `/chinta`: working Python backend (`psycopg`, notes CRUD; pytest under `chinta/test_*.py`)
- `/chinta-db`: SQL bootstrap file (`init.sql`) for shared catalog; tenant notes live in per-tenant schemas (`t_<sha256-prefix>`) created by the backend
- `/config`: YAML config samples (`chinta.yml`, `chinta-find.yml`)
- `/docs`: platform specs (`API_CONTRACTS_V1.md`, `SPEC_DRIVEN_DEVELOPMENT.md`, `CI_CD.md`, …)
- `/scripts`: `validate_openapi_specs.py`, `deploy/vm-deploy.sh`
- `/rootfs/etc/systemd/system`: `chinta-compose.service` (optional boot wrapper for docker compose)
- `docker-compose.yml`: default stack — `chinta-db`, `chinta-auth`, `chinta-backend`, `chinta-gateway`; `chinta-net` under `full-stack` profile

### Local environment bootstrap

Python services share `/workspace/.venv`. If it does not exist, create it first.

```bash
sudo apt-get install -y python3.12-venv
python3.12 -m venv /workspace/.venv
source /workspace/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r /workspace/chinta-auth/requirements.txt
python -m pip install -r /workspace/chinta-gateway/requirements.txt
python -m pip install -r /workspace/chinta/requirements.txt
```

Notes API requires PostgreSQL (e.g. `docker compose up -d chinta-db`).

### Running services locally

Activate venv before starting:

```bash
source /workspace/.venv/bin/activate
```

Start auth service:

```bash
cd /workspace/chinta-auth
OIDC_CLIENT_ID=test OIDC_CLIENT_SECRET=test uvicorn app:app --host 0.0.0.0 --port 8083 --reload
```

Start backend (needs DB):

```bash
cd /workspace/chinta
CHINTA_DB_HOST=localhost CHINTA_AUTH_URL=http://localhost:8083 uvicorn app:app --host 0.0.0.0 --port 8080 --reload
```

Start gateway service:

```bash
cd /workspace/chinta-gateway
CHINTA_AUTH_URL=http://localhost:8083 CHINTA_BACKEND_URL=http://localhost:8080 CHINTA_GATEWAY_PORT=8084 uvicorn app:app --host 0.0.0.0 --port 8084 --reload
```

### Verification

Health checks:

```bash
curl http://localhost:8083/health  # auth
curl http://localhost:8084/health  # gateway
curl http://localhost:8080/health  # backend
```

Useful endpoint checks:

```bash
curl http://localhost:8083/openapi.yaml
curl http://localhost:8084/openapi.yaml
curl http://localhost:8080/openapi.yaml
curl -i http://localhost:8084/me  # expected 401 without Bearer token
python /workspace/scripts/validate_openapi_specs.py
```

Notes via gateway (Bearer token + `X-Tenant-Id`):

```bash
curl -H "Authorization: Bearer <token>" -H "X-Tenant-Id: demo" http://localhost:8084/api/notes
```

Swagger UI:

- Auth: http://localhost:8083/docs
- Gateway: http://localhost:8084/docs
- Backend: http://localhost:8080/docs

### Cloud Agent

The saved Cloud Agent environment installs Python requirement files into `/workspace/.venv` and may start chinta-auth (`0.0.0.0:8083`) and chinta-gateway (`0.0.0.0:8084`) with `OIDC_CLIENT_ID=test` and `OIDC_CLIENT_SECRET=test`. If `GET /health` on those ports already returns `{"status":"ok"}`, leave the existing processes running. Backend and PostgreSQL are not always started in the cloud snapshot; use `docker compose up -d chinta-db chinta-backend` when testing notes.

Install all three Python `requirements.txt` files into the shared venv. Do not drop `httpx` from `chinta-gateway/requirements.txt`.

### Known blockers and gotchas

- `docker compose --profile full-stack` still builds incomplete **chinta-net** image (`Dockerfile.chinta-net`).
- Legacy root `Dockerfile.chinta` targets the old C++ binary; compose uses `chinta/Dockerfile` for **chinta-backend**.
- VM CD runs the default compose stack (`chinta-db`, `chinta-auth`, `chinta-backend`, `chinta-gateway`) via `scripts/deploy/vm-deploy.sh`.
- `Dockerfile.cinta-db` uses `chinta-db/init.sql`.
- `chinta-compose.service` defaults to `/opt/chinta`; `vm-deploy.sh` rewrites paths when `CHINTA_ROOT` differs.
- Auth service can start with dummy OIDC env vars, but real auth/token/userinfo flow requires valid IdP credentials.
- Backend validates Bearer tokens via auth `/userinfo` and requires `X-Tenant-Id` on every notes request.
- Gateway v1 OpenAPI contract excludes `GET /` UI redirect (see `docs/SPEC_DRIVEN_DEVELOPMENT.md`); route still exists for local dev.
- GitHub Actions workflow `.github/workflows/ci.yml` runs on PRs and pushes to `main`; manual VM deploy is documented in `docs/CI_CD.md`.
- For browser OAuth via gateway, set `OIDC_REDIRECT_URI_BASE` to the public origin (e.g. `http://localhost:8084`); callback defaults to `{base}/auth/callback`.

### Boundaries

- Всегда обновляй AGENTS.md при изменении структуры проекта
