"""
------------------------------------------------------------
 Modul:    interface-partition/user_manager.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    The user manager module provides functionality for
    managing user accounts, including creating, updating,
    deleting, and retrieving user information.

    Password hashing / verification now uses Argon2id
    (argon2-cffi) instead of bcrypt.

 Autor(en):
    - Heiko Schoon

 Maintainer:
    - Heiko Schoon <heiko.schoon@hs-emden-leer.de>

 Hinweis:
    Ongoing development.
------------------------------------------------------------
"""

import os
import logging
import threading
from typing import TypedDict

from tinydb import TinyDB, Query
from tinydb.table import Document
from tinydb.storages import JSONStorage
from tinydb.middlewares import CachingMiddleware

from argon2 import PasswordHasher
from argon2.low_level import Type
from argon2 import exceptions as argon2_exceptions

_logger = logging.getLogger(__name__)
__path__ = os.path.dirname(os.path.abspath(__file__))
credentials_db_file_path = os.path.join(__path__, "credentials.json")

# Argon2id configuration (tune for your device constraints)
# memory_cost is in KiB. Example: 64 * 1024 = 64 MiB.
_ARGON2 = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,
    parallelism=2,
    hash_len=32,
    salt_len=16,
    type=Type.ID,   # Argon2id
)


class UserDetails(TypedDict):
    id: int
    username: str


class UserManagerTinyDB:
    def __init__(self, db_file_path: str, max_connections: int = 5):  # max_connections kept for API compatibility
        self.db_path: str = db_file_path
        self.db: DatabaseConnector = DatabaseConnector(db_file_path)
        self._bootstrap_admin_or_die()

    def _read_admin_password_from_env(self) -> str | None:
        try:
            return os.getenv("ADMIN_PASSWORD")
        except Exception as e:
            _logger.error(f"Error reading ADMIN_PASSWORD from environment: {e}")
            return None

    def _bootstrap_admin_or_die(self) -> None:
        """
        Ensure an 'admin' user exists. If missing and no password is provided, abort startup.
        Idempotent: never overwrites existing admin credentials.
        """
        try:
            exists, record = self.retrieve_user("admin")
        except Exception as e:
            _logger.critical("User store not accessible during bootstrap: %s", e, exc_info=True)
            raise SystemExit(2)

        if exists and record:
            _logger.info("Admin user already present; skipping bootstrap.")
            return

        admin_pw = self._read_admin_password_from_env()
        if not admin_pw:
            _logger.critical(
                "No admin user exists and ADMIN_PASSWORD not provided. "
                "Refusing to start in an insecure state."
            )
            raise SystemExit(2)

        try:
            self.create_user(username="admin", password=admin_pw)
            _logger.info("Initial admin user created.")
        except Exception as e:
            _logger.critical("Failed to create initial admin user: %s", e, exc_info=True)
            raise SystemExit(2)

    def create_user(self, username: str, password: str) -> bool:
        """Create a new user with securely hashed password (Argon2id)."""
        if not username or not password:
            _logger.error("Username and password cannot be empty")
            return False

        validate_password_result, validate_password_msg = self.validate_password(password)
        if not validate_password_result:
            _logger.error(f"Password validation failed: {validate_password_msg}")
            return False

        return self.db.insert_credentials((username, password))

    def delete_user(self, id: int) -> bool:
        """Delete a user by ID"""
        return self.db.delete_credentials(id)

    def update_user(self, username: str, old_password: str, new_password: str) -> bool:
        """Update a user's password"""
        return self.db.update_credentials(username, old_password, new_password)

    def retrieve_user(self, username: str) -> tuple[bool, tuple[int, str, str, str] | None]:
        """Retrieve user data by username"""
        return self.db.retrieve_credentials(username)

    def clear_database(self) -> bool:
        """Clear all user data from the database"""
        return self.db.clear_database()

    @staticmethod
    def validate_password(password: str) -> tuple[bool, str]:
        """Validate that password meets security requirements"""
        if len(password) < 21:
            return False, "Password must be at least 21 characters long"

        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        if not (has_upper and has_lower and has_digit):
            return False, "Password must contain uppercase, lowercase, and digits"

        return True, "Password meets requirements"

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash password using Argon2id."""
        if not isinstance(password, str):
            password = str(password)
        return _ARGON2.hash(password)

    @staticmethod
    def verify_password(password: str, stored_hash: str) -> bool:
        """Verify password using Argon2id."""
        if not isinstance(password, str):
            password = str(password)
        try:
            return _ARGON2.verify(stored_hash, password)
        except (argon2_exceptions.VerifyMismatchError, argon2_exceptions.InvalidHash):
            return False

    def verify_credentials(self, username: str, password: str) -> bool:
        """Verify if the provided credentials are valid."""
        res, user = self.retrieve_user(username)
        if not res or user is None:
            _logger.warning(f"User {username} not found or failed to retrieve")
            return False

        stored_hash = user[2]  # argon2 hash string (includes salt/params)
        ok = self.verify_password(password, stored_hash)

        # Optional: if parameters changed, you can rehash-on-login
        # (requires a DB write; uncomment if you want that behavior)
        # if ok and _ARGON2.check_needs_rehash(stored_hash):
        #     self.db.rehash_password(username, password)

        return ok

    def user_exists(self, username: str) -> bool:
        """Check if a user exists in the database"""
        res, user = self.retrieve_user(username)
        return res and user is not None

    def get_all_users(self) -> list[str]:
        """Get all usernames from the database"""
        try:
            return self.db.get_all_usernames()
        except Exception as e:
            _logger.error(f"Error getting all users: {e}")
            return []

    def set_role(self, username: str, role: str) -> bool:
        """Set a user's role (not implemented)"""
        _logger.warning("Role management is not implemented in the current database schema")
        return False

    def get_user_details(self, username: str) -> UserDetails | None:
        """Get detailed information about a user"""
        res, user = self.retrieve_user(username)
        if not res or user is None:
            return None
        return {"id": user[0], "username": user[1]}

    def __del__(self) -> None:
        pass


