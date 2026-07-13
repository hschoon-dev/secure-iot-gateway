"""
------------------------------------------------------------
 Modul:    interface-partition/server_methods.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    This module sets up the OPC UA methods for request 
    submission and user management. It includes methods
    for submitting requests, adding/removing users, updating
    user secrets, checking user existence, listing users,
    setting user roles, and getting user details.
    The POSIX message queue is used for inter-process
    communication with the intermediate VoR partition.

 Autor(en):
    - Heiko Schoon

 Maintainer:
    - Heiko Schoon <heiko.schoon@hs-emden-leer.de>

 Hinweis:
    Ongoing development.
------------------------------------------------------------
"""

import datetime
import uuid
import logging
import os
import re
import json
import ssl
import urllib.error
import urllib.request
from asyncua import uamethod
from asyncua.ua import StatusCode, StatusCodes
from typing import Any

from user_manager import UserManagerTinyDB
from authorization_handler import (
    AuthorizationHandler,
    build_opa_ssl_context,
    opa_fail_open_allowed,
    opa_transport_allowed,
    parse_numeric_value,
)
from grpc_request_handler import send_request_as_grpc

_logger = logging.getLogger(__name__)

path = os.path.dirname(os.path.abspath(__file__))
parent_path = os.path.dirname(path)
#credentials_db_path = os.path.join(parent_path, "user_manager/credentials.db")
_credentials_runtime = os.getenv(
    "SIOT_CREDENTIALS_DB", "/var/lib/siot/credentials.json"
)
_credentials_fallback = os.path.join(parent_path, "user_manager", "credentials.json")
_allow_legacy_credentials = os.getenv(
    "ALLOW_LEGACY_CREDENTIALS", "false"
).strip().lower() in ("1", "true", "yes", "on")

if os.path.isfile(_credentials_runtime):
    credentials_db_path = _credentials_runtime
elif _allow_legacy_credentials and os.path.isfile(_credentials_fallback):
    _logger.warning(
        "Using legacy credential database because ALLOW_LEGACY_CREDENTIALS=true"
    )
    credentials_db_path = _credentials_fallback
else:
    raise RuntimeError(
        f"Credential database not found at {_credentials_runtime}. "
        "Run secret_migration.sh before startup; legacy fallback is disabled."
    )
_user_manager = UserManagerTinyDB(credentials_db_path, max_connections=10)

"""try:
    if not os.getenv("ADMIN_PASSWORD"):
        raise ValueError("ADMIN_PASSWORD environment variable is not set.")
    _create_init_admin = _user_manager.create_user(username="admin", password=os.getenv("ADMIN_PASSWORD"))
except Exception as e:
    _logger.error(f"Error creating initial Admin user: {e}")"""

from pathlib import Path
path = Path(__file__).resolve().parent
parent_path = path.parent
casbin_model_path_res = Path(parent_path / "authorization_handler" / "rbac_with_resource_roles_model.conf")
casbin_policy_path_res = Path(parent_path / "authorization_handler" / "rbac_policy.csv")


# Log resolved Casbin paths for debugging
_logger.debug(f"Casbin model path: {casbin_model_path_res}")
_logger.debug(f"Casbin policy path: {casbin_policy_path_res}")
_rbac_authorization_handler = AuthorizationHandler(str(casbin_model_path_res), str(casbin_policy_path_res))
_DEFAULT_NEW_USER_ROLE = os.getenv("DEFAULT_NEW_USER_ROLE", "PlantOperator")

