#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
POLICY_DIR="${ROOT_DIR}/evaluation/opa-spike"
OPA_IMAGE="openpolicyagent/opa@sha256:cba27d3c6af2feba1e4d6e6b5e24df5b53db332420d4148a90acccd12efae6ed"

run_opa() {
  docker run --rm \
    -v "${POLICY_DIR}:/policy:ro" \
    "${OPA_IMAGE}" "$@"
}

echo "OPA policy evidence"
echo "repository_commit=$(git -C "${ROOT_DIR}" rev-parse HEAD)"
echo "image=${OPA_IMAGE}"
echo

run_opa version
echo

echo "Policy assertions"
run_opa test /policy/policy.rego /policy/policy_test.rego --verbose
echo

echo "Input scenarios"
for input_file in "${POLICY_DIR}"/inputs/*.json; do
  case_name="$(basename "${input_file}")"
  echo "== ${case_name} =="
  echo "allow:"
  run_opa eval --format pretty \
    --data /policy/policy.rego \
    --input "/policy/inputs/${case_name}" \
    data.siot.authz.allow
  echo "deny_reason:"
  run_opa eval --format pretty \
    --data /policy/policy.rego \
    --input "/policy/inputs/${case_name}" \
    data.siot.authz.deny_reason
  echo
done