class DatabaseConnector:
    """
    TinyDB-backed credential store.

    Table schema (document fields):
      - username: str (unique)
      - password: str (Argon2id hash string, includes salt+params)
      - salt:     str (kept only for backwards API compatibility; unused)
    TinyDB doc_id is exposed as 'id' to match previous API.
    """

    def __init__(self, db_path: str) -> None:
        self._lock = threading.RLock()
        self._db = TinyDB(db_path, storage=CachingMiddleware(JSONStorage))
        self._table = self._db.table("credentials")
        self._User = Query()

    def insert_credentials(self, credentials: tuple[str, str]) -> bool:
        """Insert user credentials into the store. credentials: (username, plain_password)"""
        username, plain_password = credentials
        try:
            with self._lock:
                existing = self._table.get(self._User.username == username)
                if existing is not None:
                    _logger.error("Username already exists")
                    return False

                hashed_password = UserManagerTinyDB.hash_password(plain_password)

                # Keep "salt" field for compatibility, but unused with Argon2id
                doc = {"username": username, "password": hashed_password, "salt": ""}
                self._table.insert(doc)
                _logger.info("Credentials inserted")
                return True
        except Exception as e:
            _logger.error(f"Error inserting credentials: {e}")
            return False

    def delete_credentials(self, id: int) -> bool:
        """Delete a credential by TinyDB doc_id"""
        try:
            with self._lock:
                self._table.remove(doc_ids=[id])
                _logger.info("Credentials deleted")
                return True
        except Exception as e:
            _logger.error(f"Error deleting credentials: {e}")
            return False

    def retrieve_credentials(self, username: str) -> tuple[bool, tuple[int, str, str, str] | None]:
        """Return (True, (id, username, hashed_password, salt)) if found, else (False, None)"""
        try:
            with self._lock:
                doc: Document | None = self._table.get(self._User.username == username)
                if doc is None:
                    _logger.warning(f"No credentials found for username: {username}")
                    return False, None
                row = (int(doc.doc_id), doc["username"], doc["password"], doc.get("salt", ""))
                _logger.info("Credentials retrieved")
                return True, row
        except Exception as e:
            _logger.error(f"Unexpected error retrieving credentials: {e}")
            return False, None

    def update_credentials(self, username: str, old_password: str, new_password: str) -> bool:
        """Update user's password (Argon2id)."""
        try:
            with self._lock:
                doc: Document | None = self._table.get(self._User.username == username)
                if doc is None:
                    _logger.error("Username does not exist")
                    return False

                stored_hash = doc["password"]
                if not UserManagerTinyDB.verify_password(old_password, stored_hash):
                    _logger.error("Old password is incorrect")
                    return False

                hashed_new_password = UserManagerTinyDB.hash_password(new_password)
                self._table.update({"password": hashed_new_password}, doc_ids=[doc.doc_id])
                _logger.info("Credentials updated")
                return True
        except Exception as e:
            _logger.error(f"Unexpected error updating credentials: {e}")
            return False

    def clear_database(self) -> bool:
        """Delete all rows in the credentials table"""
        try:
            with self._lock:
                self._table.truncate()
                _logger.info("Database cleared")
                return True
        except Exception as e:
            _logger.error(f"Error clearing database: {e}")
            return False

    def get_all_usernames(self) -> list[str]:
        """Helper for UserManager.get_all_users()"""
        try:
            with self._lock:
                return [doc["username"] for doc in self._table.all()]
        except Exception as e:
            _logger.error(f"Error listing users: {e}")
            return []

    def __del__(self) -> None:
        try:
            self._db.close()
        except Exception:
            pass


def main():
    user_manager = UserManagerTinyDB(credentials_db_file_path)

    print("\n=== Testing User Management System (TinyDB Version / Argon2id) ===\n")

    print("Clearing database...")
    user_manager.clear_database()

    admin_password = "Admin123_secure_password_2025"
    user_password = "User456_very_secure_pwd_2025"

    print("\n--- Testing User Creation ---")
    res_admin = user_manager.create_user("admin", admin_password)
    res_user = user_manager.create_user("user", user_password)
    print(f"Created admin with Result: {res_admin}")
    print(f"Created user with Result: {res_user}")

    print("\n--- Testing Credential Verification ---")
    admin_valid = user_manager.verify_credentials("admin", admin_password)
    admin_invalid = user_manager.verify_credentials("admin", "wrong_password_123456789012")
    print(f"Admin valid credentials: {admin_valid}")
    print(f"Admin invalid credentials: {admin_invalid}")

    print("\n--- Testing Password Update ---")
    new_admin_password = "NewAdmin987_secure_password_2025"
    update_result = user_manager.update_user("admin", old_password=admin_password, new_password=new_admin_password)
    print(f"Password update result: {update_result}")

    admin_valid = user_manager.verify_credentials("admin", new_admin_password)
    print(f"Admin with new password: {admin_valid}")

    admin_invalid = user_manager.verify_credentials("admin", admin_password)
    print(f"Admin with old password: {admin_invalid}")

    print("\n--- All Users ---")
    print(user_manager.get_all_users())

    print("\n=== Test Complete ===\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
