#!/usr/bin/env bash
# Deploy chinta-auth and chinta-gateway on a Linux VM (systemd).
# Invoked locally on the VM or remotely via GitHub Actions CD workflow.

set -euo pipefail

GIT_REF="${1:-main}"
CHINTA_ROOT="${CHINTA_ROOT:-/opt/chinta}"
VENV="${CHINTA_ROOT}/.venv"
DEPLOY_ENV="${CHINTA_DEPLOY_ENV:-/etc/chinta/deploy.env}"

log() { echo "[vm-deploy] $*"; }

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

if command -v systemctl >/dev/null 2>&1; then
  if systemctl list-unit-files | grep -q '^chinta-auth.service'; then
    log "Restarting systemd units"
    sudo systemctl daemon-reload
    sudo systemctl restart chinta-auth.service chinta-gateway.service
    sudo systemctl is-active --quiet chinta-auth.service
    sudo systemctl is-active --quiet chinta-gateway.service
  else
    log "WARN: chinta-auth.service not installed — skip restart (see docs/CI_CD.md)"
  fi
else
  log "WARN: systemctl not found — skip service restart"
fi

if [[ -f "${DEPLOY_ENV}" ]]; then
  # shellcheck disable=SC1090
  source "${DEPLOY_ENV}"
fi

if curl -sf http://127.0.0.1:8083/health >/dev/null 2>&1; then
  log "Auth health OK"
elif curl -sf http://127.0.0.1:${PORT:-8083}/health >/dev/null 2>&1; then
  log "Auth health OK"
else
  log "WARN: auth health check failed (service may not be running yet)"
fi

log "Deploy finished for ref ${GIT_REF}"
