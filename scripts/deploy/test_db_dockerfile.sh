#!/usr/bin/env bash
# Regression: chinta-db image must use official Postgres so compose
# POSTGRES_* env vars and docker-entrypoint-initdb.d scripts apply.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DF="${ROOT}/Dockerfile.cinta-db"
COMPOSE="${ROOT}/docker-compose.yml"

fail() { echo "FAIL: $*" >&2; exit 1; }

grep -qE '^FROM postgres:' "${DF}" || fail "Dockerfile.cinta-db must FROM official postgres image"
grep -q 'docker-entrypoint-initdb.d' "${DF}" || fail "Dockerfile.cinta-db must install init SQL under docker-entrypoint-initdb.d"
grep -q 'chinta-db/init.sql' "${DF}" || fail "Dockerfile.cinta-db must COPY chinta-db/init.sql"

# Compose must still pass credentials the official entrypoint understands.
grep -q 'POSTGRES_DB: chinta' "${COMPOSE}" || fail "compose missing POSTGRES_DB"
grep -q 'POSTGRES_USER: chinta_user' "${COMPOSE}" || fail "compose missing POSTGRES_USER"
grep -q 'POSTGRES_PASSWORD: chinta_password' "${COMPOSE}" || fail "compose missing POSTGRES_PASSWORD"

# Volume must map to official image PGDATA (not Ubuntu package cluster path).
grep -q 'postgres_data:/var/lib/postgresql/data' "${COMPOSE}" || fail "compose volume must target /var/lib/postgresql/data"

echo "OK: chinta-db Dockerfile uses official Postgres entrypoint contract"
