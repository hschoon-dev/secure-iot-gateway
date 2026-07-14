"""
------------------------------------------------------------
 Modul:    interface-partition/authorization_handler.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    This module contains an authorization handler using the
    Casbin library to manage role-based access control (RBAC).

 Autor(en):
    - Heiko Schoon

 Maintainer:
    - Heiko Schoon <heiko.schoon@hs-emden-leer.de>

 Hinweis:
    Ongoing development.
------------------------------------------------------------
"""

import casbin
import os
import logging
import threading

_logger = logging.getLogger(__name__)

class AuthorizationHandler:
    def __init__(self, model_path=None, policy_path=None):
        self.enforcer = casbin.Enforcer(model_path, policy_path)
        # Casbin mutations are multi-step.  Serializing reads and writes keeps
        # other requests in this process from observing an intermediate state.
        self._lock = threading.RLock()
    
    def verify_authorization(self, username, parameter_name, action):
        with self._lock:
            return self.enforcer.enforce(username, parameter_name, action)

    def check_permission(self, username):
        with self._lock:
            _userroles = self.enforcer.get_roles_for_user(username)
        _logger.error("User roles: %s", _userroles)
        #return self.enforcer.get_roles_for_user(username)
        return _userroles
    
    def check_admin_role(self, username):
        with self._lock:
            return "Admin" in self.enforcer.get_roles_for_user(username)
        #return self.enforcer.get_roles_for_user(username)

    def get_all_admins(self):
        with self._lock:
            return self.enforcer.get_users_for_role("Admin")

    def add_role_for_user(self, user, role):
        with self._lock:
            return self.enforcer.add_role_for_user(user, role)
    
    def remove_role_for_user(self, user, role):
        with self._lock:
            return self.enforcer.delete_role_for_user(user, role)

    def get_roles_for_user(self, user):
        with self._lock:
            return self.enforcer.get_roles_for_user(user)

    def get_all_roles(self):
        with self._lock:
            return self.enforcer.get_all_roles()

    def role_exists(self, role):
        # get_all_roles() liefert nur die Ziel-Rollen von g-Regeln (Vererbung).
        # Anwendungsrollen sind hier als p-Policy-Subjekte definiert (z. B.
        # PlantOperator) und tauchen dort nicht auf -> Vereinigung mit den
        # p-Subjekten pruefen, damit gueltige Rollen erkannt werden.
        with self._lock:
            return role in (
                set(self.enforcer.get_all_roles()) | set(self.enforcer.get_all_subjects())
            )

    def save_policy(self):
        with self._lock:
            return self.enforcer.save_policy()

    def set_single_role_for_user(self, user, role):
        """
        Ensure user has exactly one RBAC role.
        Returns (success: bool, message: str).
        """
        with self._lock:
            if not role:
                return False, "Role must not be empty."
            if not self.role_exists(role):
                return False, f"Role '{role}' does not exist in RBAC policy."

            current_roles = self.enforcer.get_roles_for_user(user)
            if len(current_roles) == 1 and current_roles[0] == role:
                return True, f"User '{user}' already has role '{role}'."

            for current_role in current_roles:
                self.enforcer.delete_role_for_user(user, current_role)

            if not self.enforcer.add_role_for_user(user, role):
                # Best-effort rollback
                for previous_role in current_roles:
                    self.enforcer.add_role_for_user(user, previous_role)
                return False, f"Failed to assign role '{role}' to user '{user}'."

            # save_policy() returns None on success in some Casbin versions;
            # only an explicit False denotes a persistence failure.
            if self.enforcer.save_policy() is False:
                # Best-effort rollback.  The lock keeps the transient state
                # invisible to concurrent authorization checks in this process.
                self.enforcer.delete_role_for_user(user, role)
                for previous_role in current_roles:
                    self.enforcer.add_role_for_user(user, previous_role)
                self.enforcer.save_policy()
                return False, "Failed to persist RBAC policy changes."

            return True, f"Role '{role}' assigned to user '{user}'."
    
    def remove_user(self, user):
        # Casbin save_policy() may return None on success.  Normalize that API
        # quirk so callers do not mistake a successful offboarding for failure.
        with self._lock:
            if not self.enforcer.delete_user(user):
                return False
            return self.enforcer.save_policy() is not False
    
    def check_user_exists(self, user):
        with self._lock:
            _all_roles = self.enforcer.get_all_roles()
            for role in _all_roles:
                if user in self.enforcer.get_users_for_role(role):
                    return True
            return False
        #return self.enforcer.has_role_for_user(user, role)
    
def main(): # Test cases
    path = os.path.dirname(os.path.abspath(__file__))
    casbin_model_path = os.path.join(path, "rbac_model.conf")
    casbin_policy_path = os.path.join(path, "rbac_policy.csv")

    #casbin_model_path_res = os.path.join(path, "rbac_with_resource_roles_model.conf")
    #casbin_policy_path_res = os.path.join(path, "rbac_with_resource_roles_model.csv")

    rbac_handler = AuthorizationHandler(casbin_model_path, casbin_policy_path)

    print("Role-based access control")
    print(rbac_handler.verify_authorization("alice", "parameter1", "read"))
    print(rbac_handler.verify_authorization("alice", "parameter1", "write"))
    print(rbac_handler.verify_authorization("bob", "parameter1", "read"))

    print(rbac_handler.verify_authorization("Administrator", "BoilerTemperature", "increase"))
    print(rbac_handler.verify_authorization("PlantOperator", "BoilerTemperature", "increase"))

    rbac_handler_with_resource_roles = AuthorizationHandler(casbin_model_path, casbin_policy_path)
    print("Role-based access control with resource roles")
    print(rbac_handler_with_resource_roles.verify_authorization("alice", "parameter1", "read"))

if __name__ == "__main__":
    main()