_AUTHZ_MODE = os.getenv("AUTHZ_MODE", "casbin").strip().lower()
_OPA_URL = os.getenv("OPA_URL", "http://opa:8181/v1/data/siot/authz/allow")
_OPA_FAIL_OPEN_REQUESTED = os.getenv("OPA_FAIL_OPEN", "false").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
_OPA_TIMEOUT_SECONDS = float(os.getenv("OPA_TIMEOUT_SECONDS", "0.75"))
_OPA_PUMP_B_POWER_MAX_KW = float(os.getenv("OPA_PUMP_B_POWER_MAX_KW", "16"))
_OPA_TLS_CA_CERT = os.getenv("OPA_TLS_CA_CERT", "")
_OPA_TLS_CLIENT_CERT = os.getenv("OPA_TLS_CLIENT_CERT", "")
_OPA_TLS_CLIENT_KEY = os.getenv("OPA_TLS_CLIENT_KEY", "")
_DEPLOYMENT_MODE = os.getenv("SIOT_DEPLOYMENT_MODE", "production")
_OPA_FAIL_OPEN = opa_fail_open_allowed(_OPA_FAIL_OPEN_REQUESTED, _DEPLOYMENT_MODE)
if _OPA_FAIL_OPEN_REQUESTED and not _OPA_FAIL_OPEN:
    _logger.warning(
        "Ignoring OPA_FAIL_OPEN outside the explicitly labelled test deployment"
    )


def _resolve_authz_mode() -> str:
    if _AUTHZ_MODE in ("casbin", "casbin_and_opa", "opa_only"):
        return _AUTHZ_MODE
    _logger.warning("Unknown AUTHZ_MODE '%s'. Falling back to 'casbin'.", _AUTHZ_MODE)
    return "casbin"


def _authorize_with_opa(
    issuer_id: str,
    impact: str,
    parameters: str,
    value: float,
    priority: int,
    timestamp: str,
) -> tuple[bool, str]:
    transport_allowed, transport_message = opa_transport_allowed(
        _OPA_URL, _DEPLOYMENT_MODE
    )
    if not transport_allowed:
        _logger.error("OPA authorization denied: %s", transport_message)
        return False, transport_message

    roles = _rbac_authorization_handler.get_roles_for_user(issuer_id)
    input_payload = {
        "user": {
            "id": issuer_id,
            "roles": roles,
        },
        "action": impact,
        "parameter": parameters,
        "value": value,
        "limits": {
            "pump_b_power_max_kw": _OPA_PUMP_B_POWER_MAX_KW,
        },
        "request": {
            # asyncua supplies DateTime method arguments as ``datetime``
            # instances although the public method annotation says ``str``.
            # Keep the OPA wire format deterministic and JSON serializable.
            "timestamp": str(timestamp),
            "priority": priority,
        },
    }
    request_body = json.dumps({"input": input_payload}).encode("utf-8")
    request = urllib.request.Request(
        _OPA_URL,
        data=request_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        tls_context = build_opa_ssl_context(
            _OPA_URL,
            _DEPLOYMENT_MODE,
            _OPA_TLS_CA_CERT,
            _OPA_TLS_CLIENT_CERT,
            _OPA_TLS_CLIENT_KEY,
        )
        open_kwargs = {"timeout": _OPA_TIMEOUT_SECONDS}
        if tls_context is not None:
            open_kwargs["context"] = tls_context
        with urllib.request.urlopen(request, **open_kwargs) as response:
            raw_body = response.read().decode("utf-8")
        parsed = json.loads(raw_body) if raw_body else {}
        result = parsed.get("result")

        if isinstance(result, bool):
            return result, "OPA response bool"
        if isinstance(result, dict) and isinstance(result.get("allow"), bool):
            return result["allow"], "OPA response object.allow"

        message = f"Malformed OPA response: {parsed}"
        if _OPA_FAIL_OPEN:
            _logger.warning("%s (OPA_FAIL_OPEN=true)", message)
            return True, message
        _logger.error(message)
        return False, message
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, ssl.SSLError) as exc:
        message = f"OPA authorization request failed: {exc}"
        if _OPA_FAIL_OPEN:
            _logger.warning("%s (OPA_FAIL_OPEN=true)", message)
            return True, message
        _logger.error(message)
        return False, message

