#!/usr/bin/env bash
#
# rotate-secrets.sh — Schlüssel-/Zertifikatsrotation für den Secure IoT Gateway.
#
# Zweck:
#   Erzeugt eine NEUE CA, stellt alle mTLS-/OPC-UA-Zertifikate neu aus und externalisiert
#   das Ergebnis (T-02). Ein Node-RED-Master-Key wird nur rotiert, wenn kein aktiver
#   Credential-Store re-encrypted werden müsste. Das vermeidet Datenverlust, schließt T-11
#   aber nicht ohne separate Rotation der nachgelagerten Credentials und Readback-Nachweis.
#
# WICHTIG: Nach der Rotation die Container neu bauen/deployen, damit ausschließlich die
#          neuen Truststores aktiv sind. Bei aktiven Node-RED-Credentials verweigert das
#          Skript die Key-Änderung, statt den Store unlesbar zu machen.
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GEN="${ROOT_DIR}/_generated_certificates"
GRPC="${GEN}/grpc"
CA_DIR="${GRPC}/ca"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP="${ROOT_DIR}/.secrets-backup/${TS}"

KEY_BITS="${KEY_BITS:-4096}"
CA_DAYS="${CA_DAYS:-825}"
SKIP_NODE_RED_ROTATION="${SKIP_NODE_RED_ROTATION:-false}"

log() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

# --- 0) Preflight before any key material is changed ----------------------------------
command -v openssl >/dev/null 2>&1 || { echo "ERROR: openssl is required." >&2; exit 1; }
[ -f "${GRPC}/generate-grpc-certs.sh" ] || {
  echo "ERROR: Missing gRPC certificate generator." >&2
  exit 1
}
NR_CFG="${ROOT_DIR}/node-red/.config.runtime.json"
NR_CREDENTIALS="${NODE_RED_CREDENTIAL_FILE:-${ROOT_DIR}/node-red/flows_cred.json}"
NR_FLOWS="${NODE_RED_FLOWS_FILE:-${ROOT_DIR}/node-red/flows.json}"
if [ "${SKIP_NODE_RED_ROTATION}" != "true" ]; then
  [ -f "${NR_CFG}" ] || {
    echo "ERROR: Node-RED runtime config is missing; refusing partial rotation." >&2
    echo "Set SKIP_NODE_RED_ROTATION=true only for deployments without Node-RED." >&2
    exit 1
  }
  command -v python3 >/dev/null 2>&1 || {
    echo "ERROR: python3 is required for Node-RED credential rotation." >&2
    exit 1
  }
  python3 - "${NR_CFG}" "${NR_CREDENTIALS}" "${NR_FLOWS}" <<'PY'
import json
import sys
from pathlib import Path

config_path, credentials_path, flows_path = map(Path, sys.argv[1:])
config = json.loads(config_path.read_text())
secret = config.get("_credentialSecret")
if not isinstance(secret, str) or not secret:
    raise SystemExit("ERROR: Node-RED runtime config has no usable _credentialSecret.")

active_store = False
if credentials_path.exists():
    data = json.loads(credentials_path.read_text())
    active_store = bool(data)

if flows_path.exists():
    data = json.loads(flows_path.read_text())

    def contains_credentials(value):
        if isinstance(value, dict):
            if value.get("credentials"):
                return True
            return any(contains_credentials(item) for item in value.values())
        if isinstance(value, list):
            return any(contains_credentials(item) for item in value)
        return False

    active_store = active_store or contains_credentials(data)

if active_store:
    raise SystemExit(
        "ERROR: Active Node-RED credentials detected. Refusing a key-only rotation; "
        "decrypt/re-encrypt and downstream credential rotation require a dedicated procedure."
    )
PY
fi

# --- 1) Backup des aktuellen Materials -------------------------------------------------
log "1) Backup nach ${BACKUP}"
mkdir -p "${BACKUP}"
chmod 700 "${BACKUP}"
cp -a "${GEN}" "${BACKUP}/_generated_certificates" 2>/dev/null || true
[ -f "${ROOT_DIR}/node-red/.config.runtime.json" ] && \
  cp -a "${ROOT_DIR}/node-red/.config.runtime.json" "${BACKUP}/" 2>/dev/null || true
find "${BACKUP}" -type d -exec chmod 700 {} +
find "${BACKUP}" -type f -exec chmod 600 {} +

