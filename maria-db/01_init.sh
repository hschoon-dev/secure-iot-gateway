#!/usr/bin/env bash
# =============================================================================
# /docker-entrypoint-initdb.d/01_init.sh
#
# The MariaDB Docker entrypoint executes .sh files from initdb.d as bash
# scripts before executing .sql files. This lets us substitute the
# MARIADB_VOR1_PASSWORD and MARIADB_VOR2_PASSWORD environment variables
# into the CREATE USER statements at container-first-start time, so the
# passwords never have to be hardcoded in a file.
#
# Required environment variables (set in docker-compose.yml):
#   MARIADB_VOR1_PASSWORD  — password for vor-1 (intermediate-vor-partition)
#   MARIADB_VOR2_PASSWORD  — password for vor-2 (intermediate-vor-partition-cpc)
# =============================================================================

set -euo pipefail

: "${MARIADB_VOR1_PASSWORD:?MARIADB_VOR1_PASSWORD must be set}"
: "${MARIADB_VOR2_PASSWORD:?MARIADB_VOR2_PASSWORD must be set}"

mysql --user=root --password="${MARIADB_ROOT_PASSWORD}" << SQL

-- =============================================================
-- Secure IoT Gateway — MariaDB initialisation
-- Runs once when the container is first created.
-- Database 'secure_iot_gateway' is created by MARIADB_DATABASE.
-- =============================================================

USE secure_iot_gateway;

-- Force utf8mb4 as the database default so stored procedures and ad-hoc
-- queries inherit the correct charset without needing explicit declarations.
-- Mirrors the RPi fix applied by fix_mariadb_collation.sh.
ALTER DATABASE secure_iot_gateway
    CHARACTER SET = utf8mb4
    COLLATE       = utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- Users
--   vor-1  →  intermediate-vor-partition       (write + read)
--   vor-2  →  intermediate-vor-partition-cpc   (read + delete)
-- Passwords are injected from environment variables at runtime;
-- they are never stored in this file.
-- -------------------------------------------------------------

CREATE USER IF NOT EXISTS 'vor-1'@'%' IDENTIFIED BY '${MARIADB_VOR1_PASSWORD}';
CREATE USER IF NOT EXISTS 'vor-2'@'%' IDENTIFIED BY '${MARIADB_VOR2_PASSWORD}';

-- Full privileges on the database for both users.
-- vor-1 (intermediate-vor-partition): writes and reads requests.
-- vor-2 (intermediate-vor-partition-cpc): reads and deletes requests via stored procedure.
-- EXECUTE on stored procedures is NOT covered by table-level grants and must
-- be stated explicitly even with ALL PRIVILEGES on the schema.
GRANT ALL PRIVILEGES ON secure_iot_gateway.* TO 'vor-1'@'%';
GRANT ALL PRIVILEGES ON secure_iot_gateway.* TO 'vor-2'@'%';

FLUSH PRIVILEGES;

-- -------------------------------------------------------------
-- Table: mapped_requests
-- -------------------------------------------------------------

CREATE TABLE IF NOT EXISTS mapped_requests (
    request_id             VARCHAR(36)  NOT NULL,
    generation_timestamp   DATETIME(6)  NOT NULL,
    description            LONGTEXT,
    impact                 VARCHAR(255),
    priority               INT          NOT NULL DEFAULT 99,
    tags                   LONGTEXT,
    affected_endpoint_list LONGTEXT,
    created_at             DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at             DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                                        ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (request_id),
    INDEX idx_priority_ts (priority ASC, generation_timestamp ASC)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

SQL

# DELIMITER $$ is a mysql CLI directive ignored when piping SQL.
# Write the procedure to a temp file and source it so DELIMITER works.
PROC_SQL=$(mktemp)
trap 'rm -f "${PROC_SQL}"' EXIT

cat > "${PROC_SQL}" << 'PROC'
USE secure_iot_gateway;

-- -------------------------------------------------------------
-- Stored procedure: get_next_request
--
-- Atomically retrieves the highest-priority pending request and
-- deletes it in one transaction, preventing duplicate processing
-- under concurrent access from both VOR partitions.
-- -------------------------------------------------------------

DROP PROCEDURE IF EXISTS get_next_request;

DELIMITER $$

CREATE PROCEDURE get_next_request()
BEGIN
    -- CHARACTER SET and COLLATE must match the table column exactly.
    -- Without this, MariaDB uses the server default and raises
    -- error 1267 "illegal mix of collations" on the WHERE comparison.
    DECLARE v_request_id VARCHAR(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

    SELECT request_id
    INTO   v_request_id
    FROM   mapped_requests
    ORDER  BY priority ASC, generation_timestamp ASC
    LIMIT  1
    FOR UPDATE SKIP LOCKED;

    IF v_request_id IS NOT NULL THEN
        SELECT request_id,
               generation_timestamp,
               description,
               impact,
               priority,
               tags,
               affected_endpoint_list
        FROM   mapped_requests
        WHERE  request_id = v_request_id;

        DELETE FROM mapped_requests WHERE request_id = v_request_id;
    ELSE
        -- Return an empty result set so cursor.stored_results() works
        -- in mysql-connector-python even when no rows are pending.
        SELECT NULL AS request_id,
               NULL AS generation_timestamp,
               NULL AS description,
               NULL AS impact,
               NULL AS priority,
               NULL AS tags,
               NULL AS affected_endpoint_list
        WHERE  1 = 0;
    END IF;
END$$

DELIMITER ;
PROC

mysql --user=root --password="${MARIADB_ROOT_PASSWORD}" < "${PROC_SQL}"

# Grant EXECUTE after the procedure exists — granting before creation raises 1305.
mysql --user=root --password="${MARIADB_ROOT_PASSWORD}" secure_iot_gateway -e "\
GRANT EXECUTE ON PROCEDURE secure_iot_gateway.get_next_request TO 'vor-1'@'%'; \
GRANT EXECUTE ON PROCEDURE secure_iot_gateway.get_next_request TO 'vor-2'@'%'; \
FLUSH PRIVILEGES;"

echo "[01_init.sh] Initialisation complete."