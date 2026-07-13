#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="${ROOT_DIR}/.e2e-runtime"
DATA_DIR="${RUNTIME_DIR}/interface-partition"
export E2E_CREDENTIALS_DIR="${DATA_DIR}"
export E2E_MODBUS_CONFIG="${RUNTIME_DIR}/modbustcp-endpoints_demonstrator.xml"
export MARIADB_ROOT_PASSWORD="${MARIADB_ROOT_PASSWORD:-E2E-Root-Password-Only-2026}"
export MARIADB_VOR1_PASSWORD="${MARIADB_VOR1_PASSWORD:-E2E-VoR1-Password-Only-2026}"
export MARIADB_VOR2_PASSWORD="${MARIADB_VOR2_PASSWORD:-E2E-VoR2-Password-Only-2026}"
COMPOSE=(docker compose -f "${ROOT_DIR}/docker-compose.yaml" -f "${ROOT_DIR}/tests/e2e/docker-compose.e2e.yaml")

: "${ADMIN_PASSWORD:?Set ADMIN_PASSWORD to a test-only password of at least 21 characters}"
if [[ "${#ADMIN_PASSWORD}" -lt 21 || ! "${ADMIN_PASSWORD}" =~ [[:upper:]] || ! "${ADMIN_PASSWORD}" =~ [[:lower:]] || ! "${ADMIN_PASSWORD}" =~ [[:digit:]] ]]; then
  echo "ADMIN_PASSWORD must be at least 21 characters and contain uppercase, lowercase, and digits" >&2
  exit 2
fi

cleanup() {
  "${COMPOSE[@]}" --profile e2e down --remove-orphans >/dev/null 2>&1 || true
}

on_exit() {
  local status="$?"
  if [[ "${status}" -ne 0 ]]; then
    "${COMPOSE[@]}" --profile e2e logs --no-color --tail=120 >&2 || true
  fi
  if [[ "${E2E_KEEP_STACK:-false}" != "true" ]]; then
    cleanup
  fi
  exit "${status}"
}
trap on_exit EXIT

rm -rf "${RUNTIME_DIR}"
mkdir -p "${DATA_DIR}"
printf '{"_default": {}}\n' > "${DATA_DIR}/credentials.json"
sed 's#<ipaddr>10.200.1.142</ipaddr>#<ipaddr>192.168.178.181</ipaddr>#' \
  "${ROOT_DIR}/cpc-partition/config/modbustcp-endpoints_demonstrator.xml" \
  > "${E2E_MODBUS_CONFIG}"
chmod 700 "${RUNTIME_DIR}" "${DATA_DIR}"
chmod 600 "${DATA_DIR}/credentials.json" "${E2E_MODBUS_CONFIG}"

export AUTHZ_MODE="casbin_and_opa"

cleanup
"${COMPOSE[@]}" --profile e2e up --build -d \
  brownfield-opcua-server ecotec-modbus-server opa psmo-partition \
  interface-partition cpc-partition intermediate-vor-partition \
  intermediate-vor-partition-cpc

wait_for_service() {
  local service="$1"
  local attempt
  for attempt in $(seq 1 30); do
    if "${COMPOSE[@]}" --profile e2e exec -T "${service}" true >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "ERROR: ${service} did not become ready within 30 seconds" >&2
  return 1
}

for service_component in \
  "brownfield-opcua-server:brownfield-opcua-server" \
  "interface-partition:interface-partition" \
  "intermediate-vor-partition:intermediate-vor-partition" \
  "intermediate-vor-partition-cpc:intermediate-vor-partition-cpc" \
  "psmo-partition:psmo-partition" \
  "cpc-partition:cpc-partition"
do
  service="${service_component%%:*}"
  component="${service_component#*:}"
  wait_for_service "${service}"
  "${COMPOSE[@]}" --profile e2e exec -T "${service}" \
    python3 -c 'import pathlib,sys; root=pathlib.Path("/run/siot-secrets"); visible=sorted(p.name for p in root.iterdir()); expected=[sys.argv[1]]; assert visible == expected, f"expected {expected}, got {visible}"' \
    "${component}"
  echo "PASS secret-scope: ${service} sees ${component} only"
