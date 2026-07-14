#!/usr/bin/env bash
# Create a local Compose environment file with unique development credentials.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
FORCE=false
GENERATE_RUNTIME=false

usage() {
  cat <<'EOF'
Usage: ./setup-local-secrets.sh [--env-file PATH] [--force] [--generate-runtime]

Creates a mode-0600 Compose env file with new local passwords. Existing files
are never overwritten unless --force is supplied. --generate-runtime performs
a certificate rotation and activates fresh component-scoped runtime secrets.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      [[ $# -ge 2 ]] || { echo "ERROR: --env-file needs a path." >&2; exit 2; }
      ENV_FILE="$2"
      shift 2
      ;;
    --force) FORCE=true; shift ;;
    --generate-runtime) GENERATE_RUNTIME=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: Unsupported option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

command -v openssl >/dev/null 2>&1 || {
  echo "ERROR: openssl is required to generate local credentials." >&2
  exit 1
}

if [[ -e "${ENV_FILE}" && "${FORCE}" != "true" ]]; then
  echo "ERROR: Refusing to overwrite ${ENV_FILE}. Use --force after backing it up." >&2
  exit 1
fi

mkdir -p "$(dirname "${ENV_FILE}")"
umask 077

# Hex is portable in Compose env files. The fixed prefix makes the password
# policy's uppercase/lowercase/digit requirements deterministic.
password() { printf 'A1a%s' "$(openssl rand -hex 32)"; }
temporary="$(mktemp "${ENV_FILE}.tmp.XXXXXX")"
trap 'rm -f "${temporary}"' EXIT

cat >"${temporary}" <<EOF
# Generated locally by setup-local-secrets.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ).
# This file is ignored by Git. Do not reuse these values outside this deployment.
SIOT_DEPLOYMENT_MODE=production
ADMIN_PASSWORD=$(password)
MARIADB_ROOT_PASSWORD=$(password)
MARIADB_VOR1_PASSWORD=$(password)
MARIADB_VOR2_PASSWORD=$(password)
EOF
chmod 600 "${temporary}"
mv "${temporary}" "${ENV_FILE}"
trap - EXIT

echo "Created ${ENV_FILE} with mode 0600. Docker Compose loads it automatically."

if [[ "${GENERATE_RUNTIME}" == "true" ]]; then
  echo "Generating and activating fresh runtime certificates."
  if [[ ! -f "${ROOT_DIR}/node-red/.config.runtime.json" ]]; then
    # Node-RED is optional in the Compose file. With no runtime config there
    # is no encrypted store to migrate, so skipping its key is the only
    # complete initialisation path for a fresh checkout.
    SKIP_NODE_RED_ROTATION=true bash "${ROOT_DIR}/rotate-secrets.sh"
  else
    bash "${ROOT_DIR}/rotate-secrets.sh"
  fi
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
  SIOT_DEPLOYMENT_MODE=production bash "${ROOT_DIR}/validate-deployment-secrets.sh"
fi
