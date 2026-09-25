# CI/CD (GitHub Actions → VM)

Status: v1  
Last updated: 2026-09-25

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

Deploy script on the VM: [`scripts/deploy/vm-deploy.sh`](../scripts/deploy/vm-deploy.sh)

### 2.1 Prepare the VM (one time)

1. **OS**: Ubuntu 22.04+ (or similar) with `git`, `python3.12-venv` (or `python3-venv`), `curl`.
2. **User**: create a dedicated user, e.g. `chinta`, with sudo limited to `systemctl restart chinta-*` if desired.
3. **Clone** the repository:

   ```bash
   sudo mkdir -p /opt/chinta
   sudo chown chinta:chinta /opt/chinta
   sudo -u chinta git clone https://github.com/hppywrk/chinta.git /opt/chinta
   ```

4. **Environment file**:

   ```bash
   sudo mkdir -p /etc/chinta
   sudo cp /opt/chinta/config/deploy.env.example /etc/chinta/deploy.env
   sudo chmod 600 /etc/chinta/deploy.env
   # edit OIDC_CLIENT_ID / OIDC_CLIENT_SECRET and URLs
   ```

5. **Systemd units** (adjust paths if not using `/opt/chinta`):

   ```bash
   sudo cp /opt/chinta/rootfs/etc/systemd/system/chinta-auth.service /etc/systemd/system/
   sudo cp /opt/chinta/rootfs/etc/systemd/system/chinta-gateway.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable chinta-auth chinta-gateway
   ```

6. **First deploy** (on VM):

   ```bash
   cd /opt/chinta && bash scripts/deploy/vm-deploy.sh main
   sudo systemctl start chinta-auth chinta-gateway
   ```

7. **Firewall**: expose **8083** (auth) and **8084** (gateway) only as needed; prefer TLS termination on a reverse proxy in front.

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

Create a GitHub **environment** named `production` with optional protection rules (required reviewers). The CD workflow uses `environment: production`.

#### SSH access for Actions

On the VM, append the deploy public key to `~/.ssh/authorized_keys` for `DEPLOY_USER`.

The deploy user must be able to:

- `git fetch` / `checkout` in `DEPLOY_PATH`
- run `scripts/deploy/vm-deploy.sh` (creates venv, pip install)
- `sudo systemctl restart chinta-auth chinta-gateway` (configure passwordless sudo for those units, or run units as the deploy user with user systemd — adjust units accordingly)

### 2.3 Run a deploy

1. Merge or select the git ref you want (e.g. `main` or a release tag).
2. GitHub → **Actions** → **CD** → **Run workflow** → set **git_ref**.
3. Watch the job log; on success, verify on the VM:

   ```bash
   curl -s http://127.0.0.1:8083/health
   curl -s http://127.0.0.1:8084/health
   ```

---

## 3) Roadmap (after v1)

| Item | Notes |
|------|--------|
| Auto-deploy on push to `main` | Add `push: branches: [main]` to CD with environment protection |
| Spectral / schemathesis in CI | Backlog **B0.5** |
| TLS + reverse proxy (Caddy/nginx) | Document in infra repo or extend this doc |
| Docker-based deploy | Blocked until `docker-compose.yml` is runnable |
| Staging environment | Second GitHub environment + `DEPLOY_*` secrets per env |

---

## Related

- Spec-driven checks: `docs/SPEC_DRIVEN_DEVELOPMENT.md`
- Agent local runbook: `AGENTS.md`