OLD_FP="(keine)"
[ -f "${CA_DIR}/ca.crt" ] && OLD_FP="$(openssl x509 -in "${CA_DIR}/ca.crt" -noout -fingerprint -sha256 2>/dev/null | cut -d= -f2)"

# --- 2) Neue CA erzeugen ---------------------------------------------------------------
log "2) Neue CA erzeugen (${KEY_BITS} bit, ${CA_DAYS} Tage)"
mkdir -p "${CA_DIR}"
rm -f "${CA_DIR}/ca.key" "${CA_DIR}/ca.crt" "${CA_DIR}/ca.srl"
openssl genrsa -out "${CA_DIR}/ca.key" "${KEY_BITS}"
chmod 600 "${CA_DIR}/ca.key"
openssl req -x509 -new -nodes -key "${CA_DIR}/ca.key" -sha256 -days "${CA_DAYS}" \
  -out "${CA_DIR}/ca.crt" -subj "/O=HS Emden-Leer/CN=SIoT-Gateway-Root-CA ${TS}"
NEW_FP="$(openssl x509 -in "${CA_DIR}/ca.crt" -noout -fingerprint -sha256 | cut -d= -f2)"

# --- 3) gRPC-Zertifikate forciert neu ausstellen ---------------------------------------
log "3) gRPC-Zertifikate neu ausstellen"
# generate-grpc-certs.sh ueberspringt bestehende Certs -> alte entfernen erzwingt Neuausstellung.
find "${GRPC}" -maxdepth 2 -type f \( -name '*.crt' -o -name '*.key' -o -name '*.csr' \) \
  -not -path "${CA_DIR}/*" -delete
bash "${GRPC}/generate-grpc-certs.sh"

# --- 4) OPC-UA self-signed Zertifikate neu erzeugen ------------------------------------
log "4) OPC-UA-Zertifikate neu erzeugen"
OPCUA="${GEN}/opcua"
if [ -f "${OPCUA}/generate-selfsigned-opcua.sh" ]; then
  find "${OPCUA}" -maxdepth 2 -type f \( -name '*_key.pem' -o -name '*_cert.pem' -o -name '*_cert.der' \) -delete
  bash "${OPCUA}/generate-selfsigned-opcua.sh"
fi

# --- 5) Verteilung an die Partitions-Truststores/-Certs --------------------------------
log "5) Verteilung an Partitionen"
dist() { # <quelle-dir> <ziel-dir>
  [ -d "$1" ] || return 0; mkdir -p "$2"; cp -a "$1/." "$2/"; echo "  ${1#${ROOT_DIR}/} -> ${2#${ROOT_DIR}/}"
}
dist_identity() { # <quelle-dir> <identity-name> <ziel-dir>
  local source="$1" identity="$2" target="$3"
  mkdir -p "${target}"
  cp -a "${source}/${identity}.crt" "${target}/${identity}.crt"
  cp -a "${source}/${identity}.key" "${target}/${identity}.key"
  echo "  ${source#${ROOT_DIR}/}/${identity}.{crt,key} -> ${target#${ROOT_DIR}/}"
}
dist_opcua_identity() { # <quelle-dir> <identity-name> <ziel-dir>
  local source="$1" identity="$2" target="$3"
  mkdir -p "${target}"
  cp -a "${source}/${identity}_cert.der" "${target}/${identity}_cert.der"
  cp -a "${source}/${identity}_key.pem" "${target}/${identity}_key.pem"
  echo "  ${source#${ROOT_DIR}/}/${identity}_{cert.der,key.pem} -> ${target#${ROOT_DIR}/}"
}
dist_opcua_trust() { # <quelle-cert> <ziel-dir>
  local source="$1" target="$2"
  mkdir -p "${target}"
  cp -a "${source}" "${target}/$(basename "${source}")"
  echo "  ${source#${ROOT_DIR}/} -> ${target#${ROOT_DIR}/}"
}
# CA-Truststore in jede Partition
for capath in \
  "cpc-partition/certs/ca" "psmo-partition/certs/ca" \
  "interface-partition/certificates/grpc/ca" "intermediate-vor-partition/certificates/grpc/ca"; do
  mkdir -p "${ROOT_DIR}/${capath}"; cp -a "${CA_DIR}/ca.crt" "${ROOT_DIR}/${capath}/ca.crt"
  echo "  ca.crt -> ${capath}"
done
# Dienst-Zertifikate an ihre Partitionen
dist_identity "${GRPC}/cpc-certs" client \
  "${ROOT_DIR}/cpc-partition/certs/client"
