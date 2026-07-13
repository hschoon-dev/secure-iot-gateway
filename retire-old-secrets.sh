#!/usr/bin/env bash
# Delete a rotation backup only after a separately validated rollout.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_ID=""
CONFIRM=""
DELETE=false

usage() {
  cat <<'EOF'
Usage: ./retire-old-secrets.sh --backup TIMESTAMP --confirm TIMESTAMP --delete

Lists the selected backup unless all three arguments agree. This script never
removes active runtime material. Retire only after new identities and trust
stores have been deployed and the old credentials are no longer in use.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backup) [[ $# -ge 2 ]] || exit 2; BACKUP_ID="$2"; shift 2 ;;
    --confirm) [[ $# -ge 2 ]] || exit 2; CONFIRM="$2"; shift 2 ;;
    --delete) DELETE=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: Unsupported option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "${BACKUP_ID}" =~ ^[0-9]{8}-[0-9]{6}$ ]] || {
  echo "ERROR: --backup must be a rotation timestamp (YYYYMMDD-HHMMSS)." >&2
  exit 2
}
BACKUP_DIR="${ROOT_DIR}/.secrets-backup/${BACKUP_ID}"
[[ -d "${BACKUP_DIR}" ]] || { echo "ERROR: Backup not found: ${BACKUP_DIR}" >&2; exit 1; }

if [[ "${DELETE}" != "true" || "${CONFIRM}" != "${BACKUP_ID}" ]]; then
  echo "Dry run: ${BACKUP_DIR} is retained."
  echo "To delete it after a verified rollout: --backup ${BACKUP_ID} --confirm ${BACKUP_ID} --delete"
  exit 0
fi

rm -rf "${BACKUP_DIR}"
echo "Retired backup: ${BACKUP_ID}"