#@uamethod  #TODO: test...
# TODO: Update method parameters according the project/NOA-standard requirements and yuanchens additional developments
# TODO: Implement additional UserManagement 
#def submit_request(parent: Any, issuer_id: str, credentials: str, issuer_characteristics: list[str], timestamp: str, 
#                  #description: list[str], impact: list[str], parameters: str,
#                  description: list[str], impact: str, parameters: str,
#                  modification: str, priority: int) -> tuple[str, str, str]:
async def submit_request(
    parent,
    issuer_id: str,
    credentials: str,
    issuer_characteristics: list[str],
    timestamp: str,
    description: list[str],
    impact: str,
    parameters: str,
    modification: str,
    priority: int,
    *,
    grpc_config,
) -> tuple[str, str, str]:
    """
    OPC UA method to handle a request submission.

    Args:
        parent: The parent node in the OPC UA server.
        issuer_id: The unique identifier of the request issuer.
        credentials: The credentials of the request issuer.
        timestamp: The timestamp of the request.
        description: Human readable description of the request.
        impact: Impacts and benefits of the request.
        parameters: Parameters affected by the request.
        modification: Machine readable description of the requested changes.
        priority: The priority of the request.

    Returns:
        tuple: A tuple containing the request ID, server timestamp, and a notification message.
    """
    request_id = str(uuid.uuid4())
    server_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Format Request using JSON
    request_dict = {
        "issuer_id": issuer_id,
        #"credentials": Credentials are being removed before sending the request to the VoR partition for security reasons
        "issuer_characteristics": {},
        "timestamp": str(timestamp),
        "description": {},
        "impact": impact,
        "parameters": parameters,
        "modification": modification,
        "prio": priority,
        "request_id": request_id
    }
    # list.index() returns the position of the FIRST occurrence, so duplicate
    # non-empty strings would map to the same key and silently overwrite each
    # other. enumerate() always uses the iteration position, which is unique.
    for idx, i in enumerate(issuer_characteristics):
        if i:
            request_dict["issuer_characteristics"][f"issuer_characteristics_{idx}"] = i

    for idx, descr in enumerate(description):
        if descr:
            request_dict["description"][f"description_{idx}"] = descr
    _logger.info(f"Request: {request_dict}")

    # 0) Validate and normalise the modification field.
    #    Strip outer parentheses that some clients send, e.g. "(5)" -> "5".
    if isinstance(modification, str) and modification.startswith("(") and modification.endswith(")"):
        modification = modification[1:-1]
    #    Normalise Python/OPC UA boolean variants to lowercase strings.
    if isinstance(modification, bool):
        modification = str(modification).lower()
    elif isinstance(modification, str) and modification.lower() in ("true", "false"):
        modification = modification.lower()
    #    Reject anything that is not a number (optionally with %), a percentage, or a boolean.
    _mod_pattern = r"^(?:-?\d+(?:\.\d+)?%?|true|false)$"
    if not re.fullmatch(_mod_pattern, str(modification)):
        _logger.warning(f"Invalid modification value from {issuer_id}: {modification!r}")
        return request_id, server_timestamp, "Invalid input for modification."
    #    Store the normalised value in the request dict.
    request_dict["modification"] = modification

    # 1) Authenticate the request issuer
    if not _user_manager.verify_credentials(username=issuer_id, password=credentials):
        _logger.error(f"Authentication failed for {issuer_id}")
        return request_id, server_timestamp, f"Authentication failed for {issuer_id}"

    # 2) Authorize the request issuer
    # TODO: Create first a list of parameters and actions to be authorized .csv file and .conf file
    # TODO: Create documentation of parameters/actions, users/credentials, roles, and policies (initial users/credentials e.g., Admin etc.)
    authz_mode = _resolve_authz_mode()

    if authz_mode in ("casbin", "casbin_and_opa"):
        if not _rbac_authorization_handler.verify_authorization(
            issuer_id,
            parameter_name=parameters,
            action=f'"{impact}"',
        ):
            _logger.error(
                "Casbin authorization failed for %s with parameters %s and action %s",
                issuer_id,
                parameters,
                impact,
            )
            return request_id, server_timestamp, f"Request authorization failed (casbin): {issuer_id}"

    if authz_mode in ("opa_only", "casbin_and_opa"):
        try:
            opa_value = parse_numeric_value(modification)
        except ValueError as exc:
            _logger.error(
                "OPA input validation failed for %s: %s", issuer_id, exc
            )
            return request_id, server_timestamp, (
                f"Request authorization failed (invalid modification): {issuer_id}"
            )

        opa_allowed, opa_reason = _authorize_with_opa(
            issuer_id=issuer_id,
            impact=impact,
            parameters=parameters,
            value=opa_value,
            priority=priority,
            timestamp=timestamp,
        )
        if not opa_allowed:
            _logger.error(
                "OPA authorization failed for %s with parameters %s and action %s (%s)",
                issuer_id,
                parameters,
                impact,
                opa_reason,
            )
            return request_id, server_timestamp, f"Request authorization failed (opa): {issuer_id}"
    
    # 3) Submit the request to the intermediate VoR partition
    # Setup POSIX message queue for ipc with the intermediate VoR partition
    try:
        #send_request_as_grpc(request=request_dict)
        send_request_as_grpc(request=request_dict, config=grpc_config)
        _logger.info(f"Request with priority {priority} at {server_timestamp} received and forwared.")
    except Exception as e:
        _logger.error(f"Error submit request method: {e}")
        return request_id, server_timestamp, f"Error: {str(e)}"

    return request_id, server_timestamp, f"Submission received"

