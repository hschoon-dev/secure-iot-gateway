import casbin
import os
import logging

_logger = logging.getLogger(__name__)

class AuthorizationHandler:
    def __init__(self, model_path=None, policy_path=None):
        self.enforcer = casbin.Enforcer(model_path, policy_path)
    
    def verify_authorization(self, username, parameter_name, action):
        return self.enforcer.enforce(username, parameter_name, action)

    def check_permission(self, username):
        _userroles = self.enforcer.get_roles_for_user(username)
        _logger.error("User roles: %s", _userroles)
        #return self.enforcer.get_roles_for_user(username)
        return _userroles
    
    def check_admin_role(self, username):
        if "Admin" in self.enforcer.get_roles_for_user(username):
            return True
        return False
        #return self.enforcer.get_roles_for_user(username)

    def get_all_admins(self):
        return self.enforcer.get_users_for_role("Admin")

    def add_role_for_user(self, user, role):
        return self.enforcer.add_role_for_user(user, role)
    
    def remove_role_for_user(self, user, role):
        return self.enforcer.delete_role_for_user(user, role)
    
    def remove_user(self, user):
        return self.enforcer.delete_user(user)
    
    def check_user_exists(self, user):
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