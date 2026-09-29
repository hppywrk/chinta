#!/usr/bin/env bash
# Regression: default CD stack must build/start chinta-backend (notes API),
# and CHINTA_COMPOSE_SERVICES from deploy.env must override after source.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="${ROOT}/scripts/deploy/vm-deploy.sh"
UNIT="${ROOT}/rootfs/etc/systemd/system/chinta-compose.service"
EXAMPLE="${ROOT}/config/deploy.env.example"

fail() { echo "FAIL: $*" >&2; exit 1; }

grep -q 'chinta-backend' "${SCRIPT}" || fail "vm-deploy.sh missing chinta-backend default"
grep -q 'chinta-backend' "${UNIT}" || fail "chinta-compose.service missing chinta-backend"
grep -q 'chinta-backend' "${EXAMPLE}" || fail "deploy.env.example missing chinta-backend"

# Simulate the resolve order from vm-deploy.sh (source env, then assign).
tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT
cat >"${tmpdir}/deploy.env" <<'EOF'
CHINTA_COMPOSE_SERVICES="only-from-env"
EOF

# shellcheck disable=SC1090
source "${tmpdir}/deploy.env"
COMPOSE_SERVICES="${CHINTA_COMPOSE_SERVICES:-chinta-db chinta-auth chinta-backend chinta-gateway}"
[[ "${COMPOSE_SERVICES}" == "only-from-env" ]] || fail "deploy.env override ignored (got: ${COMPOSE_SERVICES})"

unset CHINTA_COMPOSE_SERVICES
COMPOSE_SERVICES="${CHINTA_COMPOSE_SERVICES:-chinta-db chinta-auth chinta-backend chinta-gateway}"
[[ "${COMPOSE_SERVICES}" == *chinta-backend* ]] || fail "default stack missing chinta-backend"

echo "OK: deploy service defaults and deploy.env override order"