@uamethod
def add_user(parent: Any, admin_id: str, admin_secret: str, 
             user_id: str, secret: str) -> tuple[StatusCode, str]: 
    """
    Add a new user to the system.
    
    Args:
        parent: The parent node in the OPC UA server.
        admin_id: Administrator identifier.
        admin_secret: Administrator credentials.
        user_id: New user identifier.
        secret: Password for the new user.
        
    Returns:
        tuple: Status code and result message.
    """
    if not _user_manager.verify_credentials(username=admin_id, password=admin_secret):
        return StatusCode(StatusCodes.BadUserAccessDenied), f"Authentication failed for admin {admin_id}."
    if not _rbac_authorization_handler.check_admin_role(admin_id):
        return StatusCode(StatusCodes.BadUserAccessDenied), f"Admin role required for adding users."
    try:
        if _user_manager.user_exists(user_id):
            return StatusCode(StatusCodes.BadUnexpectedError), f"User {user_id} already exists in user manager."

        if not _rbac_authorization_handler.role_exists(_DEFAULT_NEW_USER_ROLE):
            return StatusCode(StatusCodes.BadNoMatch), (
                f"Default role '{_DEFAULT_NEW_USER_ROLE}' does not exist in RBAC policy."
            )

        created = _user_manager.create_user(username=user_id, password=secret)
        if not created:
            return StatusCode(StatusCodes.BadUnexpectedError), f"Failed to add user {user_id} to user manager."

        success, message = _rbac_authorization_handler.set_single_role_for_user(
            user=user_id,
            role=_DEFAULT_NEW_USER_ROLE,
        )
        if not success:
            # Roll back user-manager insert to keep both stores consistent.
            res, user_record = _user_manager.retrieve_user(user_id)
            if res and user_record is not None:
                _user_manager.delete_user(user_record[0])
            return StatusCode(StatusCodes.BadUnexpectedError), (
                f"RBAC role assignment failed for {user_id}. Rolled back user creation. Details: {message}"
            )

        return StatusCode(StatusCodes.Good), (
            f"User {user_id} added successfully with role '{_DEFAULT_NEW_USER_ROLE}'."
        )
    except Exception as e:
        _logger.error(f"Error adding user: {e}")
        return StatusCode(StatusCodes.BadInternalError), f"Error: {str(e)}"

