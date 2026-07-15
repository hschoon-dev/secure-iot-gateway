"""
------------------------------------------------------------
 Modul:    db_manager.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    Database abstraction layer for the SQLite database used by
    intermediate-vor-partition-cpc to hold mapped requests
    received via the mapped_request_server gRPC service, providing
    thread-safe access to the mapped_requests table.

    MIGRATION: Replaces MariaDB (a standalone database server/
    container), and later a SQLite file shared with
    intermediate-vor-partition over a Docker volume, with a
    SQLite database that is now local and private to this
    partition — a plain file living in the app directory
    alongside the code, not a Docker-managed volume, so the same
    layout works whether run in Docker (for testing) or directly
    on a Linux VM (the intended target). intermediate-vor-partition
    no longer touches any database; it forwards mapped requests
    over gRPC instead (see mapped_request_server/mapped_request_server.py),
    and this partition is the sole owner of storage.

 Features:
    - WAL (Write-Ahead Logging) journal mode so the gRPC server
      thread (writer) and the pull/process loop thread (reader/
      deleter) don't block each other
    - busy_timeout so one thread waits for a lock instead of
      failing immediately
    - Thread-safe operations (each call opens and closes its
      own short-lived connection)
    - Automatic schema creation (idempotent)
    - Transaction support with an atomic "pull highest priority
      request and delete it" operation, equivalent to the
      MariaDB stored procedure `get_next_request` this replaced

 Autor(en):
    - Heiko Schoon (migration from MariaDB to a local SQLite database)

 Maintainer:
    - tbd
------------------------------------------------------------
"""

import logging
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

_logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Manages access to this partition's local-only SQLite database and
    provides safe access methods for the mapped_requests table.

    The database file is private to intermediate-vor-partition-cpc: no
    other process ever opens it. It is written to by the
    mapped_request_server gRPC service (on receipt from
    intermediate-vor-partition) and read/deleted from by the
    pull_request_and_process loop in main.py, both running as threads
    within this same process.
    """

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS mapped_requests (
            request_id             TEXT    NOT NULL PRIMARY KEY,
            generation_timestamp   TEXT    NOT NULL,
            description             TEXT,
            impact                  TEXT,
            priority                INTEGER NOT NULL DEFAULT 99,
            tags                    TEXT,
            affected_endpoint_list  TEXT,
            created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
            updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
        );

        CREATE INDEX IF NOT EXISTS idx_priority_ts
            ON mapped_requests (priority ASC, generation_timestamp ASC);
    """

    def __init__(
        self,
        database: str,
        busy_timeout_ms: int = 10000,
        **_ignored: Any,
    ):
        # database is the only value that truly matters for SQLite; it is
        # required and sourced from CONFIG.sqlite (env-overridable via
        # DB_PATH), not hardcoded. This file is local-only to this
        # container (no shared volume) — only this process ever opens it.
        # **_ignored absorbs legacy MariaDB keyword arguments (host, port,
        # user, password, pool_name, pool_size) so callers that still pass
        # them (e.g. old configs) don't raise a TypeError during migration.
        """
        Initialize the database manager.

        Args:
            database: Filesystem path to the SQLite database file. A plain
                file local to this partition (e.g. a "data/" subfolder
                alongside the code) — no other process opens it.
            busy_timeout_ms: Milliseconds SQLite waits for a lock held by
                another thread in this process before raising OperationalError.
        """
        self.database = str(database)
        self._busy_timeout_ms = busy_timeout_ms

        # Ensure the parent directory of the database file exists (e.g. a
        # fresh checkout/VM where the "data/" subfolder doesn't exist yet).
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)

        try:
            self._init_schema()
            _logger.info(f"SQLite database ready: {self.database}")
        except sqlite3.Error as e:
            _logger.error(f"Error initializing SQLite schema: {e}")
            raise

    def _connect(self) -> sqlite3.Connection:
        """
        Open a new connection configured for safe multi-process access.

        A fresh connection is opened per call rather than pooled: SQLite
        connections are cheap to open/close, and this avoids having to
        reason about sharing a single sqlite3.Connection object (which is
        not safe to use across threads) across the whole process.
        """
        conn = sqlite3.connect(
            self.database,
            timeout=self._busy_timeout_ms / 1000,
            isolation_level=None,  # autocommit; transactions are managed explicitly below
        )
        conn.row_factory = sqlite3.Row
        # WAL allows the writer partition and the reader/deleter partition
        # to access the file concurrently without blocking each other on
        # every operation.
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms};")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_schema(self) -> None:
        """Create the mapped_requests table/index if they don't exist yet."""
        conn = self._connect()
        try:
            conn.executescript(self._SCHEMA)
        finally:
            conn.close()

    @contextmanager
    def get_connection(self):
        """
        Context manager to safely get and close a SQLite connection.

        Usage:
            with db_manager.get_connection() as conn:
                conn.execute(...)
        """
        conn = None
        try:
            conn = self._connect()
            yield conn
        except sqlite3.Error as e:
            _logger.error(f"SQLite connection error: {e}")
            raise
        finally:
            if conn is not None:
                conn.close()

    def insert_or_update_request(
        self,
        request_id: str,
        generation_timestamp: datetime,
        description: Any,
        impact: str,
        priority: int,
        tags: Any,
        affected_endpoint_list: List,
    ) -> bool:
        """
        Insert or update a mapped request (UPSERT behavior).

        Args:
            request_id: Unique request identifier
            generation_timestamp: When the request was created
            description: Request description (will be JSON-serialized)
            impact: Impact classification
            priority: Priority level (lower = higher priority)
            tags: Tags for filtering (will be JSON-serialized)
            affected_endpoint_list: List of affected endpoints

        Returns:
            True if successful, False otherwise
        """
        conn = None
        try:
            # Convert to JSON-serializable formats
            description_json = self._to_json_string(description)
            tags_json = self._to_json_string(tags)
            affected_list_json = self._to_json_string(affected_endpoint_list)

            # SQLite has no native datetime type; store as a naive
            # 'YYYY-MM-DD HH:MM:SS.ffffff' string (matching the previous
            # MariaDB DATETIME(6) representation) so ordering by
            # generation_timestamp as text still sorts chronologically.
            ts_str = self._normalize_timestamp(generation_timestamp)

            conn = self._connect()
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                """
                INSERT INTO mapped_requests
                    (request_id, generation_timestamp, description, impact,
                     priority, tags, affected_endpoint_list, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%d %H:%M:%f', 'now'))
                ON CONFLICT(request_id) DO UPDATE SET
                    generation_timestamp   = excluded.generation_timestamp,
                    description            = excluded.description,
                    impact                 = excluded.impact,
                    priority               = excluded.priority,
                    tags                   = excluded.tags,
                    affected_endpoint_list = excluded.affected_endpoint_list,
                    updated_at             = strftime('%Y-%m-%d %H:%M:%f', 'now')
                """,
                (
                    request_id,
                    ts_str,
                    description_json,
                    impact,
                    priority,
                    tags_json,
                    affected_list_json,
                ),
            )
            conn.commit()
            _logger.debug(f"Request upserted: {request_id}")
            return True

        except sqlite3.Error as e:
            _logger.error(f"Error upserting request {request_id}: {e}")
            try:
                if conn is not None:
                    conn.rollback()
            except Exception:
                pass
            return False
        finally:
            if conn is not None:
                conn.close()

    def pull_next_request(self) -> Optional[Dict[str, Any]]:
        """
        Atomically retrieve and delete the next highest-priority request.

        Wraps the SELECT + DELETE in a single BEGIN IMMEDIATE transaction so
        no two callers (the CPC partition, potentially from multiple
        threads/processes) can pull the same request, mirroring the
        atomicity previously provided by the MariaDB `get_next_request`
        stored procedure with SKIP LOCKED.

        Returns:
            Request dictionary or None if no requests exist
        """
        conn = None
        try:
            conn = self._connect()
            conn.execute("BEGIN IMMEDIATE;")

            row = conn.execute(
                """
                SELECT request_id, generation_timestamp, description, impact,
                       priority, tags, affected_endpoint_list
                FROM   mapped_requests
                ORDER  BY priority ASC, generation_timestamp ASC
                LIMIT  1
                """
            ).fetchone()

            if row is None:
                conn.commit()
                _logger.debug("No pending requests found")
                return None

            request = dict(row)

            conn.execute(
                "DELETE FROM mapped_requests WHERE request_id = ?",
                (request["request_id"],),
            )
            conn.commit()

            # Parse JSON fields back to Python objects
            request["description"] = self._parse_json_field(request.get("description"))
            request["tags"] = self._parse_json_field(request.get("tags"))
            request["affected_endpoint_list"] = self._parse_json_field(
                request.get("affected_endpoint_list"), default_type=list
            )

            # Ensure timestamps are datetime objects
            if isinstance(request["generation_timestamp"], str):
                request["generation_timestamp"] = datetime.fromisoformat(
                    request["generation_timestamp"]
                )

            _logger.debug(f"Pulled request: {request['request_id']}")
            return request

        except sqlite3.Error as e:
            _logger.error(f"Error pulling next request: {e}")
            try:
                if conn is not None:
                    conn.rollback()
            except Exception:
                pass
            return None
        finally:
            if conn is not None:
                conn.close()

    def get_request_count(self) -> int:
        """
        Get the current number of pending requests in the database.
        """
        try:
            with self.get_connection() as conn:
                row = conn.execute("SELECT COUNT(*) AS count FROM mapped_requests").fetchone()
                return row["count"] if row else 0
        except sqlite3.Error as e:
            _logger.error(f"Error getting request count: {e}")
            return -1

    def delete_request(self, request_id: str) -> bool:
        """
        Manually delete a request by ID (fallback method).
        """
        conn = None
        try:
            conn = self._connect()
            conn.execute("BEGIN IMMEDIATE;")
            cursor = conn.execute(
                "DELETE FROM mapped_requests WHERE request_id = ?", (request_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            _logger.error(f"Error deleting request {request_id}: {e}")
            try:
                if conn is not None:
                    conn.rollback()
            except Exception:
                pass
            return False
        finally:
            if conn is not None:
                conn.close()

    def get_all_requests(self) -> List[Dict[str, Any]]:
        """
        Retrieve all pending requests (for debugging/monitoring).
        Sorted by priority and timestamp.
        """
        try:
            with self.get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT request_id, generation_timestamp, description,
                           impact, priority, tags, affected_endpoint_list
                    FROM mapped_requests
                    ORDER BY priority ASC, generation_timestamp ASC
                    """
                ).fetchall()

                # Parse JSON fields for all rows
                result = []
                for row in rows:
                    request = dict(row)
                    request["description"] = self._parse_json_field(request.get("description"))
                    request["tags"] = self._parse_json_field(request.get("tags"))
                    request["affected_endpoint_list"] = self._parse_json_field(
                        request.get("affected_endpoint_list"), default_type=list
                    )
                    result.append(request)

                return result
        except sqlite3.Error as e:
            _logger.error(f"Error retrieving all requests: {e}")
            return []

    @staticmethod
    def _normalize_timestamp(generation_timestamp: Any) -> str:
        """
        Normalize a datetime (or ISO string) into a naive
        'YYYY-MM-DD HH:MM:SS.ffffff' string for storage/sorting.
        """
        if isinstance(generation_timestamp, datetime):
            dt = generation_timestamp.replace(tzinfo=None)
        elif isinstance(generation_timestamp, str):
            dt = datetime.fromisoformat(generation_timestamp).replace(tzinfo=None)
        else:
            return str(generation_timestamp)
        return dt.isoformat(sep=" ", timespec="microseconds")

    @staticmethod
    def _to_json_string(value: Any) -> str:
        """
        Convert a value to JSON string for storage.
        Returns 'null' for None values.
        """
        try:
            return json.dumps(value, default=str)
        except (TypeError, ValueError) as e:
            _logger.warning(f"Could not JSON-serialize {type(value)}: {e}, using str()")
            return json.dumps(str(value))

    @staticmethod
    def _parse_json_field(
        value: Any, default_type: type = dict
    ) -> Any:
        """
        Parse a JSON field from the database back to Python object.

        Args:
            value: The JSON string or already-parsed value
            default_type: Type to return if value is None (dict or list)

        Returns:
            Parsed Python object or default_type() if None
        """
        if value is None:
            return default_type()

        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if parsed is not None else default_type()
            except (json.JSONDecodeError, ValueError):
                _logger.warning(f"Could not parse JSON: {value}")
                return default_type()

        # Already parsed
        return value if value is not None else default_type()
