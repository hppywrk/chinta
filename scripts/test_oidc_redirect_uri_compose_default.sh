#!/usr/bin/env bash
# Regression: compose must default OIDC_REDIRECT_URI_BASE to the gateway public
# origin. IdP callbacks omit redirect_uri; auth then exchanges the code with
# {OIDC_REDIRECT_URI_BASE}/auth/callback. Pointing at auth :8083 while the
# browser hits gateway :8084 breaks login with token_exchange_failed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="${ROOT}/docker-compose.yml"

fail() { echo "FAIL: $*" >&2; exit 1; }

grep -q 'OIDC_REDIRECT_URI_BASE:.*http://localhost:8084' "${COMPOSE}" \
  || fail "docker-compose.yml must default OIDC_REDIRECT_URI_BASE to http://localhost:8084"

if grep -q 'OIDC_REDIRECT_URI_BASE:.*http://localhost:8083' "${COMPOSE}"; then
  fail "docker-compose.yml still defaults OIDC_REDIRECT_URI_BASE to auth :8083"
fi

# Dead gateway-only callback env previously looked configured while auth ignored it.
if grep -q 'CHINTA_AUTH_CALLBACK_URL' "${COMPOSE}"; then
  fail "CHINTA_AUTH_CALLBACK_URL is unused; remove it so OIDC_REDIRECT_URI_BASE is the single source of truth"
fi

echo "OK: OIDC_REDIRECT_URI_BASE compose default matches gateway public origin"
