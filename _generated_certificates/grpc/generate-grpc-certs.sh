#!/usr/bin/env bash
set -euo pipefail

# Basis-Verzeichnis (Root des Projekts)
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CA_DIR="${ROOT_DIR}/ca"
CA_KEY="${CA_DIR}/ca.key"
CA_CRT="${CA_DIR}/ca.crt"
CA_SERIAL="${CA_DIR}/ca.srl"

KEY_BITS="${KEY_BITS:-4096}"
CERT_DAYS="${CERT_DAYS:-825}"

echo "== gRPC Zertifikats-Generation =="

# --- CA prüfen -------------------------------------------------------------

if [[ ! -f "${CA_KEY}" || ! -f "${CA_CRT}" ]]; then
  echo "FEHLER: CA-Key oder CA-Cert nicht gefunden:"
  echo "  ${CA_KEY}"
  echo "  ${CA_CRT}"
  exit 1
fi

# Serial-Datei initialisieren (für -CAserial)
if [[ ! -f "${CA_SERIAL}" ]]; then
  echo "01" > "${CA_SERIAL}"
fi

# --- Helper-Funktionen -----------------------------------------------------

generate_server_cert() {
  local dir="$1"
  local name="${2:-server}"   # default: server

  local cnf="${dir}/${name}.cnf"
  local key="${dir}/${name}.key"
  local csr="${dir}/${name}.csr"
  local crt="${dir}/${name}.crt"

  echo ""
  echo "-- Server-Zertifikat in ${dir} (${name}) --"

  if [[ ! -f "${cnf}" ]]; then
    echo "  Übersprungen: Config ${cnf} nicht gefunden."
    return 0
  fi

  # Wenn Zertifikat schon existiert: nichts tun (idempotent)
  if [[ -f "${crt}" ]]; then
    echo "  Zertifikat ${crt} existiert bereits – überspringe."
    return 0
  fi

  # Falls alte Fragmente existieren: aufräumen
  if [[ -f "${key}" || -f "${csr}" ]]; then
    echo "  Entferne alte Key/CSR-Fragmente."
    rm -f "${key}" "${csr}"
  fi

  echo "  Generiere Key: ${key}"
  openssl genrsa -out "${key}" "${KEY_BITS}"

  echo "  Generiere CSR: ${csr}"
  openssl req -new -key "${key}" -out "${csr}" -config "${cnf}"

  # Extension-Section aus req_extensions lesen, z.B.
  # req_extensions = v3_req   oder   req_extensions=req_ext
  local ext_section=""
  ext_section=$(
    grep -E '^[[:space:]]*req_extensions[[:space:]]*=' "${cnf}" \
      | head -n1 \
      | cut -d= -f2 \
      | tr -d '[:space:]'
  )

  # Fallback: falls keine req_extensions-Zeile da ist, heuristisch suchen
  if [[ -z "${ext_section}" ]]; then
    if grep -Eq '^[[:space:]]*\[[[:space:]]*req_ext[[:space:]]*\][[:space:]]*$' "${cnf}"; then
      ext_section="req_ext"
    elif grep -Eq '^[[:space:]]*\[[[:space:]]*v3_req[[:space:]]*\][[:space:]]*$' "${cnf}"; then
      ext_section="v3_req"
    fi
  fi

  # Optional: prüfen, ob es diese Section wirklich gibt
  if [[ -n "${ext_section}" ]]; then
    if ! grep -Eq "^[[:space:]]*\[[[:space:]]*${ext_section}[[:space:]]*\][[:space:]]*$" "${cnf}"; then
      echo "FEHLER: req_extensions=${ext_section}, aber Section [${ext_section}] existiert nicht in ${cnf}."
      return 1
    fi
  fi

  if [[ -z "${ext_section}" ]]; then
    echo "FEHLER: Konnte keine Extension-Section (req_extensions=..., [req_ext], [v3_req]) in ${cnf} bestimmen."
    echo "       Für Server-Zertifikate (SAN etc.) ist das Pflicht."
    return 1
  fi

  echo "  Signiere Zertifikat: ${crt} (Extensions: ${ext_section})"
  openssl x509 -req \
    -in "${csr}" \
    -CA "${CA_CRT}" \
    -CAkey "${CA_KEY}" \
    -CAserial "${CA_SERIAL}" \
    -out "${crt}" \
    -days "${CERT_DAYS}" \
    -sha256 \
    -extfile "${cnf}" \
    -extensions "${ext_section}"

  echo "  Fertig: ${crt}"
}

generate_client_cert() {
  local dir="$1"
  local name="${2:-client}"  # default: client

  local cnf="${dir}/${name}.cnf"
  local key="${dir}/${name}.key"
  local csr="${dir}/${name}.csr"
  local crt="${dir}/${name}.crt"

  echo ""
  echo "-- Client-Zertifikat in ${dir} (${name}) --"

  # Wenn Zertifikat schon existiert: nichts tun (idempotent)
  if [[ -f "${crt}" ]]; then
    echo "  Zertifikat ${crt} existiert bereits – überspringe."
    return 0
  fi

  # Alte Fragmente ggf. entfernen
  if [[ -f "${key}" || -f "${csr}" ]]; then
    echo "  Entferne alte Key/CSR-Fragmente."
    rm -f "${key}" "${csr}"
  fi

  echo "  Generiere Key: ${key}"
  openssl genrsa -out "${key}" "${KEY_BITS}"

  if [[ -f "${cnf}" ]]; then
    echo "  Generiere CSR mit Config: ${csr}"
    openssl req -new -key "${key}" -out "${csr}" -config "${cnf}"
  else
    echo "  WARNUNG: ${cnf} nicht gefunden, benutze einfaches Subject."
    openssl req -new -key "${key}" -out "${csr}" -subj "/CN=${name}"
  fi

  echo "  Signiere Zertifikat: ${crt}"
  local sign_args=(
    -req -in "${csr}" -CA "${CA_CRT}" -CAkey "${CA_KEY}"
    -CAserial "${CA_SERIAL}" -out "${crt}" -days "${CERT_DAYS}" -sha256
  )
  if [[ -f "${cnf}" ]]; then
    sign_args+=( -extfile "${cnf}" -extensions v3_req )
  fi
  openssl x509 "${sign_args[@]}"

  echo "  Fertig: ${crt}"
}

# --- Konkrete Verzeichnisse aufrufen ---------------------------------------

# CPC: client for existing data path, server for typed pipeline
generate_client_cert "${ROOT_DIR}/cpc-certs" "client"
generate_server_cert "${ROOT_DIR}/cpc-certs" "server"

# interface-certs: Client + Server
generate_client_cert "${ROOT_DIR}/interface-certs" "client"
generate_server_cert "${ROOT_DIR}/interface-certs" "server"

# Intermediate VoR: server for interface hop, client for processing hop
generate_server_cert "${ROOT_DIR}/intermediate-vor-certs" "server"
generate_client_cert "${ROOT_DIR}/intermediate-vor-certs" "client"

# Intermediate VoR CPC: server for mapping hop, client for CPC hop
generate_server_cert "${ROOT_DIR}/intermediate-vor-cpc-certs" "server"
generate_client_cert "${ROOT_DIR}/intermediate-vor-cpc-certs" "client"

# psmo-certs: nur Server
generate_server_cert "${ROOT_DIR}/psmo-certs" "server"

# OPA policy decision point: HTTPS server identity. The interface partition
# reuses its component-bound client identity; system.authz restricts API access
# to that exact certificate subject.
generate_server_cert "${ROOT_DIR}/opa-certs" "server"

echo ""
echo "== Fertig =="
