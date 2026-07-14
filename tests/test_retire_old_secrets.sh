#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT
FIXTURE="${TMP_DIR}/fixture"
BACKUP_ID="20260713-120000"
BACKUP_DIR="${FIXTURE}/.secrets-backup/${BACKUP_ID}"
mkdir -p "${BACKUP_DIR}" "${FIXTURE}/.runtime-secrets"
printf 'old-secret\n' >"${BACKUP_DIR}/value"
printf 'active-secret\n' >"${FIXTURE}/.runtime-secrets/value"
cp "${ROOT_DIR}/retire-old-secrets.sh" "${FIXTURE}/retire-old-secrets.sh"

output="$(bash "${FIXTURE}/retire-old-secrets.sh" --backup "${BACKUP_ID}")"
[[ "${output}" == *"Dry run"* ]]
[[ -d "${BACKUP_DIR}" ]]

output="$(bash "${FIXTURE}/retire-old-secrets.sh" --backup "${BACKUP_ID}" --confirm wrong --delete)"
[[ "${output}" == *"Dry run"* ]]
[[ -d "${BACKUP_DIR}" ]]

bash "${FIXTURE}/retire-old-secrets.sh" \
  --backup "${BACKUP_ID}" --confirm "${BACKUP_ID}" --delete >/dev/null
[[ ! -e "${BACKUP_DIR}" ]]
[[ "$(<"${FIXTURE}/.runtime-secrets/value")" == "active-secret" ]]

echo "PASS backup retirement requires confirmation and preserves active secrets"