dist_identity "${GRPC}/interface-certs" client \
  "${ROOT_DIR}/interface-partition/certificates/grpc/client"
dist_identity "${GRPC}/interface-certs" server \
  "${ROOT_DIR}/interface-partition/certificates/grpc/server"
dist_identity "${GRPC}/intermediate-vor-certs" server \
  "${ROOT_DIR}/intermediate-vor-partition/certificates/grpc/server"
dist_identity "${GRPC}/psmo-certs" server \
  "${ROOT_DIR}/psmo-partition/certs/server"

# OPC-UA identities and their reciprocal trust certificates. A clean checkout
# intentionally has no private keys, so these must be installed before the
# component-scoped runtime tree is assembled by secret_migration.sh.
dist_opcua_identity "${OPCUA}/interface_server" interface_server \
  "${ROOT_DIR}/interface-partition/certificates/python-server"
dist_opcua_identity "${OPCUA}/mo_client" mo_client \
  "${ROOT_DIR}/central-mo-client/certificates/python_client"
dist_opcua_trust "${OPCUA}/mo_client/mo_client_cert.der" \
  "${ROOT_DIR}/interface-partition/certificates/trusted/certs"
dist_opcua_trust "${OPCUA}/interface_server/interface_server_cert.der" \
  "${ROOT_DIR}/central-mo-client/certificates/trusted"

dist_opcua_identity "${OPCUA}/brownfield_server" brownfield_server \
  "${ROOT_DIR}/brownfield-opcua-server/opcua_secured_server/certificates"
dist_opcua_identity "${OPCUA}/cpc_client" cpc_client \
  "${ROOT_DIR}/cpc-partition/opcua_client/certificates"
dist_opcua_trust "${OPCUA}/cpc_client/cpc_client_cert.der" \
  "${ROOT_DIR}/brownfield-opcua-server/opcua_secured_server/certificates/trusted"
dist_opcua_trust "${OPCUA}/brownfield_server/brownfield_server_cert.der" \
  "${ROOT_DIR}/cpc-partition/opcua_client/certificates/trusted"

# The typed pipeline identities are installed directly from ${GRPC} into the
# component-scoped runtime tree by secret_migration.sh below.

# --- 6) Node-RED Master-Key ersetzen, nur wenn kein aktiver Store existiert --------------
if [ "${SKIP_NODE_RED_ROTATION}" != "true" ]; then
  log "6) Node-RED _credentialSecret ersetzen (leerer Store)"
  python3 - "${NR_CFG}" <<'PY'
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text())
old = data["_credentialSecret"]
new = secrets.token_hex(32)
data["_credentialSecret"] = new
temporary = path.with_suffix(path.suffix + ".tmp")
temporary.write_text(json.dumps(data, indent=4) + "\n")
os.chmod(temporary, 0o600)
os.replace(temporary, path)
print("  old key fingerprint (SHA-256): " + hashlib.sha256(old.encode()).hexdigest())
print("  new key fingerprint (SHA-256): " + hashlib.sha256(new.encode()).hexdigest())
print("  _credentialSecret replaced; no active credential store was present")
PY
  echo "  HINWEIS: Dieser Schritt allein schliesst T-11 nicht. Historisch exponierte"
  echo "           nachgelagerte Credentials muessen separat widerrufen und ersetzt werden."
fi

# --- 7) Externalisieren ----------------------------------------------------------------
if [ -x "${ROOT_DIR}/secret_migration.sh" ]; then
  log "7) Externalisierung (.runtime-secrets)"
  bash "${ROOT_DIR}/secret_migration.sh"
fi

# --- 8) Rotations-Protokoll ------------------------------------------------------------
log "8) Rotation abgeschlossen"
cat <<EOF
  Zeitpunkt:        ${TS}
  CA alt (SHA-256): ${OLD_FP}
  CA neu (SHA-256): ${NEW_FP}
  Backup:           ${BACKUP#${ROOT_DIR}/}

  Naechste Schritte:
   - Container neu bauen/deployen (nur neue Truststores aktiv).
   - Node-RED-Credentials separat rotieren, re-encrypten und per Readback pruefen (T-11).
   - Pro Dienst neue Verbindungen positiv und alte Zertifikate negativ testen.
   - Optional die weitere Verbreitung des Altmaterials durch Historienbereinigung
     reduzieren (ersetzt Rotation und Deployment-Nachweise nicht).
EOF
