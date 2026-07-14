#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT
ENV_FILE="${TMP_DIR}/.env"

bash "${ROOT_DIR}/setup-local-secrets.sh" --env-file "${ENV_FILE}"

if stat -f '%Lp' "${ENV_FILE}" >/dev/null 2>&1; then
  permissions="$(stat -f '%Lp' "${ENV_FILE}")"
else
  permissions="$(stat -c '%a' "${ENV_FILE}")"
fi
[[ "${permissions}" == "600" ]]

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

[[ "${SIOT_DEPLOYMENT_MODE}" == "production" ]]
for variable in ADMIN_PASSWORD MARIADB_ROOT_PASSWORD MARIADB_VOR1_PASSWORD MARIADB_VOR2_PASSWORD; do
  value="${!variable}"
  [[ "${#value}" -ge 21 ]]
  [[ "${value}" =~ [[:upper:]] && "${value}" =~ [[:lower:]] && "${value}" =~ [[:digit:]] ]]
done

if bash "${ROOT_DIR}/setup-local-secrets.sh" --env-file "${ENV_FILE}" >/dev/null 2>&1; then
  echo "ERROR: setup overwrote an existing .env without --force" >&2
  exit 1
fi

echo "PASS local secret setup creates protected, policy-compliant credentials"
