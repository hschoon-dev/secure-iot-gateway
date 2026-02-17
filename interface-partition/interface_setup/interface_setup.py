"""
------------------------------------------------------------
 Modul:    interface-partition/interface_setup.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    This module contains the interface setup for the Interface
    Partition. It includes the DataManager class that handles
    the interaction between an OPC UA server and shared memory.
    It creates the OPC UA methods for request submission and
    user management, and sets up the OPC UA server with security
    policies and certificate validation.

 Autor(en):
    - Heiko Schoon

 Maintainer:
    - Heiko Schoon <heiko.schoon@hs-emden-leer.de>

 Hinweis:
    Ongoing development.
------------------------------------------------------------
"""

import logging
import sys
import math

from asyncua import Server, ua
from pathlib import Path
from asyncua.crypto.permission_rules import SimpleRoleRuleset
from asyncua.server.user_managers import CertificateUserManager
from asyncua.crypto.validator import CertificateValidator, CertificateValidatorOptions
from asyncua.crypto.truststore import TrustStore
from asyncua.common.connection import TransportLimits

# Local imports
from .server_methods import (
    submit_request, add_user, remove_user, update_user_secret,
    check_user_exists, list_users, set_user_role, get_user_details
)

sys.path.insert(0, "..")
_logger = logging.getLogger(__name__)

cert_base =             Path(__file__).parent.parent
server_cert =           Path(cert_base / "certificates/python-server/interface_server_cert.der")
server_private_key =    Path(cert_base / "certificates/python-server/interface_server_key.pem")
client_cert =           Path(cert_base / "certificates/trusted/certs/mo_client_cert.der")
ua_expert_cert =        Path(cert_base / "certificates/trusted/certs/uaexpert.der")
ua_expert_cert_omag =   Path(cert_base / "certificates/trusted/certs/uaexpert_OMAG.der")

# TODO: Remove Admin Password from this comment: Admin123_secure_password_2025

