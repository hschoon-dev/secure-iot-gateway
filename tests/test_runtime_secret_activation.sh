#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

STAGE_DIR="${TMP_DIR}/stage"
RUNTIME_SECRETS="${TMP_DIR}/active/secrets"
RUNTIME_DATA="${TMP_DIR}/active/data"
BACKUP_DIR="${TMP_DIR}/backup"
mkdir -p "${STAGE_DIR}/runtime-secrets/component" "${STAGE_DIR}/runtime-data/interface" \
  "${RUNTIME_SECRETS}" "${RUNTIME_DATA}"
printf 'new-secret\n' >"${STAGE_DIR}/runtime-secrets/component/value"
printf 'new-data\n' >"${STAGE_DIR}/runtime-data/interface/value"
printf 'old-secret\n' >"${RUNTIME_SECRETS}/value"
printf 'old-data\n' >"${RUNTIME_DATA}/value"

bash "${ROOT_DIR}/activate-runtime-secrets.sh" \
  --stage-dir "${STAGE_DIR}" \
  --runtime-secrets-dir "${RUNTIME_SECRETS}" \
  --runtime-data-dir "${RUNTIME_DATA}" \
  --backup-dir "${BACKUP_DIR}" >/dev/null

[[ "$(<"${RUNTIME_SECRETS}/component/value")" == "new-secret" ]]
[[ "$(<"${RUNTIME_DATA}/interface/value")" == "new-data" ]]
[[ "$(<"${BACKUP_DIR}/runtime-secrets/value")" == "old-secret" ]]
[[ "$(<"${BACKUP_DIR}/runtime-data/value")" == "old-data" ]]
[[ ! -e "${STAGE_DIR}" ]]

echo "PASS staged runtime activation preserves the previous active tree"
