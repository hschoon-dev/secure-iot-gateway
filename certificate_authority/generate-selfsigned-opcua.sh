#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPCUA_DIR="${ROOT_DIR}/opcua"

generate_selfsigned() {
    local dir="$1"
    local name="$2"
    local cnf="${dir}/${name}.cnf"
    local key="${dir}/${name}_key.pem"
    local cert="${dir}/${name}_cert.pem"
    local der="${dir}/${name}_cert.der"

    mkdir -p "$dir"

    echo ""
    echo "-- Generating self-signed OPC UA cert for ${name} --"

    # Key
    echo "  Generating key: $key"
    openssl genrsa -out "$key" 2048

    # Self-signed cert
    echo "  Generating self-signed certificate: $cert"
    openssl req -x509 -days 365 \
        -new -key "$key" \
        -out "$cert" \
        -config "$cnf"

    # DER export
    echo "  Generating DER: $der"
    openssl x509 -in "$cert" -out "$der" -outform DER

    echo "  Done: $name"
}

echo "== Generating OPC UA Self-Signed Certificates =="

generate_selfsigned "${OPCUA_DIR}/brownfield_server" "brownfield_server"
generate_selfsigned "${OPCUA_DIR}/interface_server" "interface_server"
generate_selfsigned "${OPCUA_DIR}/cpc_client" "cpc_client"

echo ""
echo "== Finished =="