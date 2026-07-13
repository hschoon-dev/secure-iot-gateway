#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${NODE_RED_IMAGE:-nodered/node-red:4.1.11-22}"
TMP_DIR="$(mktemp -d)"
CONTAINER="siot-node-red-credential-$$"

cleanup() {
  local status="$?"
  if [[ "${status}" -ne 0 ]]; then
    docker logs "${CONTAINER}" >&2 || true
  fi
  docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

node "${ROOT_DIR}/tests/node-red/prepare_docker_credential_fixture.js" "${TMP_DIR}"

docker run -d --name "${CONTAINER}" \
  -v "${TMP_DIR}/data:/data" \
  -v "${TMP_DIR}/secrets:/run/siot-secrets/node-red:ro" \
  "${IMAGE}" >/dev/null

probe_command='const http=require("http"); const request=http.get("http://127.0.0.1:1880/credential-probe", response => { let body=""; response.on("data", chunk => body += chunk); response.on("end", () => { if (response.statusCode !== 200 || body !== "credential-loaded") process.exit(1); }); }); request.on("error", () => process.exit(1)); request.setTimeout(1000, () => { request.destroy(); process.exit(1); });'

for _ in $(seq 1 30); do
  if docker exec "${CONTAINER}" node -e "${probe_command}" >/dev/null 2>&1; then
    echo "PASS Node-RED Docker migration: migrated credential is available to a running flow"
    exit 0
  fi
  sleep 1
done

echo "ERROR: Node-RED did not serve the migrated credential flow within 30 seconds" >&2
exit 1
