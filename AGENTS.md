# AGENTS.md

## Cursor Cloud specific instructions

### Project snapshot

Chinta is a multi-tenant microservices project. In this repository state, only two services are operational:

- **chinta-auth** (port 8083): FastAPI OIDC authentication service
- **chinta-gateway** (port 8084): FastAPI edge gateway

Everything else is partial, stubbed, or missing. Plan work around that limitation.

### Current repository layout (practical view)

- `/chinta-auth`: working Python service (pytest under `chinta-auth/test_*.py`)
- `/chinta-gateway`: working Python service (`httpx` + `pyyaml` in requirements; pytest under `chinta-gateway/test_*.py`)
- `/chinta`: C++ backend skeleton only (not production-ready)
- `/chinta-db`: SQL bootstrap file (`init.sql`) only
- `/config`: YAML config samples (`chinta.yml`, `chinta-find.yml`)
- `/docs`: platform specs (`API_CONTRACTS_V1.md`, `SPEC_DRIVEN_DEVELOPMENT.md`, `CI_CD.md`, …)
- `/scripts`: `validate_openapi_specs.py`, `deploy/vm-deploy.sh`
- `/rootfs/etc/systemd`: template unit files with placeholder paths
- `docker-compose.yml`: service catalog (auth, gateway, db in default stack; backend/net under `full-stack` profile)

### Local environment bootstrap

Python services share `/workspace/.venv`. If it does not exist, create it first.

```bash
sudo apt-get install -y python3.12-venv
python3.12 -m venv /workspace/.venv
source /workspace/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r /workspace/chinta-auth/requirements.txt
python -m pip install -r /workspace/chinta-gateway/requirements.txt
```

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

Start gateway service (local auth URL, backend may be unavailable):

```bash
cd /workspace/chinta-gateway
CHINTA_AUTH_URL=http://localhost:8083 CHINTA_BACKEND_URL=http://localhost:8080 CHINTA_GATEWAY_PORT=8084 uvicorn app:app --host 0.0.0.0 --port 8084 --reload
```

### Verification

Health checks:

```bash
curl http://localhost:8083/health  # auth
curl http://localhost:8084/health  # gateway
```

Useful endpoint checks:

```bash
curl http://localhost:8083/openapi.yaml
curl http://localhost:8084/openapi.yaml
curl -i http://localhost:8084/me  # expected 401 without Bearer token
python /workspace/scripts/validate_openapi_specs.py
```

Swagger UI:

- Auth: http://localhost:8083/docs
- Gateway: http://localhost:8084/docs

### Cloud Agent

The saved Cloud Agent environment installs both Python requirement files into `/workspace/.venv` and, on each boot, starts chinta-auth (`0.0.0.0:8083`) and chinta-gateway (`0.0.0.0:8084`) with `OIDC_CLIENT_ID=test` and `OIDC_CLIENT_SECRET=test`. If `GET /health` on those ports already returns `{"status":"ok"}`, leave the existing processes running.

`chinta-gateway/requirements.txt` declares `httpx` (required by `app.py`). Install both Python requirement files into the shared venv.

### Known blockers and gotchas

- `docker compose --profile full-stack` still builds incomplete C++/net images (`Dockerfile.chinta`, `Dockerfile.chinta-net`).
- VM CD uses **systemd** for auth/gateway (venv); compose describes the same service names/ports for Docker/local and optional `chinta-db.service`.
- `Dockerfile.chinta` copies `lib/http-service`, but only `lib/http/include/...` exists.
- `Dockerfile.chinta` runs `/usr/local/bin/chinta --config /etc/chinta/chinta.yaml`, while sample config file is `config/chinta.yml` (name mismatch).
- `Dockerfile.cinta-db` uses `chinta-db/init.sql`.
- C++ backend file is misnamed as `chinta/src/ CMakeLists.txt` (leading space), which breaks normal CMake workflows.
- Systemd unit files under `rootfs/etc/systemd` contain placeholder paths like `/path/to/your/...` and are not directly deployable.
- Auth service can start with dummy OIDC env vars, but real auth/token/userinfo flow requires valid IdP credentials.
- Gateway v1 OpenAPI contract excludes `GET /` UI redirect (see `docs/SPEC_DRIVEN_DEVELOPMENT.md`); route still exists for local dev.
- Auth and gateway include pytest suites under each service directory; run with `pip install pytest` then `pytest` from the service directory. No README, CONTRIBUTING guide, or Makefile are currently present.
- Do not drop `httpx` from `chinta-gateway/requirements.txt` — proxy routes import it at module load.
- GitHub Actions workflow `.github/workflows/ci.yml` runs on PRs and pushes to `main`; manual VM deploy is documented in `docs/CI_CD.md`.
- For browser OAuth via gateway, set `OIDC_REDIRECT_URI_BASE` to the public origin (e.g. `http://localhost:8084`); callback defaults to `{base}/auth/callback`.

### Boundaries

- Всегда обновляй AGENTS.md при изменении структуры проекта
