#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT
FIXTURE="${TMP_DIR}/fixture"
STAGE_DIR="${TMP_DIR}/stage"
mkdir -p "${FIXTURE}"

cp "${ROOT_DIR}/stage-runtime-secrets.sh" "${FIXTURE}/stage-runtime-secrets.sh"
printf '%s\n' \
  '#!/usr/bin/env bash' \
  'set -euo pipefail' \
  'mkdir -p "${SIOT_RUNTIME_SECRETS_DIR}/component" "${SIOT_RUNTIME_DATA_DIR}/interface"' \
  'printf "staged-secret\\n" >"${SIOT_RUNTIME_SECRETS_DIR}/component/value"' \
  'printf "staged-data\\n" >"${SIOT_RUNTIME_DATA_DIR}/interface/value"' \
  >"${FIXTURE}/secret_migration.sh"
chmod 755 "${FIXTURE}/secret_migration.sh"

bash "${FIXTURE}/stage-runtime-secrets.sh" --stage-dir "${STAGE_DIR}" >/dev/null

[[ "$(<"${STAGE_DIR}/runtime-secrets/component/value")" == "staged-secret" ]]
[[ "$(<"${STAGE_DIR}/runtime-data/interface/value")" == "staged-data" ]]

if bash "${FIXTURE}/stage-runtime-secrets.sh" --stage-dir "${STAGE_DIR}" >/dev/null 2>&1; then
  echo "ERROR: staging reused an existing stage directory" >&2
  exit 1
fi

echo "PASS runtime staging creates a complete isolated tree"
