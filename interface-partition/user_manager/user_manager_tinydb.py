"""
------------------------------------------------------------
 Modul:    interface-partition/user_manager.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    The user manager module provides functionality for
    managing user accounts, including creating, updating,
    deleting, and retrieving user information. It securely
    handles password hashing and verification using bcrypt
    with unique salts for each user. The module now uses
    TinyDB for storage and a thread lock for concurrency.

 Autor(en):
    - Heiko Schoon

 Maintainer:
    - Heiko Schoon <heiko.schoon@hs-emden-leer.de>

 Hinweis:
    Ongoing development.
------------------------------------------------------------
"""

import os
import bcrypt
import logging
import threading
from typing import TypedDict

from tinydb import TinyDB, Query
from tinydb.table import Document
from tinydb.storages import JSONStorage
from tinydb.middlewares import CachingMiddleware

_logger = logging.getLogger(__name__)
__path__ = os.path.dirname(os.path.abspath(__file__))
# Use JSON file for TinyDB
credentials_db_file_path = os.path.join(__path__, 'credentials.json')


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
            _admin_password = os.getenv("ADMIN_PASSWORD")
            return _admin_password
        except Exception as e:
            _logger.error(f"Error reading ADMIN_PASSWORD from environment: {e}")

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

        # Missing admin: require a password or abort
        admin_pw = self._read_admin_password_from_env()
        if not admin_pw:
            _logger.critical(
                "No admin user exists and ADMIN_PASSWORD/ADMIN_PASSWORD_FILE not provided. "
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
        """
        Create a new user with securely hashed password
        """
        if not username or not password:
            _logger.error("Username and password cannot be empty")
            return False

        validate_password_result, validate_password_msg = self.validate_password(password)
        if not validate_password_result:
            _logger.error(f"Password validation failed: {validate_password_msg}")
            return False

        credentials_without_salt = (username, password)
        res = self.db.insert_credentials(credentials_without_salt)

        if res:
            _logger.info(f"Created user '{username}'")
        else:
            _logger.error(f"Failed to create user '{username}'")

        return res

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
    def hash_password(password: str, salt: str) -> str:
        """Hash password using bcrypt with specific salt"""
        if not isinstance(password, str):
            password = str(password)
        if not isinstance(salt, str):
            salt = str(salt)

        salted_password = password + salt
        return bcrypt.hashpw(salted_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def verify_password(password: str, salt: str, stored_hash: str) -> bool:
        """Verify password using bcrypt"""
        if not isinstance(password, str):
            password = str(password)
        if not isinstance(salt, str):
            salt = str(salt)

        salted_password = password + salt
        return bcrypt.checkpw(salted_password.encode("utf-8"), stored_hash.encode("utf-8"))

    def verify_credentials(self, username: str, password: str) -> bool:
        """Verify if the provided credentials are valid."""
        result = self.retrieve_user(username)

        if result is None:
            _logger.warning(f"User {username} not found in database")
            return False

        if isinstance(result, tuple):
            res, user = result
            if not res or user is None:
                _logger.warning(f"Failed to retrieve user {username}")
                return False

            stored_hash = user[2]  # password hash
            user_salt = user[3]    # user-specific salt
            return self.verify_password(password, user_salt, stored_hash)

        _logger.warning(f"Unexpected return format from retrieve_user for {username}")
        return False

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
        return {
            "id": user[0],
            "username": user[1],
        }

    def __del__(self) -> None:
        """No persistent handles to close with TinyDB"""
        pass


class DatabaseConnector:
    """
    TinyDB-backed credential store.

    Table schema (document fields):
      - username: str (unique)
      - password: str (bcrypt hash of password+salt)
      - salt:     str (hex, per-user)
    TinyDB doc_id is exposed as 'id' to match previous API.
    """

    def __init__(self, db_path: str) -> None:
        # CachingMiddleware reduces writes; flushes on close/GC.
        self._lock = threading.RLock()
        self._db = TinyDB(db_path, storage=CachingMiddleware(JSONStorage))
        self._table = self._db.table("credentials")
        self._User = Query()
        # No explicit table creation needed.

    def insert_credentials(self, credentials: tuple[str, str]) -> bool:
        """
        Insert user credentials into the store.
        credentials: (username, plain_password)
        """
        username, plain_password = credentials
        try:
            with self._lock:
                # Enforce unique username
                existing = self._table.get(self._User.username == username)
                if existing is not None:
                    _logger.error("Username already exists")
                    return False

                user_salt = os.urandom(32).hex()
                salted_password = plain_password + user_salt
                hashed_password = bcrypt.hashpw(
                    salted_password.encode("utf-8"), bcrypt.gensalt()
                ).decode("utf-8")

                doc = {"username": username, "password": hashed_password, "salt": user_salt}
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
                # remove(doc_ids=[...]) is the most direct way
                removed = self._table.remove(doc_ids=[id])
                _logger.info("Credentials deleted")
                return True
        except Exception as e:
            _logger.error(f"Error deleting credentials: {e}")
            return False

    def retrieve_credentials(self, username: str) -> tuple[bool, tuple[int, str, str, str] | None]:
        """
        Return (True, (id, username, hashed_password, salt)) if found, else (False, None)
        """
        try:
            with self._lock:
                doc: Document | None = self._table.get(self._User.username == username)
                if doc is None:
                    _logger.warning(f"No credentials found for username: {username}")
                    return False, None
                # doc.doc_id is the record id we expose for compatibility
                row = (int(doc.doc_id), doc["username"], doc["password"], doc["salt"])
                _logger.info("Credentials retrieved")
                return True, row
        except Exception as e:
            _logger.error(f"Unexpected error retrieving credentials: {e}")
            return False, None

    def update_credentials(self, username: str, old_password: str, new_password: str) -> bool:
        """
        Update user's password. Keeps the same salt (as your prior implementation).
        """
        try:
            with self._lock:
                doc: Document | None = self._table.get(self._User.username == username)
                if doc is None:
                    _logger.error("Username does not exist")
                    return False

                user_salt = doc["salt"]
                stored_hash = doc["password"]

                salted_old_password = old_password + user_salt
                if not bcrypt.checkpw(salted_old_password.encode("utf-8"), stored_hash.encode("utf-8")):
                    _logger.error("Old password is incorrect")
                    return False

                hashed_new_password = UserManagerTinyDB.hash_password(new_password, user_salt)

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
        # Ensure cache flushes
        try:
            self._db.close()
        except Exception:
            pass


def main():
    user_manager = UserManagerTinyDB(credentials_db_file_path)

    print("\n=== Testing User Management System (TinyDB Version) ===\n")

    # Clear database for testing
    print("Clearing database...")
    user_manager.clear_database()

    # Create complex passwords that meet requirements
    admin_password = "Admin123_secure_password_2025"  # 28 chars with upper, lower, digits
    user_password = "User456_very_secure_pwd_2025"    # 28 chars with upper, lower, digits

    # Test user creation
    print("\n--- Testing User Creation ---")
    res_admin = user_manager.create_user('admin', admin_password)
    res_user = user_manager.create_user('user', user_password)
    print(f"Created admin with Result: {res_admin}")
    print(f"Created user with Result: {res_user}")

    # Test password requirements failures
    print("\n--- Testing Password Requirements ---")
    short_pw_result = user_manager.create_user('test1', 'Short1')
    no_upper_result = user_manager.create_user('test2', 'this_has_no_uppercase_chars_123')
    no_lower_result = user_manager.create_user('test3', 'THIS_HAS_NO_LOWERCASE_CHARS_123')
    no_digit_result = user_manager.create_user('test4', 'This_has_no_digits_at_all')
    print(f"Short password result: {short_pw_result}")
    print(f"No uppercase result: {no_upper_result}")
    print(f"No lowercase result: {no_lower_result}")
    print(f"No digits result: {no_digit_result}")

    # Test duplicate username
    print("\n--- Testing Duplicate Username ---")
    duplicate_id = user_manager.create_user('user', 'Different789_secure_password_2025')
    print(f"Attempted duplicate creation result: {duplicate_id}")

    # Test user retrieval
    print("\n--- Testing User Retrieval ---")
    res_admin, admin_record = user_manager.retrieve_user('admin')
    res_user, user_record = user_manager.retrieve_user('user')
    print(f"Admin record: {admin_record} with status {res_admin}")
    print(f"User record: {user_record} with status {res_user}")

    # Test credential verification
    print("\n--- Testing Credential Verification ---")
    admin_valid = user_manager.verify_credentials('admin', admin_password)
    admin_invalid = user_manager.verify_credentials('admin', 'wrong_password_123456789012')
    print(f"Admin valid credentials: {admin_valid}")
    print(f"Admin invalid credentials: {admin_invalid}")

    # Test password update
    print("\n--- Testing Password Update ---")
    new_admin_password = "NewAdmin987_secure_password_2025"
    update_result = user_manager.update_user('admin', old_password=admin_password, new_password=new_admin_password)
    print(f"Password update result: {update_result}")

    # Verify the new password works
    admin_valid = user_manager.verify_credentials('admin', new_admin_password)
    print(f"Admin with new password: {admin_valid}")

    # Old password should fail
    admin_invalid = user_manager.verify_credentials('admin', admin_password)
    print(f"Admin with old password: {admin_invalid}")

    # Test failed update with incorrect old password
    update_result = user_manager.update_user('admin', 'wrong_old_password_12345678', 'Another567_secure_password_2025')
    print(f"Update with incorrect old password: {update_result}")

    # Show all users
    print("\n--- All Users ---")
    print(user_manager.get_all_users())

    print("\n=== Test Complete ===\n")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
