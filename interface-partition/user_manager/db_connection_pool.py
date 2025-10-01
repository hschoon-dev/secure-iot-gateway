import sqlite3
import queue
import threading
import logging
import time
from typing import Any

_logger = logging.getLogger(__name__)

class SQLiteConnectionPool:
    """A thread-safe connection pool for SQLite connections"""
    
    def __init__(self, db_path: str, max_connections: int = 5) -> None:
        self.db_path: str = db_path
        self.max_connections: int = max_connections
        self.pool: queue.Queue = queue.Queue(maxsize=max_connections)
        self._lock: threading.RLock = threading.RLock()
        
        # Use a dictionary to track connection metadata since we can't add attributes directly
        self._connection_metadata: dict[int, dict[str, Any]] = {}
        
        # Fill the pool initially
        self._fill_pool()
    
    def _fill_pool(self) -> None:
        """Pre-create connections and fill the pool"""
        for _ in range(self.max_connections):
            conn = self._create_connection()
            if conn:
                self.pool.put(conn)
    
    def _create_connection(self) -> sqlite3.Connection | None:
        """
        Create a new SQLite connection
        
        Returns:
            sqlite3.Connection or None: A new database connection or None if connection failed
        """
        try:
            # Create connection with foreign keys enabled and allow specific thread usage
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("PRAGMA foreign_keys = ON")
            
            # Store metadata about this connection
            conn_id = id(conn)
            self._connection_metadata[conn_id] = {
                'thread_id': threading.get_ident(),
                'created_at': time.time()  # Use time.time() instead of threading.time.time()
            }
            
            return conn
        except sqlite3.Error as e:
            _logger.error(f"Error creating database connection: {e}")
            return None
    
    def get_connection(self) -> sqlite3.Connection | None:
        """
        Get a connection from the pool or create a new one if needed
        
        Returns:
            sqlite3.Connection or None: A database connection or None if connection failed
        """
        current_thread_id = threading.get_ident()
        
        # First try to get a connection from the pool
        try:
            conn = self.pool.get(block=False)
            conn_id = id(conn)
            
            # Check if this connection has metadata and belongs to the current thread
            if conn_id in self._connection_metadata:
                metadata = self._connection_metadata[conn_id]
                if metadata['thread_id'] != current_thread_id:
                    # If from a different thread, close it and create a new one
                    _logger.debug(f"Connection from thread {metadata['thread_id']} cannot be used in thread {current_thread_id}")
                    conn.close()
                    # Remove metadata for closed connection
                    self._connection_metadata.pop(conn_id, None)
                    conn = self._create_connection()
            else:
                # If connection has no metadata, update it
                self._connection_metadata[conn_id] = {
                    'thread_id': current_thread_id,
                    'created_at': time.time()  # Use time.time() instead of threading.time.time()
                }
            
            return conn
        except queue.Empty:
            # If pool is empty, create a new connection
            _logger.warning("Connection pool empty, creating new connection")
            conn = self._create_connection()
            return conn
    
    def return_connection(self, conn: sqlite3.Connection | None) -> None:
        """
        Return a connection to the pool
        
        Args:
            conn: The database connection to return to the pool
        """
        if conn is None:
            return
        
        conn_id = id(conn)
        
        try:
            # Update thread ID in metadata
            if conn_id in self._connection_metadata:
                self._connection_metadata[conn_id]['thread_id'] = threading.get_ident()
            
            # Only put the connection back if the pool isn't full
            if not self.pool.full():
                self.pool.put(conn, block=False)
            else:
                # If pool is full, close this connection
                conn.close()
                # Remove metadata for the closed connection
                self._connection_metadata.pop(conn_id, None)
        except queue.Full:
            # If can't return to pool, close the connection
            conn.close()
            # Remove metadata for the closed connection
            self._connection_metadata.pop(conn_id, None)
    
    def close_all(self) -> None:
        """
        Close all connections in the pool
        """
        with self._lock:
            # Empty the queue and close each connection
            while not self.pool.empty():
                try:
                    conn = self.pool.get(block=False)
                    conn_id = id(conn)
                    conn.close()
                    # Remove metadata for the closed connection
                    self._connection_metadata.pop(conn_id, None)
                except queue.Empty:
                    break
            
            # Clear all metadata
            self._connection_metadata.clear()


class ConnectionContext:
    """Context manager for database connections"""

    def __init__(self, connector: SQLiteConnectionPool) -> None:
        """Initialize the context manager with a connection pool"""
        self.connector: SQLiteConnectionPool = connector
        self.conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection | None:
        """Get a connection from the pool when entering the context"""
        self.conn = self.connector.get_connection()
        return self.conn
    
    def __exit__(self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any | None) -> None:
        """Return the connection to the pool when exiting the context"""
        if self.conn:
            if exc_type:
                try:
                    self.conn.rollback()
                except Exception:
                    pass
            else:
                try:
                    self.conn.commit()
                except Exception:
                    pass
            self.connector.return_connection(self.conn)  # Changed from _return_connection to return_connection