done

# T-12: The NoSecurity brownfield endpoint must not exist in the ordinary E2E
# test profile. Its implementation is available only after a separate explicit
# test opt-in, never by default or in production.
"${COMPOSE[@]}" --profile e2e exec -T brownfield-opcua-server \
  python3 -c 'import socket; probe = socket.socket(); probe.settimeout(1); result = probe.connect_ex(("127.0.0.1", 4841)); probe.close(); assert result != 0, "NoSecurity endpoint unexpectedly listens on 4841"'
echo "PASS nosecurity-disabled: brownfield port 4841 is closed by default"

"${COMPOSE[@]}" --profile e2e build identity-probe

# T-07: the production OPA endpoint is TLS 1.3 with mutual authentication.
# No-certificate callers fail during TLS; a valid certificate belonging to a
# different gateway service reaches OPA but is denied by system.authz.
"${COMPOSE[@]}" --profile e2e run --rm --no-deps \
  --entrypoint python \
  -v "${ROOT_DIR}/.runtime-secrets/cpc-partition:/probe-secrets:ro" \
  identity-probe /probe/opa_mtls_probe.py \
    missing-client \
    https://opa:8181/v1/data/siot/authz/allow \
    /probe-secrets/certs/ca/ca.crt
"${COMPOSE[@]}" --profile e2e run --rm --no-deps \
  --entrypoint python \
  -v "${ROOT_DIR}/.runtime-secrets/cpc-partition:/probe-secrets:ro" \
  identity-probe /probe/opa_mtls_probe.py \
    foreign-identity \
    https://opa:8181/v1/data/siot/authz/allow \
    /probe-secrets/certs/ca/ca.crt \
    /probe-secrets/certs/client/client.crt \
    /probe-secrets/certs/client/client.key

probe_wrong_identity() {
  local rpc="$1" target="$2" server_name="$3" source="$4"
  local key="$5" certificate="$6" ca="$7"
  "${COMPOSE[@]}" --profile e2e run --rm --no-deps \
    -v "${ROOT_DIR}/.runtime-secrets/${source}:/probe-secrets:ro" \
    identity-probe \
    "${rpc}" "${target}" "${server_name}" \
      "/probe-secrets/${key}" "/probe-secrets/${certificate}" "/probe-secrets/${ca}"
}

# A shared CA proves membership in the trust domain, not authorization for
# every service. Each server must reject a valid certificate issued to a
# different gateway component.
probe_wrong_identity request \
  intermediate-vor-partition:50051 intermediate-vor-partition \
  intermediate-vor-partition-cpc \
  certificates/pipeline/client/client.key \
  certificates/pipeline/client/client.crt \
  certificates/pipeline/ca/ca.crt
probe_wrong_identity processing \
  intermediate-vor-partition-cpc:50052 intermediate-vor-partition-cpc \
  interface-partition \
  certificates/grpc/client/client.key \
  certificates/grpc/client/client.crt \
  certificates/grpc/ca/ca.crt
probe_wrong_identity cpc \
  cpc-partition:50053 cpc-partition \
  intermediate-vor-partition \
  certificates/pipeline/client/client.key \
  certificates/pipeline/client/client.crt \
  certificates/pipeline/ca/ca.crt
probe_wrong_identity json \
  interface-partition:50051 interface-partition \
  intermediate-vor-partition \
  certificates/pipeline/client/client.key \
  certificates/pipeline/client/client.crt \
  certificates/pipeline/ca/ca.crt
probe_wrong_identity json \
  psmo-partition:50051 psmo-partition \
  intermediate-vor-partition \
  certificates/pipeline/client/client.key \
  certificates/pipeline/client/client.crt \
  certificates/pipeline/ca/ca.crt

"${COMPOSE[@]}" --profile e2e run --build --rm --no-deps e2e-runner
