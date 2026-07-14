#!/usr/bin/env bash
# Atomically activate a staged runtime-secret tree and retain the old tree.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE_DIR=""
RUNTIME_SECRETS_DIR="${ROOT_DIR}/.runtime-secrets"
RUNTIME_DATA_DIR="${ROOT_DIR}/.runtime-data"
BACKUP_DIR="${ROOT_DIR}/.secrets-backup/runtime-$(date +%Y%m%d-%H%M%S)"

usage() {
  cat <<'EOF'
Usage: ./activate-runtime-secrets.sh --stage-dir PATH [options]

Options:
  --runtime-secrets-dir PATH  Target secret directory (default: .runtime-secrets)
  --runtime-data-dir PATH     Target mutable-data directory (default: .runtime-data)
  --backup-dir PATH           Destination for the previous active tree
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stage-dir)
      [[ $# -ge 2 ]] || { echo "ERROR: --stage-dir needs a path." >&2; exit 2; }
      STAGE_DIR="$2"; shift 2 ;;
    --runtime-secrets-dir)
      [[ $# -ge 2 ]] || { echo "ERROR: --runtime-secrets-dir needs a path." >&2; exit 2; }
      RUNTIME_SECRETS_DIR="$2"; shift 2 ;;
    --runtime-data-dir)
      [[ $# -ge 2 ]] || { echo "ERROR: --runtime-data-dir needs a path." >&2; exit 2; }
      RUNTIME_DATA_DIR="$2"; shift 2 ;;
    --backup-dir)
      [[ $# -ge 2 ]] || { echo "ERROR: --backup-dir needs a path." >&2; exit 2; }
      BACKUP_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: Unsupported option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "${STAGE_DIR}" ]] || { echo "ERROR: --stage-dir is required." >&2; exit 2; }
[[ -d "${STAGE_DIR}/runtime-secrets" && -d "${STAGE_DIR}/runtime-data" ]] || {
  echo "ERROR: Stage directory is incomplete: ${STAGE_DIR}" >&2
  exit 1
}
[[ ! -e "${BACKUP_DIR}" ]] || { echo "ERROR: Backup directory already exists: ${BACKUP_DIR}" >&2; exit 1; }

mkdir -p "$(dirname "${RUNTIME_SECRETS_DIR}")" "$(dirname "${RUNTIME_DATA_DIR}")" "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

old_secrets=false
old_data=false
if [[ -e "${RUNTIME_SECRETS_DIR}" ]]; then
  mv "${RUNTIME_SECRETS_DIR}" "${BACKUP_DIR}/runtime-secrets"
  old_secrets=true
fi
if [[ -e "${RUNTIME_DATA_DIR}" ]]; then
  mv "${RUNTIME_DATA_DIR}" "${BACKUP_DIR}/runtime-data"
  old_data=true
fi

restore() {
  local status="$?"
  if [[ "${status}" -ne 0 ]]; then
    [[ -e "${RUNTIME_SECRETS_DIR}" ]] && rm -rf "${RUNTIME_SECRETS_DIR}"
    [[ -e "${RUNTIME_DATA_DIR}" ]] && rm -rf "${RUNTIME_DATA_DIR}"
    [[ "${old_secrets}" == "true" ]] && mv "${BACKUP_DIR}/runtime-secrets" "${RUNTIME_SECRETS_DIR}"
    [[ "${old_data}" == "true" ]] && mv "${BACKUP_DIR}/runtime-data" "${RUNTIME_DATA_DIR}"
  fi
  exit "${status}"
}
trap restore EXIT

# Rename is atomic when stage and runtime live on the same filesystem.
mv "${STAGE_DIR}/runtime-secrets" "${RUNTIME_SECRETS_DIR}"
mv "${STAGE_DIR}/runtime-data" "${RUNTIME_DATA_DIR}"
rmdir "${STAGE_DIR}"

echo "Activated staged runtime material. Previous active material: ${BACKUP_DIR}"
