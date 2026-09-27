#!/usr/bin/env bash
# Deploy Chinta on a Linux VM via docker compose (see docker-compose.yml).

set -euo pipefail

GIT_REF="${1:-main}"
CHINTA_ROOT="${CHINTA_ROOT:-/opt/chinta}"
DEPLOY_ENV="${CHINTA_DEPLOY_ENV:-/etc/chinta/deploy.env}"
COMPOSE_FILE="${CHINTA_ROOT}/docker-compose.yml"
# Space-separated service names from the default stack (override in deploy.env).
COMPOSE_SERVICES="${CHINTA_COMPOSE_SERVICES:-chinta-db chinta-auth chinta-gateway}"
SYSTEMD_UNIT="chinta-compose.service"

log() { echo "[vm-deploy] $*"; }

if [[ -f "${DEPLOY_ENV}" ]]; then
  # shellcheck disable=SC1090
  source "${DEPLOY_ENV}"
fi

export CHINTA_DEPLOY_ENV="${DEPLOY_ENV}"

if [[ ! -d "${CHINTA_ROOT}/.git" ]]; then
  log "ERROR: ${CHINTA_ROOT} is not a git checkout"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  log "ERROR: docker and docker compose plugin are required for VM deploy"
  exit 1
fi

cd "${CHINTA_ROOT}"
log "Fetching and checking out ${GIT_REF}"
git fetch origin "${GIT_REF}"
git checkout "${GIT_REF}"
git reset --hard "origin/${GIT_REF}" 2>/dev/null || git reset --hard "${GIT_REF}"

compose() {
  local env_args=()
  if [[ -f "${DEPLOY_ENV}" ]]; then
    env_args=(--env-file "${DEPLOY_ENV}")
  fi
  docker compose -f "${COMPOSE_FILE}" "${env_args[@]}" "$@"
}

log "Validating docker-compose.yml"
OIDC_CLIENT_ID="${OIDC_CLIENT_ID:-validate}" OIDC_CLIENT_SECRET="${OIDC_CLIENT_SECRET:-validate}" \
  compose config -q

# Read shellcheck-friendly service list
read -r -a services <<< "${COMPOSE_SERVICES}"

log "Building images: ${COMPOSE_SERVICES}"
compose build "${services[@]}"

log "Starting stack: ${COMPOSE_SERVICES}"
compose up -d "${services[@]}"

install_systemd_unit() {
  local unit="$1"
  local src="${CHINTA_ROOT}/rootfs/etc/systemd/system/${unit}"
  [[ -f "${src}" ]] || return 0
  log "Installing ${unit} (CHINTA_ROOT=${CHINTA_ROOT})"
  sed "s|/opt/chinta|${CHINTA_ROOT}|g" "${src}" | sudo tee "/etc/systemd/system/${unit}" >/dev/null
}

if command -v systemctl >/dev/null 2>&1; then
  install_systemd_unit "${SYSTEMD_UNIT}"
  if [[ -f "/etc/systemd/system/${SYSTEMD_UNIT}" ]]; then
    sudo systemctl daemon-reload
    sudo systemctl enable "${SYSTEMD_UNIT}"
    sudo systemctl restart "${SYSTEMD_UNIT}" || true
  fi
fi

AUTH_PORT="${PORT:-8083}"
GW_PORT="${CHINTA_GATEWAY_PORT:-8084}"

for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${AUTH_PORT}/health" >/dev/null 2>&1 \
    && curl -sf "http://127.0.0.1:${GW_PORT}/health" >/dev/null 2>&1; then
    log "Auth and gateway health OK"
    break
  fi
  sleep 2
done

if ! curl -sf "http://127.0.0.1:${AUTH_PORT}/health" >/dev/null 2>&1; then
  log "WARN: auth health check failed on port ${AUTH_PORT}"
fi
if ! curl -sf "http://127.0.0.1:${GW_PORT}/health" >/dev/null 2>&1; then
  log "WARN: gateway health check failed on port ${GW_PORT}"
fi

log "Deploy finished for ref ${GIT_REF}"
