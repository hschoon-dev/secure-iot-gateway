"""
------------------------------------------------------------
 Modul:    db_manager.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    Database abstraction layer for MariaDB connection pooling
    and thread-safe access to mapped_requests table.
    
    Replaces TinyDB with proper database connection management.

 Features:
    - Connection pooling (reduces connection overhead)
    - Thread-safe operations
    - Automatic reconnection on connection loss
    - Transaction support
    - Proper error handling and logging

 Autor(en):
    - Heiko Schoon (migration from TinyDB to MariaDB)

 Maintainer:
    - tbd
------------------------------------------------------------
"""

import logging
import json
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

try:
    import mysql.connector
    from mysql.connector import pooling, Error
except ImportError:
    raise ImportError(
        "mysql-connector-python is required. "
        "Install with: pip install mysql-connector-python"
    )

_logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Manages MariaDB connection pooling and provides safe access methods.
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        pool_name: str = "iot_gateway_pool",
        pool_size: int = 5,
    ):
        # All connection parameters are required; no defaults are provided for
        # credentials or addresses to prevent accidental use of stale values.
        # Callers (main.py) must supply values sourced from environment variables
        # or a secrets manager, not from version-controlled config files.
        """
        Initialize the database manager with connection pool.
        
        Args:
            host: MariaDB server hostname
            port: MariaDB server port
            user: Database user
            password: Database password
            database: Database name
            pool_name: Connection pool identifier
            pool_size: Number of connections in the pool
        """
        self.config = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database,
            "autocommit": False,  # Explicit transaction control
            "use_unicode": True,
            "charset": "utf8mb4",
        }

        try:
            self.pool = pooling.MySQLConnectionPool(
                pool_name=pool_name,
                pool_size=pool_size,
                pool_reset_session=True,
                **self.config,
            )
            _logger.info(
                f"Database connection pool initialized: {host}:{port}/{database}"
            )
        except Error as e:
            _logger.error(f"Error creating connection pool: {e}")
            raise

    @contextmanager
    def get_connection(self):
        """
        Context manager to safely get and return a connection from the pool.
        Automatically handles connection cleanup.
        
        Usage:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(...)
        """
        conn = None
        try:
            conn = self.pool.get_connection()
            yield conn
        except Error as e:
            _logger.error(f"Connection pool error: {e}")
            raise
        finally:
            if conn and conn.is_connected():
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
        try:
            # Convert to JSON-serializable formats
            description_json = self._to_json_string(description)
            tags_json = self._to_json_string(tags)
            affected_list_json = self._to_json_string(affected_endpoint_list)

            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Use INSERT ... ON DUPLICATE KEY UPDATE for upsert
                query = """
                    INSERT INTO mapped_requests 
                    (request_id, generation_timestamp, description, impact, 
                     priority, tags, affected_endpoint_list)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        generation_timestamp = VALUES(generation_timestamp),
                        description = VALUES(description),
                        impact = VALUES(impact),
                        priority = VALUES(priority),
                        tags = VALUES(tags),
                        affected_endpoint_list = VALUES(affected_endpoint_list),
                        updated_at = CURRENT_TIMESTAMP
                """

                cursor.execute(
                    query,
                    (
                        request_id,
                        generation_timestamp,
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

        except Error as e:
            _logger.error(f"Error upserting request {request_id}: {e}")
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            return False

    def pull_next_request(self) -> Optional[Dict[str, Any]]:
        """
        Atomically retrieve and delete the next highest-priority request.
        
        Uses a stored procedure to ensure atomicity under concurrent access.
        
        Returns:
            Request dictionary or None if no requests exist
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)

                # Call the stored procedure (atomic operation)
                cursor.callproc("get_next_request")

                # Fetch the result set
                request = None
                for result in cursor.stored_results():
                    rows = result.fetchall()
                    if rows:
                        request = rows[0]
                        break

                conn.commit()

                if request:
                    # Parse JSON fields back to Python objects
                    request["description"] = self._parse_json_field(
                        request.get("description")
                    )
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
                else:
                    _logger.debug("No pending requests found")
                    return None

        except Error as e:
            _logger.error(f"Error pulling next request: {e}")
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            return None

    def get_request_count(self) -> int:
        """
        Get the current number of pending requests in the database.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as count FROM mapped_requests")
                result = cursor.fetchone()
                return result[0] if result else 0
        except Error as e:
            _logger.error(f"Error getting request count: {e}")
            return -1

    def delete_request(self, request_id: str) -> bool:
        """
        Manually delete a request by ID (fallback method).
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM mapped_requests WHERE request_id = %s", (request_id,)
                )
                conn.commit()
                return cursor.rowcount > 0
        except Error as e:
            _logger.error(f"Error deleting request {request_id}: {e}")
            return False

    def get_all_requests(self) -> List[Dict[str, Any]]:
        """
        Retrieve all pending requests (for debugging/monitoring).
        Sorted by priority and timestamp.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    """
                    SELECT request_id, generation_timestamp, description, 
                           impact, priority, tags, affected_endpoint_list
                    FROM mapped_requests
                    ORDER BY priority ASC, generation_timestamp ASC
                    """
                )
                rows = cursor.fetchall()

                # Parse JSON fields for all rows
                for row in rows:
                    row["description"] = self._parse_json_field(row.get("description"))
                    row["tags"] = self._parse_json_field(row.get("tags"))
                    row["affected_endpoint_list"] = self._parse_json_field(
                        row.get("affected_endpoint_list"), default_type=list
                    )

                return rows
        except Error as e:
            _logger.error(f"Error retrieving all requests: {e}")
            return []

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

        # Already parsed (MariaDB might return parsed JSON in some connectors)
        return value if value is not None else default_type()