async def add_user_manager_methods(server: Server) -> None:
    """
    Add user management OPC UA methods to the server
    """
    try:
        # Get objects and namespaces
        _idx = await server.get_namespace_index("idx.request-handler.ua")
        _obj = await server.nodes.objects.add_object(_idx, "UserManager")        
        
        # Add basic user management methods
        method = await _obj.add_method(_idx, "add_user", add_user, [
            ua.Argument("AdminID", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Admin Identifier")),
            ua.Argument("Admin Secret", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Admin Secret")),
            ua.Argument("UserID", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("User Identifier")),
            ua.Argument("User Secret", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("User Secret"))], 
            [
                ua.Argument("StatusCode", ua.NodeId(ua.ObjectIds.StatusCode), -1, [], ua.LocalizedText("Status Code")),
                ua.Argument("Response", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Response"))
            ])
        
        method = await _obj.add_method(_idx, "remove_user", remove_user, [
            ua.Argument("AdminID", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Admin Identifier")),
            ua.Argument("AdminSecret", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Admin Secret")),
            ua.Argument("UserID", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("User Identifier"))],
            [
                ua.Argument("StatusCode", ua.NodeId(ua.ObjectIds.StatusCode), -1, [], ua.LocalizedText("Status Code")),
                ua.Argument("Response", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Response"))
            ])
        
        method = await _obj.add_method(_idx, "update_user_secret", update_user_secret, [
            ua.Argument("UserID", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("User Identifier")),
            ua.Argument("Secret", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Current Secret")),
            ua.Argument("NewSecret", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("New Secret"))],
            [
                ua.Argument("StatusCode", ua.NodeId(ua.ObjectIds.StatusCode), -1, [], ua.LocalizedText("Status Code")),
                ua.Argument("Response", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Response"))
            ])
        
        # Add additional user management methods
        method = await _obj.add_method(_idx, "check_user_exists", check_user_exists, [
            ua.Argument("UserID", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("User Identifier"))],
            [
                ua.Argument("StatusCode", ua.NodeId(ua.ObjectIds.StatusCode), -1, [], ua.LocalizedText("Status Code")),
                ua.Argument("Exists", ua.NodeId(ua.ObjectIds.Boolean), -1, [], ua.LocalizedText("User Exists")),
                ua.Argument("Response", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Response"))
            ])
        
        method = await _obj.add_method(_idx, "list_users", list_users, [
            ua.Argument("AdminID", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Admin Identifier")),
            ua.Argument("AdminSecret", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Admin Secret"))],
            [
                ua.Argument("StatusCode", ua.NodeId(ua.ObjectIds.StatusCode), -1, [], ua.LocalizedText("Status Code")),
                ua.Argument("Users", ua.NodeId(ua.ObjectIds.String), 1, [0], ua.LocalizedText("User List")),
                ua.Argument("Response", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Response"))
            ])
        
        method = await _obj.add_method(_idx, "set_user_role", set_user_role, [
            ua.Argument("AdminID", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Admin Identifier")),
            ua.Argument("AdminSecret", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Admin Secret")),
            ua.Argument("UserID", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("User Identifier")),
            ua.Argument("Role", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Role Name"))],
            [
                ua.Argument("StatusCode", ua.NodeId(ua.ObjectIds.StatusCode), -1, [], ua.LocalizedText("Status Code")),
                ua.Argument("Response", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Response"))
            ])
        
        method = await _obj.add_method(_idx, "get_user_details", get_user_details, [
            ua.Argument("AdminID", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Admin Identifier")),
            ua.Argument("AdminSecret", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Admin Secret")),
            ua.Argument("UserID", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("User Identifier"))],
            [
                ua.Argument("StatusCode", ua.NodeId(ua.ObjectIds.StatusCode), -1, [], ua.LocalizedText("Status Code")),
                ua.Argument("Details", ua.NodeId(ua.ObjectIds.String), 1, [0], ua.LocalizedText("User Details")),
                ua.Argument("Response", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Response"))
            ])
    except Exception as e:
        _logger.error(f"Error adding user management methods: {e}")

#async def setup_opcua_server(vor_parameters: list[str]) -> Server:
async def setup_opcua_server() -> Server:
    """
    Sets up and starts the OPC UA server.

    This function initializes the OPC UA server, sets up security policies, loads certificates,
    and registers the necessary namespaces and methods.

    Args:
        vor_parameters (list[str]): List of VoR parameters to be added to the server.

    Returns:
        Server: The initialized OPC UA server instance.
    """

    cert_user_manager = CertificateUserManager()
    #await cert_user_manager.add_admin(client_cert, name='PythonClient')
    await cert_user_manager.add_user(client_cert, name='Python-M+O-Client')
    await cert_user_manager.add_user(ua_expert_cert, name='UA-Expert-Client')
    await cert_user_manager.add_user(ua_expert_cert_omag, name='UA-Expert-Client-OMAG')

    buffer_sz = 16 * 1024            # 16 KB
    max_msg_sz = 10 * 1024           # 10 KB

    server = Server(user_manager=cert_user_manager)
    await server.init()

    #server.limits.max_recv_buffer = buffer_sz
    #server.limits.max_send_buffer = buffer_sz
    #server.limits.max_message_size = max_msg_sz

    server_app_uri =   f"urn:freeopcua:interface_server" #TODO: this value MUST match the configured certificate subjectAltName!
    await server.set_application_uri(server_app_uri)
    server.set_endpoint("opc.tcp://0.0.0.0:4840/freeopcua/server/")

    server.limits = TransportLimits(
        max_recv_buffer=buffer_sz,
        max_send_buffer=buffer_sz,
        # how many chunks we allow per message (round up)
        max_chunk_count=math.ceil(max_msg_sz / buffer_sz),
        max_message_size=max_msg_sz,
    )

    server.set_security_policy([ua.SecurityPolicyType.Aes256Sha256RsaPss_SignAndEncrypt],
                            permission_ruleset=SimpleRoleRuleset())

    # load server certificate and private key. This enables endpoints with signing and encryption.
    await server.load_certificate(str(server_cert))
    await server.load_private_key(str(server_private_key))

    # TRUSTSTORE
    trust_store = TrustStore([Path(cert_base / "certificates/trusted/certs")], [])
    await trust_store.load()
    validator = CertificateValidator(options=CertificateValidatorOptions.TRUSTED_VALIDATION | CertificateValidatorOptions.PEER_CLIENT, trust_store = trust_store)
    server.set_certificate_validator(validator)

    uri = "idx.request-handler.ua"
    #app_uri = f"mo-opcua-server"
    idx = await server.register_namespace(uri)
    obj = await server.nodes.objects.add_object(idx, "RequestHandler")


    # Define input arguments
    # issuer_id: str, credentials: str, timestamp: str, description: list, impact: list, parameters: list, modification: str,  priority: int):
    args: list[tuple[str, ua.ObjectIds, int, list, str]] = [
        ("IssuerID",                ua.ObjectIds.String,    -1, [],     "Unique identifier of the request issuer"),
        ("Credentials",             ua.ObjectIds.String,    -1, [],     "Credentials of the request issuer"),
        ("Issuer characteristics",  ua.ObjectIds.String,     1, [0],    "Origin tags of the request"),       # IP address, container instance, model identifier, etc.
        ("Timestamp",               ua.ObjectIds.DateTime,  -1, [],     "Timestamp of Request"),
        ("Description",             ua.ObjectIds.String,     1, [0],    "Description of Request"),
        ("Impact",                  ua.ObjectIds.String,    -1, [],     "Impact of Request"),
        ("Parameters",              ua.ObjectIds.String,    -1, [],     "Parameters affected by the Request"),
        ("Modification",            ua.ObjectIds.String,    -1, [],     "Requested Modification"),
        ("Priority",                ua.ObjectIds.Int32,     -1, [],     "Priority"),
    ]

    input_args: list[ua.Argument] = []
    for name, data_type, value_rank, array_dims, desc in args:
        arg: ua.Argument = ua.Argument()
        arg.Name = name
        arg.DataType = ua.NodeId(data_type)
        arg.ValueRank = value_rank
        arg.ArrayDimensions = array_dims
        arg.Description = ua.LocalizedText(desc)
        input_args.append(arg)

    # Define output arguments
    output_args: list[tuple[str, ua.ObjectIds, int, list, str]] = [
        ("RequestID", ua.ObjectIds.String, -1, [], "Unique request Identifier"),
        ("Timestamp", ua.ObjectIds.String, -1, [], "VoR Timestamp"),
        ("Notification", ua.ObjectIds.String, -1, [], "Notification of submission"),
    ]
    out_args: list[ua.Argument] = []
    for name, data_type, value_rank, array_dims, desc in output_args:
        arg: ua.Argument = ua.Argument()
        arg.Name = name
        arg.DataType = ua.NodeId(data_type)
        arg.ValueRank = value_rank
        arg.ArrayDimensions = array_dims
        arg.Description = ua.LocalizedText(desc)
        out_args.append(arg)

    method = await obj.add_method(idx, "request", submit_request, input_args, out_args)

    await add_user_manager_methods(server)

    _logger.info("Starting OPC UA server...")
    return server