# Local deploy v1 (Docker Compose)

Status: Draft  
Last updated: 2026-10-08  
Spec: `docs/PRODUCT_SLICE_V1.md`

Run the Chinta stack on your machine with Docker Compose. Some steps below reflect **current** repo behavior; items marked *(planned)* come from the product v1 backlog (UI, auto-migrations, seed script).

---

## Prerequisites

- Docker Engine with Compose v2
- OIDC client credentials (e.g. Google OAuth) with redirect URI  
  `http://localhost:8084/auth/callback`
- Optional: Python 3.12 + venv for `chinta-admin` on the host

---

## 1) Configure environment

```bash
cd /path/to/chinta
cp docs/examples/deploy.local.env.example .env
# Edit .env: set OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, and CHINTA_PLATFORM_ADMIN_TOKEN
```

---

## 2) Start the stack

```bash
docker compose --env-file .env up -d --build
```

Default services today: `chinta-db`, `chinta-auth`, `chinta-backend`, `chinta-gateway`, `chinta-platform`.  
*(Planned: `chinta-ui`, optional `prometheus`.)*

---

## 3) Apply platform schema (until E3 automates this)

On a **fresh** database volume:

```bash
docker compose exec -T chinta-db psql -U chinta_user -d chinta \
  < chinta-platform/migrations/001_platform_core.sql
```

Or from the host if port 5432 is published:

```bash
psql "postgresql://chinta_user:chinta_password@localhost:5432/chinta" \
  -f chinta-platform/migrations/001_platform_core.sql
```

---

## 4) Bootstrap demo tenant and user

Use `chinta-admin` with platform URL `http://localhost:8085` (direct to platform) or follow `docs/ADMIN_V1.md`.

```bash
export CHINTA_PLATFORM_URL=http://localhost:8085
export CHINTA_PLATFORM_ADMIN_TOKEN=dev-admin-token-change-me   # match .env

# Create platform user (use your real OIDC sub after first login, or a placeholder for API-only tests)
python chinta-admin/cli.py user create --email you@example.com --sub "google-oauth2|YOUR_SUB"

# Create tenant owned by that user
python chinta-admin/cli.py tenant create --slug demo --name "Demo" --owner-user-id "<uuid>"

# Optional: verify
python chinta-admin/cli.py tenant get --slug demo
```

*(Planned: `./scripts/seed-demo-tenant.sh` wrapping the above.)*

Set in `.env`: `CHINTA_DEFAULT_TENANT_SLUG=demo`.

---

## 5) Verify APIs

```bash
curl -sf http://localhost:8083/health
curl -sf http://localhost:8084/health
curl -sf http://localhost:8080/health
curl -sf http://localhost:8085/health
```

Without a Bearer token, gateway userinfo should reject:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8084/me   # expect 401
```

Notes (requires valid OIDC access token and membership):

```bash
curl -H "Authorization: Bearer <access_token>" \
     -H "X-Tenant-Id: demo" \
     http://localhost:8084/api/notes
```

---

## 6) Browser (after chinta-ui lands)

1. Open `http://localhost:8084/` (gateway redirects to UI).
2. Sign in with your IdP.
3. Use Notes in the shell; confirm title `CHINTA_COMPANY_NAME: Notes - <your name>`.

Until `chinta-ui` exists, use Swagger at http://localhost:8084/docs and API calls above.

---

## 7) OAuth reminder

| Setting | Value |
|---------|--------|
| `OIDC_REDIRECT_URI_BASE` | `http://localhost:8084` |
| Callback path | `/auth/callback` (proxied to auth service) |
| IdP authorized redirect | `http://localhost:8084/auth/callback` |

---

## 8) Tear down

```bash
docker compose --env-file .env down
# Remove DB volume if you need a clean slate:
# docker compose --env-file .env down -v
```
