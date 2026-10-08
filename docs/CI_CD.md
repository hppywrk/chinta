# CI/CD (GitHub Actions → VM)

Status: v1  
Last updated: 2026-09-29

This document describes continuous integration on pull requests and manual deployment to a Linux VM.

---

## 1) CI (pull requests and `main`)

Workflow: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)

Runs on every **pull request** and every **push to `main`**.

| Job | What it checks |
|-----|----------------|
| **OpenAPI specs** | `python scripts/validate_openapi_specs.py` |
| **Python services** | Install auth + gateway deps, `compileall`, import `app` modules |
| **Smoke** | Start uvicorn for auth and gateway; `curl` health, OpenAPI, and `GET /me` → 401 |

No repository secrets are required for CI.

### Local parity

```bash
python3.12 -m pip install pyyaml
python3.12 scripts/validate_openapi_specs.py
python3.12 -m pip install -r chinta-auth/requirements.txt -r chinta-gateway/requirements.txt
python3.12 -m compileall -q chinta-auth chinta-gateway
```

---

## 2) CD (manual deploy to a VM)

Workflow: [`.github/workflows/cd.yml`](../.github/workflows/cd.yml)

Triggered only via **Actions → CD → Run workflow** (`workflow_dispatch`). This avoids accidental deploys before secrets exist.

Deploy script: [`scripts/deploy/vm-deploy.sh`](../scripts/deploy/vm-deploy.sh)

The CD job **copies `vm-deploy.sh` from the selected git ref** onto the VM before running it. The script then `git fetch` / `checkout` / `reset` to the same ref and runs **`docker compose build` + `up -d`**.

### Service layout: Docker Compose only

[`docker-compose.yml`](../docker-compose.yml) defines **all** runtime services on the VM. There is no host venv or per-service uvicorn under systemd.

| Service | Default CD stack | Notes |
|---------|------------------|--------|
| `chinta-db` | yes | Postgres image from `Dockerfile.cinta-db` |
| `chinta-auth` | yes | Built from `chinta-auth/Dockerfile` |
| `chinta-backend` | yes | Notes API (`chinta/Dockerfile`); required for `/api/notes` |
| `chinta-gateway` | yes | Built from `chinta-gateway/Dockerfile` |
| `chinta-platform` | yes | Control plane; gateway access resolve (`CHINTA_PLATFORM_URL`) |
| `chinta-net` | `full-stack` profile only | Experimental; not in default CD |

Default service list is in `x-chinta-vm.default_services` and overridable via `CHINTA_COMPOSE_SERVICES` in `/etc/chinta/deploy.env` (loaded by `vm-deploy.sh` before resolving the service list).

**Boot after reboot:** optional [`chinta-compose.service`](../rootfs/etc/systemd/system/chinta-compose.service) runs the same `docker compose up -d` stack (one systemd unit, all processes in containers).

### 2.1 Prepare the VM (one time)

1. **OS**: Ubuntu 22.04+ with `git`, `curl`, **Docker Engine** and the **Compose plugin** (`docker compose version`).
2. **User**: e.g. `chinta` in the `docker` group (`sudo usermod -aG docker chinta`) and passwordless `sudo` for `systemctl` if you enable `chinta-compose.service`.
3. **Clone** the repository:

   ```bash
   sudo mkdir -p /opt/chinta
   sudo chown chinta:chinta /opt/chinta
   sudo -u chinta git clone https://github.com/hppywrk/chinta.git /opt/chinta
   ```

4. **Environment file** (passed to compose via `--env-file` and container `env_file`):

   ```bash
   sudo mkdir -p /etc/chinta
   sudo cp /opt/chinta/config/deploy.env.example /etc/chinta/deploy.env
   sudo chmod 600 /etc/chinta/deploy.env
   # Set OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, and public OIDC_REDIRECT_URI_BASE
   # (compose defaults OIDC_REDIRECT_URI_BASE to the gateway origin, e.g. http://localhost:8084)
   ```

5. **Optional — start stack on boot:**

   ```bash
   sudo cp /opt/chinta/rootfs/etc/systemd/system/chinta-compose.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable chinta-compose
   ```

6. **First deploy**:

   ```bash
   cd /opt/chinta && bash scripts/deploy/vm-deploy.sh main
   ```

7. **Firewall**: expose **8083** (auth) and **8084** (gateway) as needed; prefer TLS on a reverse proxy.

Local Docker (same compose file):

```bash
export OIDC_CLIENT_ID=test OIDC_CLIENT_SECRET=test
docker compose up -d chinta-db chinta-auth chinta-backend chinta-gateway chinta-platform
```

### 2.2 GitHub configuration

#### Repository secrets

| Secret | Description |
|--------|-------------|
| `DEPLOY_HOST` | VM hostname or IP |
| `DEPLOY_USER` | SSH user (e.g. `chinta`) |
| `DEPLOY_SSH_KEY` | Private key (PEM) for that user |
| `DEPLOY_SSH_PORT` | Optional; default 22 |
| `DEPLOY_PATH` | Optional; default `/opt/chinta` |

#### Environment (recommended)

Create a GitHub **environment** named `production` with optional protection rules. The CD workflow uses `environment: production`.

#### SSH access for Actions

The deploy user must be able to:

- `git fetch` / `checkout` in `DEPLOY_PATH`
- run `docker compose` (group `docker` or root)
- run `scripts/deploy/vm-deploy.sh`
- optional: `sudo systemctl` for `chinta-compose.service`

### 2.3 Run a deploy

1. Select the git ref (e.g. `main`).
2. GitHub → **Actions** → **CD** → **Run workflow** → set **git_ref**.
3. Verify on the VM:

   ```bash
   docker compose ps
   curl -s http://127.0.0.1:8083/health
   curl -s http://127.0.0.1:8080/health
   curl -s http://127.0.0.1:8084/health
   ```

---

## 3) Roadmap (after v1)

| Item | Notes |
|------|--------|
| Auto-deploy on push to `main` | Add `push: branches: [main]` with environment protection |
| Spectral / schemathesis in CI | Backlog **B0.5** |
| TLS + reverse proxy (Caddy/nginx) | Infra doc or extend this file |
| `full-stack` profile in CD | When `chinta-net` image builds reliably |
| Staging environment | Second GitHub environment + secrets |

---

## Related

- Spec-driven checks: `docs/SPEC_DRIVEN_DEVELOPMENT.md`
- Agent local runbook: `AGENTS.md`
