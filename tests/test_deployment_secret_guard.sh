#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT
mkdir -p "${TMP_DIR}/secrets"
touch "${TMP_DIR}/secrets/.siot-test-only"

common=(
  SIOT_RUNTIME_SECRETS_DIR="${TMP_DIR}/secrets"
  ADMIN_PASSWORD="Production-Admin-9x-Unique"
  MARIADB_ROOT_PASSWORD="Production-Root-8y-Unique"
  MARIADB_VOR1_PASSWORD="Production-Vor1-7z-Unique"
  MARIADB_VOR2_PASSWORD="Production-Vor2-6w-Unique"
)

env "${common[@]}" SIOT_DEPLOYMENT_MODE=test \
  bash "${ROOT_DIR}/validate-deployment-secrets.sh" >/dev/null

if env "${common[@]}" SIOT_DEPLOYMENT_MODE=production \
  bash "${ROOT_DIR}/validate-deployment-secrets.sh" >/dev/null 2>&1; then
  echo "ERROR: production guard accepted a test-only runtime marker" >&2
  exit 1
fi

rm "${TMP_DIR}/secrets/.siot-test-only"
env "${common[@]}" SIOT_DEPLOYMENT_MODE=production \
  bash "${ROOT_DIR}/validate-deployment-secrets.sh" >/dev/null

if env "${common[@]}" SIOT_DEPLOYMENT_MODE=production \
  ADMIN_PASSWORD="EXAMPLE-TEST-ONLY-ADMIN-DO-NOT-USE" \
  bash "${ROOT_DIR}/validate-deployment-secrets.sh" >/dev/null 2>&1; then
  echo "ERROR: production guard accepted a known example password" >&2
  exit 1
fi

echo "PASS deployment secret guard rejects marked and known example data"
