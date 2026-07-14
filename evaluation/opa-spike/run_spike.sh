#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLICY_FILE="${SCRIPT_DIR}/policy.rego"

if ! command -v opa >/dev/null 2>&1; then
  echo "ERROR: OPA binary not found; policy tests were not executed." >&2
  echo "Install OPA and run: bash ${SCRIPT_DIR}/run_spike.sh" >&2
  exit 127
fi

echo "Running OPA spike with policy: ${POLICY_FILE}"
echo

opa test "${SCRIPT_DIR}/policy.rego" "${SCRIPT_DIR}/policy_test.rego" --verbose
echo

for input_file in "${SCRIPT_DIR}"/inputs/*.json; do
  case_name="$(basename "${input_file}")"
  echo "== ${case_name} =="
  echo "allow:"
  opa eval --format pretty --data "${POLICY_FILE}" --input "${input_file}" "data.siot.authz.allow"
  echo "deny_reason:"
  opa eval --format pretty --data "${POLICY_FILE}" --input "${input_file}" "data.siot.authz.deny_reason"
  echo
done
