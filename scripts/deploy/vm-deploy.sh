#!/usr/bin/env bash
# Deploy Chinta on a Linux VM: git checkout, Python venv, systemd units.
# Service names/ports match docker-compose.yml; auth and gateway run natively
# under systemd, optional chinta-db via systemd + docker compose.

set -euo pipefail

GIT_REF="${1:-main}"
CHINTA_ROOT="${CHINTA_ROOT:-/opt/chinta}"
VENV="${CHINTA_ROOT}/.venv"
DEPLOY_ENV="${CHINTA_DEPLOY_ENV:-/etc/chinta/deploy.env}"
SYSTEMD_UNITS=(chinta-auth.service chinta-gateway.service)

log() { echo "[vm-deploy] $*"; }

if [[ -f "${DEPLOY_ENV}" ]]; then
  # shellcheck disable=SC1090
  source "${DEPLOY_ENV}"
fi

if [[ ! -d "${CHINTA_ROOT}/.git" ]]; then
  log "ERROR: ${CHINTA_ROOT} is not a git checkout"
  exit 1
fi

cd "${CHINTA_ROOT}"
log "Fetching and checking out ${GIT_REF}"
git fetch origin "${GIT_REF}"
git checkout "${GIT_REF}"
git reset --hard "origin/${GIT_REF}" 2>/dev/null || git reset --hard "${GIT_REF}"

if [[ ! -d "${VENV}" ]]; then
  log "Creating venv at ${VENV}"
  python3.12 -m venv "${VENV}" || python3 -m venv "${VENV}"
fi

# shellcheck disable=SC1091
source "${VENV}/bin/activate"
python -m pip install --upgrade pip
pip install -r chinta-auth/requirements.txt -r chinta-gateway/requirements.txt

log "Validating OpenAPI specs"
python scripts/validate_openapi_specs.py

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  log "Validating docker-compose.yml"
  OIDC_CLIENT_ID="${OIDC_CLIENT_ID:-validate}" OIDC_CLIENT_SECRET="${OIDC_CLIENT_SECRET:-validate}" \
    docker compose -f "${CHINTA_ROOT}/docker-compose.yml" config -q
fi

install_systemd_unit() {
  local unit="$1"
  local src="${CHINTA_ROOT}/rootfs/etc/systemd/system/${unit}"
  [[ -f "${src}" ]] || return 0
  log "Installing ${unit} (CHINTA_ROOT=${CHINTA_ROOT})"
  sed "s|/opt/chinta|${CHINTA_ROOT}|g" "${src}" | sudo tee "/etc/systemd/system/${unit}" >/dev/null
}

if command -v systemctl >/dev/null 2>&1; then
  for unit in "${SYSTEMD_UNITS[@]}"; do
    install_systemd_unit "${unit}"
  done
  if systemctl list-unit-files | grep -q '^chinta-auth.service'; then
    log "Restarting systemd units: ${SYSTEMD_UNITS[*]}"
    sudo systemctl daemon-reload
    sudo systemctl enable "${SYSTEMD_UNITS[@]}"
    sudo systemctl restart "${SYSTEMD_UNITS[@]}"
    for unit in "${SYSTEMD_UNITS[@]}"; do
      sudo systemctl is-active --quiet "${unit}"
    done
  else
    log "WARN: chinta-auth.service not installed — copy units from rootfs (see docs/CI_CD.md)"
  fi
else
  log "WARN: systemctl not found — skip service install/restart"
fi

AUTH_PORT="${PORT:-8083}"
GW_PORT="${CHINTA_GATEWAY_PORT:-8084}"

if curl -sf "http://127.0.0.1:${AUTH_PORT}/health" >/dev/null 2>&1; then
  log "Auth health OK"
else
  log "WARN: auth health check failed on port ${AUTH_PORT}"
fi

if curl -sf "http://127.0.0.1:${GW_PORT}/health" >/dev/null 2>&1; then
  log "Gateway health OK"
else
  log "WARN: gateway health check failed on port ${GW_PORT}"
fi

log "Deploy finished for ref ${GIT_REF}"
