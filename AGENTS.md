# AGENTS.md

## Cursor Cloud specific instructions

### Project snapshot

Chinta is a multi-tenant microservices project. In this repository state, only two services are operational:

- **chinta-auth** (port 8083): FastAPI OIDC authentication service
- **chinta-gateway** (port 8084): FastAPI edge gateway

Everything else is partial, stubbed, or missing. Plan work around that limitation.

### Current repository layout (practical view)

- `/chinta-auth`: working Python service (includes `test_userinfo.py`)
- `/chinta-gateway`: working Python service
- `/chinta`: C++ backend skeleton only (not production-ready)
- `/chinta-db`: SQL bootstrap file (`init.sql`) only
- `/config`: YAML config samples (`chinta.yml`, `chinta-find.yml`)
- `/rootfs/etc/systemd`: template unit files with placeholder paths
- `docker-compose.yml`: present, but not runnable as-is (see gotchas)

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
curl http://localhost:8083/openapi.json
curl -i http://localhost:8084/me  # expected 401 without Bearer token
```

Swagger UI:

- Auth: http://localhost:8083/docs
- Gateway: http://localhost:8084/docs

### Known blockers and gotchas

- `docker-compose.yml` references services/directories that do not exist (`chinta-find`, `chinta-net`, `chinta-web`).
- `docker-compose.yml` points DB build to `Dockerfile.postgres`, but repo file is `Dockerfile.cinta-db`.
- `docker-compose.yml` defines `chinta-backend` with `context: ./chinta` and `dockerfile: Dockerfile`, but `/chinta/Dockerfile` is missing.
- `Dockerfile.chinta` copies `lib/http-service`, but only `lib/http/include/...` exists.
- `Dockerfile.chinta` runs `/usr/local/bin/chinta --config /etc/chinta/chinta.yaml`, while sample config file is `config/chinta.yml` (name mismatch).
- `Dockerfile.cinta-db` copies `config/database/init.sql`, but this path is missing; available SQL is `chinta-db/init.sql`.
- C++ backend file is misnamed as `chinta/src/ CMakeLists.txt` (leading space), which breaks normal CMake workflows.
- Systemd unit files under `rootfs/etc/systemd` contain placeholder paths like `/path/to/your/...` and are not directly deployable.
- Auth service can start with dummy OIDC env vars, but real auth/token/userinfo flow requires valid IdP credentials.
- Auth has a small pytest suite (`chinta-auth/test_userinfo.py`); no README, CONTRIBUTING guide, or Makefile are currently present.

### Boundaries

- Всегда обновляй AGENTS.md при изменении структуры проекта
