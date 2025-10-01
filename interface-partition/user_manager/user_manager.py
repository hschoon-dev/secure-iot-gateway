import sqlite3
import os
import bcrypt
import logging
from typing import TypedDict

from .db_connection_pool import SQLiteConnectionPool, ConnectionContext

_logger = logging.getLogger(__name__)
__path__ = os.path.dirname(os.path.abspath(__file__))
credentials_db_file_path = os.path.join(__path__, 'credentials.db')

class UserDetails(TypedDict):
    id: int
    username: str

class UserManager():
    def __init__(self, db_file_path: str, max_connections: int = 5):
        self.db_path: str = db_file_path
        self.connection_pool: SQLiteConnectionPool = SQLiteConnectionPool(db_file_path, max_connections)
        self.db: DatabaseConnector = DatabaseConnector(db_file_path, connection_pool=self.connection_pool) 

    def create_user(self, username: str, password: str) -> bool:
        """
        Create a new user with securely hashed password
        
        Parameters:
        - username: Username for the new account
        - password: Password for the new account
        
        Returns:
        - True if successful, False if failed
        """
        # Input validation
        if not username or not password:
            _logger.error("Username and password cannot be empty")
            return False
         
        # Validate password
        validate_password_result, validate_password_msg = self.validate_password(password)
        if not validate_password_result:
            _logger.error(f"Password validation failed: {validate_password_msg}")
            return False
        
        # Prepare credentials tuple
        credentials_without_salt = (username, password)
        
        # Attempt to insert the credentials
        res = self.db.insert_credentials(credentials_without_salt)
        
        # Log the result
        if res:
            _logger.info(f"Created user '{username}'")
        else:
            _logger.error(f"Failed to create user '{username}'")
            
        return res

    def delete_user(self, id: int) -> bool:
        """
        Delete a user by ID
        
        Args:
            id: User ID to delete
            
        Returns:
            True if successful, False if failed
        """
        return self.db.delete_credentials(id)

    def update_user(self, username: str, old_password: str, new_password: str) -> bool:
        """
        Update a user's password
        
        Args:
            username: Username of the account to update
            old_password: Current password
            new_password: New password to set
            
        Returns:
            True if successful, False if failed
        """
        return self.db.update_credentials(username, old_password, new_password)

    def retrieve_user(self, username: str) -> tuple[bool, tuple[int, str, str, str] | None]:
        """
        Retrieve user data by username
        
        Args:
            username: Username to retrieve
            
        Returns:
            Tuple containing (success, user_data)
            Where user_data is (id, username, hashed_password, salt) if found, otherwise None
        """
        return self.db.retrieve_credentials(username)

    def clear_database(self) -> bool:
        """
        Clear all user data from the database
        
        Returns:
            True if successful, False if failed
        """
        self.db.clear_database()

    @staticmethod
    def validate_password(password: str) -> tuple[bool, str]:
        """
        Validate that password meets security requirements
        
        Args:
            password: Password to validate
            
        Returns:
            Tuple containing (is_valid, message)
        """
        if len(password) < 21:
            return False, "Password must be at least 21 characters long"
            
        # Enforce complexity requirements
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        if not (has_upper and has_lower and has_digit):
            return False, "Password must contain uppercase, lowercase, and digits"
        
        return True, "Password meets requirements"
    
    @staticmethod
    def hash_password(password: str, salt: str) -> str:
        """
        Hash password using bcrypt with specific salt
        
        Args:
            password: Password to hash
            salt: Salt to use in hashing
            
        Returns:
            Hashed password
        """
        if not isinstance(password, str):
            password = str(password)
        if not isinstance(salt, str):
            salt = str(salt)
            
        # Combine password with salt
        salted_password = password + salt
        
        # Hash using bcrypt
        return bcrypt.hashpw(salted_password.encode('utf-8'), 
                            bcrypt.gensalt()).decode('utf-8')


    @staticmethod
    def verify_password(password: str, salt: str, stored_hash: str) -> bool:
        """
        Verify password using bcrypt
        
        Args:
            password: Password to verify
            salt: Salt used in original hash
            stored_hash: Stored hash to compare against
            
        Returns:
            True if password matches, False otherwise
        """
        if not isinstance(password, str):
            password = str(password)
        if not isinstance(salt, str):
            salt = str(salt)
            
        # Combine password with salt
        salted_password = password + salt
        
        # Verify the hash
        return bcrypt.checkpw(salted_password.encode('utf-8'), 
                            stored_hash.encode('utf-8'))

    def verify_credentials(self, username: str, password: str) -> bool:
        """
        Verify if the provided credentials are valid.
        
        Args:
            username: The username to verify
            password: The password to verify
            
        Returns:
            True if credentials are valid, False otherwise
        """
        result = self.retrieve_user(username)
        
        # Handle case where user doesn't exist
        if result is None:
            _logger.warning(f"User {username} not found in database")
            return False
        
        # If retrieve_user returns a tuple (as expected)
        if isinstance(result, tuple):
            res, user = result
            if not res or user is None:
                _logger.warning(f"Failed to retrieve user {username}")
                return False
            
            # User is a tuple with format (id, username, hashed_password, salt)
            stored_hash = user[2]  # password hash
            user_salt = user[3]    # user-specific salt
            
            # Verify the password using salt
            return self.verify_password(password, user_salt, stored_hash)
        
        # Alternative implementation if retrieve_user has a different return format
        # This code path should not be reached based on your implementation
        _logger.warning(f"Unexpected return format from retrieve_user for {username}")
        return False
    
    # Add these methods to the UserManager class
    def user_exists(self, username: str) -> bool:
        """
        Check if a user exists in the database
        
        Args:
            username: Username to check
            
        Returns:
            True if user exists, False otherwise
        """
        res, user = self.retrieve_user(username)
        return res and user is not None

    def get_all_users(self) -> list[str]:
        """
        Get all usernames from the database
        
        Returns:
            List of all usernames
        """
        try:
            users = []
            conn = self.connection_pool.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT username FROM credentials")
                rows = cursor.fetchall()
                for row in rows:
                    users.append(row[0])  # Username is at index 0
            finally:
                self.connection_pool.return_connection(conn)
            return users
        except Exception as e:
            _logger.error(f"Error getting all users: {e}")
            return []

    def set_role(self, username: str, role: str) -> bool:
        """
        Set a user's role (not implemented - would require schema change)
        
        Args:
            username: Username to modify
            role: Role to assign
            
        Returns:
            True if successful, False otherwise
        """
        _logger.warning(f"Role management is not implemented in the current database schema")
        return False
            
    def get_user_details(self, username: str) -> UserDetails | None:
        """
        Get detailed information about a user
        
        Args:
            username: Username to retrieve details for
            
        Returns:
            Dictionary with user details if found, None otherwise
        """
        res, user = self.retrieve_user(username)
        if not res or user is None:
            return None
        
        # Return a dictionary with safe user information
        # Omitting password hash and salt
        return {
            "id": user[0],
            "username": user[1],
            # Add additional fields if your schema has them
        }
    
    def __del__(self) -> None:
        """Clean up resources when object is destroyed"""
        if hasattr(self, 'connection_pool'):
            self.connection_pool.close_all()   