@uamethod
def remove_user(parent: Any, admin_id: str, admin_secret: str, 
                user_id: str) -> tuple[StatusCode, str]:
    """
    Remove a user from the system.
    
    Args:
        parent: The parent node in the OPC UA server.
        admin_id: Administrator identifier.
        admin_secret: Administrator credentials.
        user_id: User to remove.
        
    Returns:
        tuple: Status code and result message.
    """
    try:
        if not _user_manager.verify_credentials(username=admin_id, password=admin_secret):
            return StatusCode(StatusCodes.BadUserAccessDenied), f"Authentication failed for admin {admin_id}."
        if not _rbac_authorization_handler.check_admin_role(admin_id):
            return StatusCode(StatusCodes.BadUserAccessDenied), f"Admin role required for user deletion."
        
        user_roles = _rbac_authorization_handler.get_roles_for_user(user_id)

        # Check if user is last admin and prevent deletion.
        if len(_rbac_authorization_handler.get_all_admins()) == 1 and "Admin" in user_roles:
            return StatusCode(StatusCodes.BadUserAccessDenied), f"Cannot delete last admin user."

        # Get user record from user-manager first.
        res, user_record = _user_manager.retrieve_user(user_id)
        if not res or user_record is None:
            return StatusCode(StatusCodes.BadNoMatch), f"User {user_id} not found."

        # Phase 1: remove RBAC assignments (if present), persist immediately.
        # We keep a snapshot for rollback if user-manager deletion fails.
        rbac_had_roles = len(user_roles) > 0
        if rbac_had_roles:
            if not _rbac_authorization_handler.remove_user(user_id):
                return StatusCode(StatusCodes.BadUnexpectedError), (
                    f"Failed to remove RBAC assignments for user {user_id}."
                )

        # Phase 2: remove from user-manager.
        user_db_id = user_record[0]
        deleted = _user_manager.delete_user(user_db_id)
        if deleted:
            return StatusCode(StatusCodes.Good), f"User {user_id} deleted successfully."

        # Rollback RBAC if user-manager deletion failed.
        if rbac_had_roles:
            for role in user_roles:
                _rbac_authorization_handler.add_role_for_user(user_id, role)
            _rbac_authorization_handler.save_policy()
        return StatusCode(StatusCodes.BadUnexpectedError), (
            f"Failed to delete user {user_id} from user manager. RBAC rollback applied."
        )
    except Exception as e:
        _logger.error(f"Error removing user: {e}")
        return StatusCode(StatusCodes.BadInternalError), f"Error: {str(e)}"

@uamethod
def update_user_secret(parent: Any, user_id: str, secret: str, 
                      new_secret: str) -> tuple[StatusCode, str]:
    """
    Update a user's password.
    
    Args:
        parent: The parent node in the OPC UA server.
        user_id: User identifier.
        secret: Current password.
        new_secret: New password.
        
    Returns:
        tuple: Status code and result message.
    """
    try:
        if not _user_manager.verify_credentials(username=user_id, password=secret):
            return StatusCode(StatusCodes.BadUserAccessDenied), f"Authentication failed for user {user_id}."
        
        res = _user_manager.update_user(username=user_id, old_password=secret, new_password=new_secret)
        if res:
            return StatusCode(StatusCodes.Good), f"User {user_id} secret updated successfully."
        else:
            return StatusCode(StatusCodes.BadUnexpectedError), f"Failed to update secret for user {user_id}."
    except Exception as e:
        _logger.error(f"Error updating user secret: {e}")
        return StatusCode(StatusCodes.BadInternalError), f"Error: {str(e)}"

@uamethod
def check_user_exists(parent: Any, user_id: str) -> tuple[StatusCode, bool, str]:
    """
    Check if a user exists in the system.
    
    Args:
        parent: The parent node in the OPC UA server.
        user_id: User identifier to check.
        
    Returns:
        tuple: Status code, existence flag, and result message.
    """
    try:
        res, user_record = _user_manager.retrieve_user(user_id)
        # If retrieve_user returns success and a record, user exists
        exists = res and user_record is not None
        if exists:
            return StatusCode(StatusCodes.Good), True, f"User {user_id} exists."
        else:
            return StatusCode(StatusCodes.Good), False, f"User {user_id} does not exist."
    except Exception as e:
        _logger.error(f"Error checking user existence: {e}")
        return StatusCode(StatusCodes.BadInternalError), False, f"Error: {str(e)}"
    
