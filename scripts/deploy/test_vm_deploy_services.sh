#!/usr/bin/env bash
# Regression: default CD stack must build/start chinta-backend (notes API) and
# chinta-platform (gateway access resolve). CHINTA_COMPOSE_SERVICES from
# deploy.env must override after source.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="${ROOT}/scripts/deploy/vm-deploy.sh"
UNIT="${ROOT}/rootfs/etc/systemd/system/chinta-compose.service"
EXAMPLE="${ROOT}/config/deploy.env.example"
COMPOSE="${ROOT}/docker-compose.yml"
DEFAULT_STACK="chinta-db chinta-auth chinta-backend chinta-gateway chinta-platform"

fail() { echo "FAIL: $*" >&2; exit 1; }

for svc in chinta-backend chinta-platform; do
  grep -q "${svc}" "${SCRIPT}" || fail "vm-deploy.sh missing ${svc} default"
  grep -q "${svc}" "${UNIT}" || fail "chinta-compose.service missing ${svc}"
  grep -q "${svc}" "${EXAMPLE}" || fail "deploy.env.example missing ${svc}"
done

# Keep shell defaults aligned with compose catalog annotation.
for svc in chinta-backend chinta-platform; do
  grep -q "${svc}" "${COMPOSE}" || fail "docker-compose.yml missing ${svc}"
done
grep -A20 'x-chinta-vm:' "${COMPOSE}" | grep -q 'chinta-platform' \
  || fail "x-chinta-vm.default_services missing chinta-platform"

# Simulate the resolve order from vm-deploy.sh (source env, then assign).
tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT
cat >"${tmpdir}/deploy.env" <<'EOF'
CHINTA_COMPOSE_SERVICES="only-from-env"
EOF

# shellcheck disable=SC1090
source "${tmpdir}/deploy.env"
COMPOSE_SERVICES="${CHINTA_COMPOSE_SERVICES:-$DEFAULT_STACK}"
[[ "${COMPOSE_SERVICES}" == "only-from-env" ]] || fail "deploy.env override ignored (got: ${COMPOSE_SERVICES})"

unset CHINTA_COMPOSE_SERVICES
COMPOSE_SERVICES="${CHINTA_COMPOSE_SERVICES:-$DEFAULT_STACK}"
[[ "${COMPOSE_SERVICES}" == *chinta-backend* ]] || fail "default stack missing chinta-backend"
[[ "${COMPOSE_SERVICES}" == *chinta-platform* ]] || fail "default stack missing chinta-platform"

# systemd must not pass a mandatory docker compose --env-file. vm-deploy restarts
# the unit after compose up; if the file is missing, ExecStop tears the stack down
# and ExecStart fails — leaving auth/gateway/backend unreachable.
if grep -qE 'ExecStart=.*--env-file' "${UNIT}"; then
  fail "chinta-compose.service ExecStart must not require --env-file (use EnvironmentFile=-)"
fi
grep -q 'EnvironmentFile=-/etc/chinta/deploy.env' "${UNIT}" \
  || fail "chinta-compose.service must use optional EnvironmentFile=-"

echo "OK: deploy service defaults and deploy.env override order"
