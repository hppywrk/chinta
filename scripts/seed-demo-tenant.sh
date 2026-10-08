#!/usr/bin/env bash
# Bootstrap a demo platform user + tenant for local product v1.
# Requires: chinta-platform running, DDL applied, Python venv with chinta-admin deps.
# See docs/LOCAL_DEPLOY_V1.md

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export CHINTA_PLATFORM_URL="${CHINTA_PLATFORM_URL:-http://localhost:8085}"
export CHINTA_PLATFORM_ADMIN_TOKEN="${CHINTA_PLATFORM_ADMIN_TOKEN:-dev-admin-token-change-me}"

SLUG="${CHINTA_DEFAULT_TENANT_SLUG:-demo}"
EMAIL="${CHINTA_DEMO_USER_EMAIL:-demo@example.com}"
SUB="${CHINTA_DEMO_USER_SUB:-local-demo-sub}"
NAME="${CHINTA_DEMO_TENANT_NAME:-Demo}"

CLI=(python "${ROOT}/chinta-admin/cli.py")

if ! curl -sf "${CHINTA_PLATFORM_URL}/health" >/dev/null; then
  echo "seed-demo-tenant: platform not healthy at ${CHINTA_PLATFORM_URL}" >&2
  exit 1
fi

if "${CLI[@]}" tenant get --slug "${SLUG}" --output json >/dev/null 2>&1; then
  echo "seed-demo-tenant: tenant slug '${SLUG}' already exists"
  exit 0
fi

USER_JSON="$("${CLI[@]}" user create --email "${EMAIL}" --sub "${SUB}" --name "Demo User" --output json)"
USER_ID="$(python -c "import json,sys; print(json.load(sys.stdin)['user_id'])" <<<"${USER_JSON}")"

"${CLI[@]}" tenant create --slug "${SLUG}" --name "${NAME}" --owner-user-id "${USER_ID}" --output table
echo "seed-demo-tenant: created tenant '${SLUG}' for ${EMAIL}"