@uamethod
def list_users(parent: Any, admin_id: str, admin_secret: str) -> tuple[StatusCode, list[str], str]:
    """
    List all users in the system.
    
    Args:
        parent: The parent node in the OPC UA server.
        admin_id: Administrator identifier.
        admin_secret: Administrator credentials.
        
    Returns:
        tuple: Status code, list of usernames, and result message.
    """
    try:
        if not _user_manager.verify_credentials(username=admin_id, password=admin_secret):
            return StatusCode(StatusCodes.BadUserAccessDenied), [""], f"Authentication failed for admin {admin_id}."
        
        if not _rbac_authorization_handler.check_admin_role(admin_id):
            return StatusCode(StatusCodes.BadUserAccessDenied), [""], f"Admin role required for user listing."

        # UserManagerTinyDB.get_all_users() queries the TinyDB credentials table
        # directly and returns a list[str] of usernames.
        # The old code called _get_connection()/_return_connection() which belonged
        # to a previous SQLite-backed implementation and no longer exists.
        users = _user_manager.get_all_users()
        return StatusCode(StatusCodes.Good), users, f"Successfully retrieved {len(users)} users."
    
    except Exception as e:
        _logger.error(f"Error listing users: {e}")
        return StatusCode(StatusCodes.BadInternalError), [""], f"Error: {str(e)}"
    
@uamethod
def set_user_role(parent: Any, admin_id: str, admin_secret: str, 
                 user_id: str, role: str) -> tuple[StatusCode, str]:
    """
    Set a user's role in the system.
    
    Args:
        parent: The parent node in the OPC UA server.
        admin_id: Administrator identifier.
        admin_secret: Administrator credentials.
        user_id: User to modify.
        role: New role to assign.
        
    Returns:
        tuple: Status code and result message.
    """
    try:
        if not _user_manager.verify_credentials(username=admin_id, password=admin_secret):
            return StatusCode(StatusCodes.BadUserAccessDenied), f"Authentication failed for admin {admin_id}."
        
        if not _rbac_authorization_handler.check_admin_role(admin_id):
            return StatusCode(StatusCodes.BadUserAccessDenied), f"Admin role required for user role management."

        if not _user_manager.user_exists(user_id):
            return StatusCode(StatusCodes.BadNoMatch), f"User {user_id} does not exist in user manager."

        success, message = _rbac_authorization_handler.set_single_role_for_user(user_id, role)
        if success:
            return StatusCode(StatusCodes.Good), message

        if "does not exist" in message:
            return StatusCode(StatusCodes.BadNoMatch), message
        return StatusCode(StatusCodes.BadUnexpectedError), message
    except Exception as e:
        _logger.error(f"Error setting user role: {e}")
        return StatusCode(StatusCodes.BadInternalError), f"Error: {str(e)}"
    
@uamethod
def get_user_details(parent: Any, admin_id: str, admin_secret: str, 
                    user_id: str) -> tuple[StatusCode, list[str], str]:
    """
    Get detailed information about a user.
    
    Args:
        parent: The parent node in the OPC UA server.
        admin_id: Administrator identifier.
        admin_secret: Administrator credentials.
        user_id: User to retrieve details for.
        
    Returns:
        tuple: Status code, list of user details, and result message.
    """
    try:
        if not _user_manager.verify_credentials(username=admin_id, password=admin_secret):
            return StatusCode(StatusCodes.BadUserAccessDenied), [""], f"Authentication failed for admin {admin_id}."
        
        if not _rbac_authorization_handler.check_admin_role(admin_id):
            return StatusCode(StatusCodes.BadUserAccessDenied), [""], f"Admin role required for user detail extraction."
        # TODO: Add user role details from _rbac_authorization_handler
        # Retrieve user details
        res, user_record = _user_manager.retrieve_user(user_id)
        if not res or user_record is None:
            return StatusCode(StatusCodes.BadNoMatch), [""], f"User {user_id} not found."
        
        # Format the user details as strings in a list
        # Format: "field_name:value"
        # Skipping the password hash for security
        details = []
        if user_record:
            fields = ["id", "username", "role", "created_at", "last_login"] 
            # Add available fields from the user record
            details.append(f"id:{user_record[0]}")
            details.append(f"username:{user_record[1]}")
            # Don't include password hash (index 2) or salt (index 3)
            
            # Add any extra fields if they exist in your schema
            # Currently the schema only has id, username, password, salt
            
        return StatusCode(StatusCodes.Good), details, f"Successfully retrieved details for user {user_id}."
    except Exception as e:
        _logger.error(f"Error getting user details: {e}")
        return StatusCode(StatusCodes.BadInternalError), [""], f"Error: {str(e)}"
