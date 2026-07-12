#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_ROOT="${SIOT_RUNTIME_SECRETS_DIR:-${ROOT_DIR}/.runtime-secrets}"
MODE="${SIOT_DEPLOYMENT_MODE:-}"
TEST_MARKER="${SECRETS_ROOT}/.siot-test-only"

fail() {
  echo "ERROR: $*" >&2
  exit 2
}

case "${MODE}" in
  test)
    [[ -f "${TEST_MARKER}" ]] || fail \
      "test mode requires ${TEST_MARKER}; generate ephemeral identities with tests/ci/prepare_test_secrets.sh"
    echo "PASS deployment secret guard: explicitly marked test profile"
    exit 0
    ;;
  production)
    [[ ! -f "${TEST_MARKER}" ]] || fail \
      "test-only runtime secrets must never be used in production"
    ;;
  *)
    fail "set SIOT_DEPLOYMENT_MODE explicitly to test or production"
    ;;
esac

required_passwords=(
  ADMIN_PASSWORD
  MARIADB_ROOT_PASSWORD
  MARIADB_VOR1_PASSWORD
  MARIADB_VOR2_PASSWORD
)

for variable in "${required_passwords[@]}"; do
  value="${!variable:-}"
  [[ "${#value}" -ge 21 ]] || fail "${variable} must contain at least 21 characters"
  if [[ "${value}" =~ (EXAMPLE|TEST-ONLY|E2E-|CI-Only|CHANGEME|change-me|password) ]]; then
    fail "${variable} contains a known test/example marker"
  fi
done

[[ -d "${SECRETS_ROOT}" ]] || fail "runtime secret directory does not exist: ${SECRETS_ROOT}"

echo "PASS deployment secret guard: production profile contains no known test markers"
