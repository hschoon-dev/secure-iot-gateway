#!/usr/bin/env bash
# Assemble a complete runtime-secret tree without replacing the active tree.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE_DIR="${ROOT_DIR}/.secret-staging/$(date +%Y%m%d-%H%M%S)"

usage() {
  echo "Usage: ./stage-runtime-secrets.sh [--stage-dir PATH]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stage-dir)
      [[ $# -ge 2 ]] || { echo "ERROR: --stage-dir needs a path." >&2; exit 2; }
      STAGE_DIR="$2"
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: Unsupported option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ ! -e "${STAGE_DIR}" ]] || {
  echo "ERROR: Stage directory already exists: ${STAGE_DIR}" >&2
  exit 1
}

mkdir -p "${STAGE_DIR}"
cleanup() {
  local status="$?"
  if [[ "${status}" -ne 0 ]]; then
    rm -rf "${STAGE_DIR}"
  fi
  exit "${status}"
}
trap cleanup EXIT

SIOT_RUNTIME_SECRETS_DIR="${STAGE_DIR}/runtime-secrets" \
SIOT_RUNTIME_DATA_DIR="${STAGE_DIR}/runtime-data" \
  bash "${ROOT_DIR}/secret_migration.sh"

echo "Staged runtime material at: ${STAGE_DIR}"
echo "Activate it with: ./activate-runtime-secrets.sh --stage-dir ${STAGE_DIR}"