class DatabaseConnector:
    def __init__(self, db_path: str, connection_pool: SQLiteConnectionPool | None = None) -> None:
        self.db_path: str = db_path
        self.connection_pool: SQLiteConnectionPool | None = connection_pool
        self._owned_connection: sqlite3.Connection | None = None
        self._create_credentials_table()
    
    def connection(self) -> ConnectionContext:
        """
        Get a connection context that will automatically be returned to the pool
        
        Returns:
            Connection context manager
        """
        return ConnectionContext(self.connection_pool)
    
    def _get_connection(self) -> sqlite3.Connection | None:
        """
        Get a raw connection from the pool
        
        Returns:
            Database connection or None if connection failed
        """
        return self.connection_pool.get_connection()
    
    def _return_connection(self, conn: sqlite3.Connection | None) -> None:
        """
        Return a connection to the pool
        
        Args:
            conn: Connection to return
        """
        self.connection_pool.return_connection(conn)

    def _create_connection(self) -> sqlite3.Connection | None:
        """
        Create a database connection to the SQLite database
        
        Returns:
            Connection object or None if connection failed
        """
        conn = None
        try:
            conn = sqlite3.connect(self._db_file)
            _logger.info('Connection to database successful')
            return conn
        except sqlite3.Error as e:
            _logger.error(f'Error connecting to database: {e}')
            return False

    def _create_credentials_table(self) -> None:
        """Create the credentials table if it doesn't exist"""
        sql_create_credentials_table = """ CREATE TABLE IF NOT EXISTS credentials (
                                            id integer PRIMARY KEY,
                                            username text NOT NULL,
                                            password text NOT NULL,
                                            salt text NOT NULL
                                        ); """
        self._create_table(sql_create_credentials_table)

    def _create_table(self, create_table_sql: str) -> None:
        """
        Create a table from the create_table_sql statement
        
        Args:
            create_table_sql: SQL statement to create table
        """
        try:
            with self.connection() as conn:
                c = conn.cursor()
                c.execute(create_table_sql)
                _logger.info('Table created')
        except sqlite3.Error as e:
            _logger.error(f'Error creating table: {e}')

    def insert_credentials(self, credentials: tuple[str, str]) -> bool:
        """
        Insert user credentials into the database
        
        Args:
            credentials: Tuple containing (username, plain_password)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Check if username exists first
            res, user = self.retrieve_credentials(credentials[0])
            if res:
                _logger.error('Username already exists')
                return False
                
            # Generate a unique salt for this user
            user_salt = os.urandom(32).hex()
            
            # Combine password with user-specific salt
            salted_password = credentials[1] + user_salt
            hashed_password = bcrypt.hashpw(salted_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            # Store credentials with salt
            hashed_credentials = (credentials[0], hashed_password, user_salt)
            
            # Use the context manager to ensure proper connection handling
            with self.connection() as conn:
                sql = '''INSERT INTO credentials(username, password, salt) VALUES(?, ?, ?)'''
                cur = conn.cursor()
                cur.execute(sql, hashed_credentials)
                conn.commit()
                _logger.info('Credentials inserted')
                return True
                
        except sqlite3.IntegrityError as e:
            _logger.error(f"Database integrity error: {e}")
            return False
        except Exception as e:
            _logger.error(f"Error inserting credentials: {e}")
            return False

    def delete_credentials(self, id: int) -> bool:
        """
        Delete a credential by credential id
        
        Args:
            id: ID of the credential to delete
            
        Returns:
            True if successful, False otherwise
        """
        sql = 'DELETE FROM credentials WHERE id=?'
        try:
            with self.connection() as conn:
                cur = conn.cursor()
                cur.execute(sql, (id,))
                conn.commit()
                _logger.info('Credentials deleted')
                return True
        except sqlite3.Error as e:
            _logger.error(f'Error deleting credentials: {e}')
            return False

    def retrieve_credentials(self, username: str) -> tuple[bool, tuple[int, str, str, str] | None]:
        """
        Query credentials by username
        
        Args:
            username: Username to retrieve
            
        Returns:
            Tuple containing (success, user_data)
            Where user_data is (id, username, hashed_password, salt) if found, otherwise None
        """
        sql = 'SELECT * FROM credentials WHERE username=?'
        
        # Use the context manager to ensure proper connection handling
        try:
            with self.connection() as conn:
                cur = conn.cursor()
                cur.execute(sql, (username,))
                credentials = cur.fetchone()
                if credentials is not None:
                    _logger.info('Credentials retrieved')
                    return True, credentials
                _logger.warning(f'No credentials found for username: {username}')
                return False, None
        except sqlite3.Error as e:
            _logger.error(f'Error retrieving credentials: {e}')
            return False, None
        except Exception as e:
            _logger.error(f'Unexpected error retrieving credentials: {e}')
            return False, None
            
    def update_credentials(self, username: str, old_password: str, new_password: str) -> bool:
        """
        Update user credentials while maintaining unique salt
        
        Args:
            username: Username to update
            old_password: Current password
            new_password: New password to set
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Retrieve the user's credentials
            res, user_credentials = self.retrieve_credentials(username)
            if not res or user_credentials is None:
                _logger.error('Username does not exist')
                return False
            
            # Get user's salt
            user_salt = user_credentials[3]
            stored_hash = user_credentials[2]
            
            # Check if old password is correct using existing salt
            salted_old_password = old_password + user_salt
            if not bcrypt.checkpw(salted_old_password.encode('utf-8'), stored_hash.encode('utf-8')):
                _logger.error('Old password is incorrect')
                return False
            
            # Update with new password (keeping the same salt)
            hashed_new_password = UserManager.hash_password(new_password, user_salt)
            
            with self.connection() as conn:
                sql = '''UPDATE credentials SET password = ? WHERE username = ?'''
                cur = conn.cursor()
                cur.execute(sql, (hashed_new_password, username))
                conn.commit()
                _logger.info('Credentials updated')
                return True
        except sqlite3.Error as e:
            _logger.error(f'Error updating credentials: {e}')
            return False
        except Exception as e:
            _logger.error(f"Unexpected error: {e}")
            return False         

    def clear_database(self) -> bool:
        """
        Delete all rows in the credentials table
        
        Returns:
            True if successful, False otherwise
        """
        sql = 'DELETE FROM credentials'
        try:
            with self.connection() as conn:
                cur = conn.cursor()
                cur.execute(sql)
                conn.commit()
                _logger.info('Database cleared')
                return True
        except sqlite3.Error as e:
            _logger.error(f'Error clearing database: {e}')
            return False

    # Fix the DatabaseConnector.__del__ method
    def __del__(self) -> None:
        """Properly clean up resources"""
        try:
            # Don't get a new connection in __del__
            # Just release any owned connection if we have one
            if self._owned_connection:
                try:
                    self._owned_connection.close()
                except Exception as e:
                    pass  # Silently fail in destructor
        except Exception:
            pass  # Ensure no exceptions escape __del__



def main():
    user_manager = UserManager(credentials_db_file_path)
    
    print("\n=== Testing User Management System (OPC UA Server Version) ===\n")
    
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
    update_result = user_manager.update_user('admin', admin_password, new_admin_password)
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
    
    print("\n=== Test Complete ===\n")

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()