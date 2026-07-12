#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="${SIOT_RUNTIME_SECRETS_DIR:-${ROOT_DIR}/.runtime-secrets}"
DATA_DIR="${SIOT_RUNTIME_DATA_DIR:-${ROOT_DIR}/.runtime-data}"
if [[ $# -gt 0 ]]; then
  echo "ERROR: Unsupported option: $1" >&2
  echo "This script never deletes source material. Remove legacy files through a reviewed change." >&2
  exit 2
fi

copy_tree() {
  local src="$1"
  local dst="$2"
  if [[ -d "${src}" ]]; then
    mkdir -p "${dst}"
    cp -a "${src}/." "${dst}/"
    echo "Copied ${src} -> ${dst}"
  fi
}

copy_file() {
  local src="$1"
  local dst="$2"
  if [[ ! -f "${src}" ]]; then
    echo "ERROR: Required generated credential is missing: ${src}" >&2
    echo "Run _generated_certificates/grpc/generate-grpc-certs.sh first." >&2
    exit 1
  fi
  mkdir -p "$(dirname "${dst}")"
  cp -a "${src}" "${dst}"
}

install_pipeline_identity() {
  local generated_name="$1"
  local component="$2"
  local component_base="${RUNTIME_DIR}/${component}/certificates/pipeline"
  local generated_base="${ROOT_DIR}/_generated_certificates/grpc/${generated_name}"

  copy_file "${ROOT_DIR}/_generated_certificates/grpc/ca/ca.crt" \
            "${component_base}/ca/ca.crt"
  shift 2
  local identity
  for identity in "$@"; do
    copy_file "${generated_base}/${identity}.crt" \
              "${component_base}/${identity}/${identity}.crt"
    copy_file "${generated_base}/${identity}.key" \
              "${component_base}/${identity}/${identity}.key"
  done
}

install_grpc_identity() {
  local generated_name="$1"
  local identity="$2"
  local component="$3"
  local relative_target="$4"
  local generated_base="${ROOT_DIR}/_generated_certificates/grpc/${generated_name}"
  local target="${RUNTIME_DIR}/${component}/${relative_target}"

  copy_file "${generated_base}/${identity}.crt" "${target}/${identity}.crt"
  copy_file "${generated_base}/${identity}.key" "${target}/${identity}.key"
}

initialize_credentials() {
  local src="$1"
  local dst="$2"
  mkdir -p "$(dirname "${dst}")"
  if [[ -f "${dst}" ]]; then
    echo "Preserved existing runtime credential database: ${dst}"
  elif [[ -f "${src}" ]]; then
    cp -a "${src}" "${dst}"
    echo "Migrated legacy credential database: ${src} -> ${dst}"
  else
    # Valid empty TinyDB document. ADMIN_PASSWORD bootstrap creates the first
    # account and refuses startup if creation or readback fails.
    printf '{"_default": {}}\n' > "${dst}"
    echo "Initialized empty runtime credential database: ${dst}"
  fi
}

echo "Preparing runtime secret directory at: ${RUNTIME_DIR}"
mkdir -p "${RUNTIME_DIR}"

# Mutable credential state is deliberately kept outside the read-only
# certificate mount.  The application refuses a silent legacy fallback.
initialize_credentials \
  "${ROOT_DIR}/interface-partition/user_manager/credentials.json" \
  "${DATA_DIR}/interface-partition/credentials.json"

# Interface partition
copy_tree "${ROOT_DIR}/interface-partition/certificates" \
          "${RUNTIME_DIR}/interface-partition/certificates"
install_grpc_identity "interface-certs" client \
  "interface-partition" "certificates/grpc/client"
install_grpc_identity "interface-certs" server \
  "interface-partition" "certificates/grpc/server"

# Central M+O client
copy_tree "${ROOT_DIR}/central-mo-client/certificates" \
          "${RUNTIME_DIR}/central-mo-client/certificates"

# Intermediate VoR partition
copy_tree "${ROOT_DIR}/intermediate-vor-partition/certificates" \
          "${RUNTIME_DIR}/intermediate-vor-partition/certificates"
install_grpc_identity "intermediate-vor-certs" server \
  "intermediate-vor-partition" "certificates/grpc/server"

# Typed request pipeline identities. Each component receives only its own key
# and the shared CA certificate.
install_pipeline_identity "intermediate-vor-certs" \
  "intermediate-vor-partition" client
install_pipeline_identity "intermediate-vor-cpc-certs" \
  "intermediate-vor-partition-cpc" server client
install_pipeline_identity "cpc-certs" "cpc-partition" server

# psM+O partition
copy_tree "${ROOT_DIR}/psmo-partition/certs" \
          "${RUNTIME_DIR}/psmo-partition/certs"
install_grpc_identity "psmo-certs" server \
  "psmo-partition" "certs/server"

# CPC partition
copy_tree "${ROOT_DIR}/cpc-partition/certs" \
          "${RUNTIME_DIR}/cpc-partition/certs"
install_grpc_identity "cpc-certs" client \
  "cpc-partition" "certs/client"
copy_tree "${ROOT_DIR}/cpc-partition/opcua_client/certificates" \
          "${RUNTIME_DIR}/cpc-partition/opcua_client/certificates"

# Brownfield OPC UA server
copy_tree "${ROOT_DIR}/brownfield-opcua-server/opcua_secured_server/certificates" \
          "${RUNTIME_DIR}/brownfield-opcua-server/opcua_secured_server/certificates"

# Restrict copied material independently of the source-tree permissions.
find "${RUNTIME_DIR}" -type d -exec chmod 700 {} +
find "${RUNTIME_DIR}" -type f -exec chmod 600 {} +
find "${DATA_DIR}" -type d -exec chmod 700 {} +
chmod 600 "${DATA_DIR}/interface-partition/credentials.json"

echo
echo "Done."
echo "Runtime secrets are available under: ${RUNTIME_DIR}"
echo "Mutable credential data is available under: ${DATA_DIR}"
echo "Services read external secrets via SIOT_SECRETS_ROOT (default: /run/siot-secrets)."
echo "docker-compose mounts secrets read-only and credential data read-write."
