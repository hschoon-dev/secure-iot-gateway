#from .user_manager import UserManager
#from .db_connection_pool import SQLiteConnectionPool # removed due to unsupported SQLite from ELinOS/PikeOS

from .user_manager_tinydb import UserManagerTinyDB

#__all__ = ['UserManager', 'UserManagerTinyDB', 'SQLiteConnectionPool']
__all__ = ['UserManagerTinyDB']