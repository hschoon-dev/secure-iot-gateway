#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NETWORK="siot-policy-comparison-$$"
OPA_CONTAINER="siot-policy-opa-$$"
INTERFACE_IMAGE="siot-policy-interface-$$"
OPA_IMAGE="openpolicyagent/opa@sha256:cba27d3c6af2feba1e4d6e6b5e24df5b53db332420d4148a90acccd12efae6ed"

cleanup() {
  docker rm -f "${OPA_CONTAINER}" >/dev/null 2>&1 || true
  docker network rm "${NETWORK}" >/dev/null 2>&1 || true
  docker image rm -f "${INTERFACE_IMAGE}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup
docker network create "${NETWORK}" >/dev/null
docker build -q -t "${INTERFACE_IMAGE}" "${ROOT_DIR}/interface-partition" >/dev/null
docker run -d --name "${OPA_CONTAINER}" --network "${NETWORK}" \
  --network-alias opa \
  -v "${ROOT_DIR}/evaluation/opa-spike/policy.rego:/policy.rego:ro" \
  "${OPA_IMAGE}" run --server --addr=0.0.0.0:8181 /policy.rego >/dev/null
docker run --rm --network "${NETWORK}" \
  -v "${ROOT_DIR}/evaluation/casbin-abac:/evaluation:ro" \
  "${INTERFACE_IMAGE}" \
  python /evaluation/compare.py \
    --opa-url http://opa:8181/v1/data/siot/authz/allow \
    --iterations "${COMPARISON_ITERATIONS:-1000}"
