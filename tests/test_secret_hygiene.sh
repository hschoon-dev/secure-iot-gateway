#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

tracked_secrets="$({
  git -C "${ROOT_DIR}" ls-files
} | grep -E '(^|/)(credentials\.json|[^/]*\.key|[^/]*_key\.pem|ca\.key)$' || true)"

if [[ -n "${tracked_secrets}" ]]; then
  echo "ERROR: Private key or credential database remains tracked:" >&2
  echo "${tracked_secrets}" >&2
  exit 1
fi

SIOT_RUNTIME_SECRETS_DIR="${TMP_DIR}/secrets" \
SIOT_RUNTIME_DATA_DIR="${TMP_DIR}/data" \
  bash "${ROOT_DIR}/secret_migration.sh" >/dev/null

credentials="${TMP_DIR}/data/interface-partition/credentials.json"
[[ -f "${credentials}" ]]
if stat -f '%Lp' "${credentials}" >/dev/null 2>&1; then
  permissions="$(stat -f '%Lp' "${credentials}")"
else
  permissions="$(stat -c '%a' "${credentials}")"
fi
[[ "${permissions}" == "600" ]]

if grep -R -n --include='*.py' \
  'Using legacy .*Set SIOT_SECRETS_ROOT' "${ROOT_DIR}" >/dev/null; then
  echo "ERROR: A silent legacy secret fallback remains in Python code." >&2
  exit 1
fi

echo "Secret hygiene checks passed."
bash "${ROOT_DIR}/tests/test_deployment_secret_guard.sh"
bash "${ROOT_DIR}/tests/test_local_secret_setup.sh"
bash "${ROOT_DIR}/tests/test_stage_runtime_secrets.sh"
bash "${ROOT_DIR}/tests/test_runtime_secret_activation.sh"
bash "${ROOT_DIR}/tests/test_retire_old_secrets.sh"
