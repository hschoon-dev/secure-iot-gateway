#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="${ROOT_DIR}/.mariadb-e2e-runtime"
DATA_DIR="${RUNTIME_DIR}/interface-partition"
export E2E_CREDENTIALS_DIR="${DATA_DIR}"
export E2E_MODBUS_CONFIG="${RUNTIME_DIR}/modbustcp-endpoints_demonstrator.xml"
export MARIADB_ROOT_PASSWORD="${MARIADB_ROOT_PASSWORD:-MariaDB-E2E-Root-2026}"
export MARIADB_VOR1_PASSWORD="${MARIADB_VOR1_PASSWORD:-MariaDB-E2E-Writer-2026}"
export MARIADB_VOR2_PASSWORD="${MARIADB_VOR2_PASSWORD:-MariaDB-E2E-Consumer-2026}"
export AUTHZ_MODE="casbin_and_opa"
COMPOSE=(
  docker compose
  -f "${ROOT_DIR}/docker-compose.yaml"
  -f "${ROOT_DIR}/tests/e2e/docker-compose.e2e.yaml"
  -f "${ROOT_DIR}/tests/mariadb/docker-compose.mariadb-e2e.yaml"
)

: "${ADMIN_PASSWORD:?Set ADMIN_PASSWORD to a test-only password of at least 21 characters}"

cleanup() {
  "${COMPOSE[@]}" --profile e2e down --volumes --remove-orphans >/dev/null 2>&1 || true
}

on_exit() {
  local status="$?"
  if [[ "${status}" -ne 0 ]]; then
    "${COMPOSE[@]}" --profile e2e logs --no-color --tail=160 >&2 || true
  fi
  if [[ "${MARIADB_E2E_KEEP_STACK:-false}" != "true" ]]; then
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

cleanup
"${COMPOSE[@]}" --profile e2e up --build -d \
  mariadb brownfield-opcua-server ecotec-modbus-server opa psmo-partition \
  interface-partition cpc-partition intermediate-vor-partition \
  intermediate-vor-partition-cpc

wait_for_service() {
  local service="$1"
  local attempt
  for attempt in $(seq 1 60); do
    if "${COMPOSE[@]}" --profile e2e exec -T "${service}" true >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "ERROR: ${service} did not become ready within 60 seconds" >&2
  return 1
}

for service in mariadb interface-partition intermediate-vor-partition \
  intermediate-vor-partition-cpc cpc-partition ecotec-modbus-server; do
  wait_for_service "${service}"
done

"${COMPOSE[@]}" --profile e2e exec -T cpc-partition \
  python3 -c 'import socket; probe=socket.socket(); probe.settimeout(1); result=probe.connect_ex(("127.0.0.1",5000)); probe.close(); assert result != 0, "legacy CPC Flask bridge unexpectedly listens on 5000"'
echo "PASS legacy-http-disabled: MariaDB pipeline uses CPC gRPC/mTLS; port 5000 is closed"

mysql_as() {
  local user="$1" password="$2" sql="$3"
  "${COMPOSE[@]}" --profile e2e exec -T mariadb \
    mariadb --protocol=TCP -h 127.0.0.1 \
      -u "${user}" "-p${password}" secure_iot_gateway -Nse "${sql}"
}

expect_sql_denied() {
  local user="$1" password="$2" sql="$3" label="$4"
  if mysql_as "${user}" "${password}" "${sql}" >/dev/null 2>&1; then
    echo "ERROR: ${label} unexpectedly succeeded" >&2
    return 1
  fi
  echo "PASS least-privilege: ${label} denied"
}

# Guard the effective three-file Compose merge. A missing override silently
# starts pipeline_main.py from the generic E2E profile and bypasses the
# persisted consumer even though every image builds successfully.
resolved_consumer_command="$("${COMPOSE[@]}" --profile e2e config --format json | \
  python3 -c 'import json,sys; command=json.load(sys.stdin)["services"]["intermediate-vor-partition-cpc"]["command"]; print(" ".join(command))')"
if [[ "${resolved_consumer_command}" != "python3 -u ./mariadb_pipeline_main.py" ]]; then
  echo "ERROR: resolved MariaDB consumer command is ${resolved_consumer_command}" >&2
  exit 1
fi
echo "PASS compose-profile: MariaDB overlay selects the gRPC/mTLS consumer"

# Runtime authorization is verified by actual permitted and prohibited SQL,
# not by parsing SHOW GRANTS text.
mysql_as vor-1 "${MARIADB_VOR1_PASSWORD}" \
  "INSERT INTO mapped_requests (request_id,generation_timestamp,priority) VALUES ('least-privilege-probe',NOW(6),99); UPDATE mapped_requests SET priority=98 WHERE request_id='least-privilege-probe';" \
  >/dev/null
echo "PASS least-privilege: vor-1 insert/update allowed"
expect_sql_denied vor-1 "${MARIADB_VOR1_PASSWORD}" \
  "DELETE FROM mapped_requests WHERE request_id='least-privilege-probe';" \
  "vor-1 delete"
expect_sql_denied vor-2 "${MARIADB_VOR2_PASSWORD}" \
  "INSERT INTO mapped_requests (request_id,generation_timestamp,priority) VALUES ('forbidden',NOW(6),99);" \
  "vor-2 insert"
mysql_as vor-2 "${MARIADB_VOR2_PASSWORD}" "CALL get_next_request();" >/dev/null
echo "PASS least-privilege: vor-2 stored-procedure consume allowed"

read_modbus() {
  "${COMPOSE[@]}" --profile e2e exec -T cpc-partition python3 -c \
    'from pyModbusTCP.client import ModbusClient; c=ModbusClient(host="ecotec-modbus-server",port=503,unit_id=1,auto_open=True,timeout=2); v=c.read_holding_registers(541,1); print(v[0] if v else "unavailable")'
}

initial="$(read_modbus)"
if [[ "${initial}" != "42" ]]; then
  echo "ERROR: expected deterministic initial Modbus value 42, got ${initial}" >&2
  exit 1
fi
echo "PASS mariadb-e2e: deterministic initial Modbus value is 42"

"${COMPOSE[@]}" --profile e2e run --build --rm --no-deps e2e-runner

final=""
for _attempt in $(seq 1 40); do
  final="$(read_modbus)"
  [[ "${final}" == "9" ]] && break
  sleep 1
done
if [[ "${final}" != "9" ]]; then
  echo "ERROR: MariaDB pipeline did not write/read back Modbus value 9; got ${final}" >&2
  exit 1
fi

pending="$(mysql_as vor-1 "${MARIADB_VOR1_PASSWORD}" 'SELECT COUNT(*) FROM mapped_requests;')"
if [[ "${pending}" != "0" ]]; then
  echo "ERROR: expected empty queue after processing, got ${pending}" >&2
  exit 1
fi
echo "PASS mariadb-e2e: OPC-UA -> gRPC -> MariaDB -> consumer -> gRPC/mTLS -> CPC -> Modbus readback = 9"
echo "PASS mariadb-e2e: request queue drained atomically"
