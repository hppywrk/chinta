# AGENTS.md

## Cursor Cloud specific instructions

### Project Overview

Chinta is a personal thoughts/tasks management platform built as microservices. Only two services are currently fully implemented:

- **chinta-auth** (port 8083) — FastAPI OIDC authentication service
- **chinta-gateway** (port 8084) — FastAPI edge API gateway

Other services referenced in `docker-compose.yml` (`chinta-find`, `chinta-net`, `chinta-web`) have **missing directories** and cannot be built or run. The C++ backend (`chinta/`) is a skeleton only.

### Running Services Locally

Both Python services use a shared virtualenv at `/workspace/.venv`. Activate it before running anything:

```bash
source /workspace/.venv/bin/activate
```

**chinta-auth** (requires dummy OIDC env vars to start):
```bash
cd /workspace/chinta-auth
OIDC_CLIENT_ID=test OIDC_CLIENT_SECRET=test uvicorn app:app --host 0.0.0.0 --port 8083 --reload
```

**chinta-gateway** (point URLs to local services):
```bash
cd /workspace/chinta-gateway
CHINTA_AUTH_URL=http://localhost:8083 CHINTA_BACKEND_URL=http://localhost:8080 CHINTA_GATEWAY_PORT=8084 uvicorn app:app --host 0.0.0.0 --port 8084 --reload
```

### Key Gotchas

- `python3.12-venv` must be installed (`sudo apt-get install -y python3.12-venv`) before creating the virtualenv. The update script handles this.
- The auth service will start without real OIDC credentials, but OIDC flows (token exchange, userinfo) require valid `OIDC_CLIENT_ID`/`OIDC_CLIENT_SECRET` from a real IdP (defaults to Google).
- `docker-compose.yml` references `Dockerfile.postgres` but the actual file is named `Dockerfile.cinta-db` (typo). Docker Compose orchestration will fail without fixes.
- The C++ backend's `CMakeLists.txt` has a leading space in the filename (`chinta/src/ CMakeLists.txt`), which will cause CMake build failures.
- No README, CONTRIBUTING.md, or Makefile exist in this repo.
- No automated test suites exist for any service.

### Verification

Health checks for running services:
```bash
curl http://localhost:8083/health  # auth
curl http://localhost:8084/health  # gateway
```

Interactive API docs (Swagger UI):
- Auth: http://localhost:8083/docs
- Gateway: http://localhost:8084/docs
