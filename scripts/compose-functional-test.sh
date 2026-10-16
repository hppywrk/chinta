#!/usr/bin/env bash
# Product v1 compose functional test (E7): health, seed, notes via gateway.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.ci.yml)
SERVICES=(chinta-db chinta-auth chinta-backend chinta-gateway chinta-platform chinta-ui)

export CHINTA_PLATFORM_URL="${CHINTA_PLATFORM_URL:-http://localhost:8085}"
export CHINTA_PLATFORM_ADMIN_TOKEN="${CHINTA_PLATFORM_ADMIN_TOKEN:-dev-admin-token-change-me}"
export CHINTA_DEFAULT_TENANT_SLUG="${CHINTA_DEFAULT_TENANT_SLUG:-demo}"
export CHINTA_DEMO_USER_SUB="${CHINTA_DEMO_USER_SUB:-local-demo-sub}"
export OIDC_CLIENT_ID="${OIDC_CLIENT_ID:-ci}"

log() {
  echo "compose-ft: $*" >&2
}

wait_postgres() {
  for _ in $(seq 1 60); do
    if "${COMPOSE[@]}" exec -T chinta-db pg_isready -U chinta_user -d chinta >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  log "timeout waiting for PostgreSQL"
  "${COMPOSE[@]}" ps
  return 1
}

wait_http() {
  local url="$1"
  local label="$2"
  for _ in $(seq 1 90); do
    if curl -sf "${url}" >/dev/null; then
      return 0
    fi
    sleep 2
  done
  log "timeout waiting for ${label} at ${url}"
  "${COMPOSE[@]}" ps
  return 1
}

mint_ci_jwt() {
  python3 - <<'PY'
import base64
import json
import os

client_id = os.environ["OIDC_CLIENT_ID"]
sub = os.environ["CHINTA_DEMO_USER_SUB"]

def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

header = b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
payload = b64(json.dumps({"sub": sub, "aud": client_id}).encode())
print(f"{header}.{payload}.")
PY
}

cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

log "building and starting stack"
"${COMPOSE[@]}" build "${SERVICES[@]}"
"${COMPOSE[@]}" up -d "${SERVICES[@]}"

wait_postgres

wait_http "http://127.0.0.1:8083/health" "chinta-auth"
wait_http "http://127.0.0.1:8080/health" "chinta-backend"
wait_http "http://127.0.0.1:8084/health" "chinta-gateway"
wait_http "http://127.0.0.1:8085/health" "chinta-platform"
wait_http "http://127.0.0.1:8086/health" "chinta-ui"

log "waiting for platform admin API (DDL ready)"
for _ in $(seq 1 60); do
  if curl -sf -H "Authorization: Bearer ${CHINTA_PLATFORM_ADMIN_TOKEN}" \
    "${CHINTA_PLATFORM_URL}/v1/tenants" >/dev/null; then
    break
  fi
  sleep 2
done
curl -sf -H "Authorization: Bearer ${CHINTA_PLATFORM_ADMIN_TOKEN}" \
  "${CHINTA_PLATFORM_URL}/v1/tenants" >/dev/null \
  || { log "platform admin API not ready"; exit 1; }

log "installing chinta-admin for seed script"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  export PYTHON="${ROOT}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  export PYTHON=python3
fi
if [[ -n "${PYTHON:-}" ]]; then
  "${PYTHON}" -m pip install -q -r "${ROOT}/chinta-admin/requirements.txt"
fi

log "seeding demo tenant"
bash "${ROOT}/scripts/seed-demo-tenant.sh"

TOKEN="$(mint_ci_jwt)"
TENANT="${CHINTA_DEFAULT_TENANT_SLUG}"

log "creating note via gateway"
CREATE_BODY="$(curl -sf \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-Id: ${TENANT}" \
  -H "Content-Type: application/json" \
  -d '{"body":"compose-ft"}' \
  "http://127.0.0.1:8084/api/notes")"

NOTE_ID="$(python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" <<<"${CREATE_BODY}")"
[[ -n "${NOTE_ID}" ]] || { log "missing note id in create response"; exit 1; }

log "listing notes via gateway"
LIST="$(curl -sf \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-Id: ${TENANT}" \
  "http://127.0.0.1:8084/api/notes?limit=10")"

export LIST_JSON="${LIST}" NOTE_ID="${NOTE_ID}"
python3 -c "
import json, os
notes = json.loads(os.environ['LIST_JSON'])
ids = {n.get('id') for n in notes}
assert os.environ['NOTE_ID'] in ids, ids
"

log "OK"
