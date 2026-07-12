#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
COPY_DIR="${TMP_DIR}/gateway"
export COMPOSE_PROJECT_NAME="siot-rotation-e2e-$$"
COMPOSE=(
  docker compose
  -f "${COPY_DIR}/docker-compose.yaml"
  -f "${COPY_DIR}/tests/e2e/docker-compose.e2e.yaml"
)

cleanup() {
  if [[ -f "${COPY_DIR}/docker-compose.yaml" ]]; then
    "${COMPOSE[@]}" --profile e2e down --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

command -v rsync >/dev/null
command -v openssl >/dev/null

rsync -a \
  --exclude .git \
  --exclude .runtime-secrets \
  --exclude .runtime-data \
  --exclude .e2e-runtime \
  --exclude .secrets-backup \
  --exclude '*.log' \
  "${ROOT_DIR}/" "${COPY_DIR}/"

GRPC="${COPY_DIR}/_generated_certificates/grpc"
find "${GRPC}" -type f \( -name '*.crt' -o -name '*.key' -o -name '*.csr' \) -delete
mkdir -p "${GRPC}/ca"
openssl genrsa -out "${GRPC}/ca/ca.key" 2048 >/dev/null 2>&1
openssl req -x509 -new -key "${GRPC}/ca/ca.key" -sha256 -days 30 \
  -out "${GRPC}/ca/ca.crt" -subj "/O=SIoT Test/CN=Old Rotation CA" \
  >/dev/null 2>&1
printf '01\n' > "${GRPC}/ca/ca.srl"

KEY_BITS=2048 CERT_DAYS=30 \
  bash "${GRPC}/generate-grpc-certs.sh" >/dev/null
bash "${COPY_DIR}/secret_migration.sh" >/dev/null

OLD_CA_FP="$(openssl x509 -in "${GRPC}/ca/ca.crt" -noout -fingerprint -sha256)"
OLD_CLIENTS="${COPY_DIR}/rotation-old-clients"
mkdir -p "${OLD_CLIENTS}"
for component_path in \
  "interface-partition:certificates/grpc/client" \
  "intermediate-vor-partition:certificates/pipeline/client" \
  "intermediate-vor-partition-cpc:certificates/pipeline/client" \
  "cpc-partition:certs/client"
do
  component="${component_path%%:*}"
  path="${component_path#*:}"
  mkdir -p "${OLD_CLIENTS}/${component}"
  cp -a "${COPY_DIR}/.runtime-secrets/${component}/${path}/." \
    "${OLD_CLIENTS}/${component}/"
done

assert_old_clients_complete() {
  local component
  for component in \
    interface-partition intermediate-vor-partition \
    intermediate-vor-partition-cpc cpc-partition
  do
    [[ -s "${OLD_CLIENTS}/${component}/client.key" && \
       -s "${OLD_CLIENTS}/${component}/client.crt" ]] || {
      echo "ERROR: saved old identity is incomplete: ${component}" >&2
      return 1
    }
  done
}
assert_old_clients_complete

KEY_BITS=2048 CA_DAYS=30 CERT_DAYS=30 SKIP_NODE_RED_ROTATION=true \
  bash "${COPY_DIR}/rotate-secrets.sh" >/dev/null
assert_old_clients_complete

NEW_CA_FP="$(openssl x509 -in "${GRPC}/ca/ca.crt" -noout -fingerprint -sha256)"
if [[ "${OLD_CA_FP}" == "${NEW_CA_FP}" ]]; then
  echo "ERROR: CA fingerprint did not change" >&2
  exit 1
fi
echo "EVIDENCE ${OLD_CA_FP}"
echo "EVIDENCE ${NEW_CA_FP}"
echo "PASS rotation: CA fingerprint changed"

truststore_count=0
while IFS= read -r trust_anchor; do
  truststore_count=$((truststore_count + 1))
  trust_fp="$(openssl x509 -in "${trust_anchor}" -noout -fingerprint -sha256)"
  if [[ "${trust_fp}" != "${NEW_CA_FP}" ]]; then
    echo "ERROR: stale trust anchor after rotation: ${trust_anchor#${COPY_DIR}/}" >&2
    exit 1
  fi
  echo "EVIDENCE new trust anchor: ${trust_anchor#${COPY_DIR}/}"
done < <(find "${COPY_DIR}/.runtime-secrets" -type f -name ca.crt | sort)
if [[ "${truststore_count}" -lt 5 ]]; then
  echo "ERROR: expected at least five runtime CA trust anchors, got ${truststore_count}" >&2
  exit 1
fi
echo "PASS trust replacement: ${truststore_count} runtime CA files contain only the new CA"

# The regular E2E suite now runs against the rotated trust material. It proves
# all intended peers, per-service secret scopes, five valid-but-foreign client
# denials and the complete OPC-UA -> policy -> gRPC -> Modbus path.
export ADMIN_PASSWORD="${ADMIN_PASSWORD:-Rotation-Only-Admin-Password-2026}"
export E2E_CREDENTIALS_DIR="${COPY_DIR}/.e2e-runtime/interface-partition"
export E2E_MODBUS_CONFIG="${COPY_DIR}/.e2e-runtime/modbustcp-endpoints_demonstrator.xml"
export MARIADB_ROOT_PASSWORD="${MARIADB_ROOT_PASSWORD:-E2E-Root-Password-Only-2026}"
export MARIADB_VOR1_PASSWORD="${MARIADB_VOR1_PASSWORD:-E2E-VoR1-Password-Only-2026}"
export MARIADB_VOR2_PASSWORD="${MARIADB_VOR2_PASSWORD:-E2E-VoR2-Password-Only-2026}"
E2E_KEEP_STACK=true bash "${COPY_DIR}/tests/e2e/run.sh"
assert_old_clients_complete

probe_identity() {
  local expectation="$1" rpc="$2" target="$3" server_name="$4"
  local client_root="$5"
  local connect_timeout=20
  if [[ "${expectation}" == "tls-rejected" ]]; then
    connect_timeout=5
  fi
  [[ -s "${client_root}/client.key" && -s "${client_root}/client.crt" ]] || {
    echo "ERROR: probe identity is incomplete: ${client_root#${COPY_DIR}/}" >&2
    return 1
  }
  "${COMPOSE[@]}" --profile e2e run --rm --no-deps \
    -v "${client_root}:/probe-client:ro" \
    -v "${GRPC}/ca/ca.crt:/probe-ca.crt:ro" \
    identity-probe \
    "${rpc}" "${target}" "${server_name}" \
      /probe-client/client.key /probe-client/client.crt /probe-ca.crt \
      --expect "${expectation}" \
      --connect-timeout "${connect_timeout}"
}

probe_obsolete_identity() {
  local rpc="$1" target="$2" server_name="$3" component="$4" new_path="$5"
  local new_client="${COPY_DIR}/.runtime-secrets/${component}/${new_path}"
  local old_client="${OLD_CLIENTS}/${component}"

  # Bracket the negative check with the new identity. This distinguishes an
  # obsolete-client rejection from an unavailable or crashed server.
  probe_identity accepted-identity "${rpc}" "${target}" "${server_name}" "${new_client}"
  probe_identity tls-rejected "${rpc}" "${target}" "${server_name}" "${old_client}"
  probe_identity accepted-identity "${rpc}" "${target}" "${server_name}" "${new_client}"
}

# Each post-rotation server must reject the old identity of its formerly
# intended caller while the probe still trusts the new server CA.
probe_obsolete_identity request \
  intermediate-vor-partition:50051 intermediate-vor-partition \
  interface-partition certificates/grpc/client
probe_obsolete_identity processing \
  intermediate-vor-partition-cpc:50052 intermediate-vor-partition-cpc \
  intermediate-vor-partition certificates/pipeline/client
probe_obsolete_identity cpc \
  cpc-partition:50053 cpc-partition \
  intermediate-vor-partition-cpc certificates/pipeline/client
probe_obsolete_identity json \
  interface-partition:50051 interface-partition \
  cpc-partition certs/client
probe_obsolete_identity json \
  psmo-partition:50051 psmo-partition \
  cpc-partition certs/client

echo "EVIDENCE compose images after rotation"
"${COMPOSE[@]}" --profile e2e images
echo "PASS T-02 evaluated-deployment acceptance: new path works and all old peers are rejected"
