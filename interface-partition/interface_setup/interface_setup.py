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
from asyncua import uamethod
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
from config_loader import OpcUaServerConfig, GrpcClientConfig  # only sub-model needed

sys.path.insert(0, "..")
_logger = logging.getLogger(__name__)


async def add_user_manager_methods(server: Server, namespace_uri: str) -> None:
    """
    Add user management OPC UA methods to the server.

    Args:
        server:        The running asyncua Server instance.
        namespace_uri: Namespace URI, taken from OpcUaServerConfig.namespace_uri.
    """
    try:
        _idx = await server.get_namespace_index(namespace_uri)
        _obj = await server.nodes.objects.add_object(_idx, "UserManager")

        await _obj.add_method(_idx, "add_user", add_user, [
            ua.Argument("AdminID",      ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Admin Identifier")),
            ua.Argument("Admin Secret", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Admin Secret")),
            ua.Argument("UserID",       ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("User Identifier")),
            ua.Argument("User Secret",  ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("User Secret")),
        ], [
            ua.Argument("StatusCode", ua.NodeId(ua.ObjectIds.StatusCode), -1, [], ua.LocalizedText("Status Code")),
            ua.Argument("Response",   ua.NodeId(ua.ObjectIds.String),     -1, [], ua.LocalizedText("Response")),
        ])

        await _obj.add_method(_idx, "remove_user", remove_user, [
            ua.Argument("AdminID",     ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Admin Identifier")),
            ua.Argument("AdminSecret", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Admin Secret")),
            ua.Argument("UserID",      ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("User Identifier")),
        ], [
            ua.Argument("StatusCode", ua.NodeId(ua.ObjectIds.StatusCode), -1, [], ua.LocalizedText("Status Code")),
            ua.Argument("Response",   ua.NodeId(ua.ObjectIds.String),     -1, [], ua.LocalizedText("Response")),
        ])

        await _obj.add_method(_idx, "update_user_secret", update_user_secret, [
            ua.Argument("UserID",    ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("User Identifier")),
            ua.Argument("Secret",    ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Current Secret")),
            ua.Argument("NewSecret", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("New Secret")),
        ], [
            ua.Argument("StatusCode", ua.NodeId(ua.ObjectIds.StatusCode), -1, [], ua.LocalizedText("Status Code")),
            ua.Argument("Response",   ua.NodeId(ua.ObjectIds.String),     -1, [], ua.LocalizedText("Response")),
        ])

        await _obj.add_method(_idx, "check_user_exists", check_user_exists, [
            ua.Argument("UserID", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("User Identifier")),
        ], [
            ua.Argument("StatusCode", ua.NodeId(ua.ObjectIds.StatusCode), -1, [], ua.LocalizedText("Status Code")),
            ua.Argument("Exists",     ua.NodeId(ua.ObjectIds.Boolean),    -1, [], ua.LocalizedText("User Exists")),
            ua.Argument("Response",   ua.NodeId(ua.ObjectIds.String),     -1, [], ua.LocalizedText("Response")),
        ])

        await _obj.add_method(_idx, "list_users", list_users, [
            ua.Argument("AdminID",     ua.NodeId(ua.ObjectIds.String), -1, [],  ua.LocalizedText("Admin Identifier")),
            ua.Argument("AdminSecret", ua.NodeId(ua.ObjectIds.String), -1, [],  ua.LocalizedText("Admin Secret")),
        ], [
            ua.Argument("StatusCode", ua.NodeId(ua.ObjectIds.StatusCode), -1, [],  ua.LocalizedText("Status Code")),
            ua.Argument("Users",      ua.NodeId(ua.ObjectIds.String),      1, [0], ua.LocalizedText("User List")),
            ua.Argument("Response",   ua.NodeId(ua.ObjectIds.String),     -1, [],  ua.LocalizedText("Response")),
        ])

        await _obj.add_method(_idx, "set_user_role", set_user_role, [
            ua.Argument("AdminID",     ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Admin Identifier")),
            ua.Argument("AdminSecret", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Admin Secret")),
            ua.Argument("UserID",      ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("User Identifier")),
            ua.Argument("Role",        ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Role Name")),
        ], [
            ua.Argument("StatusCode", ua.NodeId(ua.ObjectIds.StatusCode), -1, [], ua.LocalizedText("Status Code")),
            ua.Argument("Response",   ua.NodeId(ua.ObjectIds.String),     -1, [], ua.LocalizedText("Response")),
        ])

        await _obj.add_method(_idx, "get_user_details", get_user_details, [
            ua.Argument("AdminID",     ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Admin Identifier")),
            ua.Argument("AdminSecret", ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("Admin Secret")),
            ua.Argument("UserID",      ua.NodeId(ua.ObjectIds.String), -1, [], ua.LocalizedText("User Identifier")),
        ], [
            ua.Argument("StatusCode", ua.NodeId(ua.ObjectIds.StatusCode), -1, [],  ua.LocalizedText("Status Code")),
            ua.Argument("Details",    ua.NodeId(ua.ObjectIds.String),      1, [0], ua.LocalizedText("User Details")),
            ua.Argument("Response",   ua.NodeId(ua.ObjectIds.String),     -1, [],  ua.LocalizedText("Response")),
        ])

    except Exception as e:
        _logger.error(f"Error adding user management methods: {e}")


async def setup_opcua_server(config: OpcUaServerConfig, grpc_client: GrpcClientConfig) -> Server:
    """
    Sets up and starts the OPC UA server.

    This function initializes the OPC UA server, sets up security policies,
    loads certificates, and registers the necessary namespaces and methods.

    Args:
        config: OpcUaServerConfig sub-model from InterfaceConfig.

    Returns:
        Server: The initialized OPC UA server instance.
    """

    # Wrap submit_request to inject grpc_client
    @uamethod
    async def _submit_request(parent, issuer_id, credentials, issuer_characteristics,
                            timestamp, description, impact, parameters,
                            modification, priority):
        return await submit_request(
            parent, issuer_id, credentials, issuer_characteristics,
            timestamp, description, impact, parameters,
            modification, priority,
            grpc_config=grpc_client,   # injected from outer scope
        )

    certs = config.certs

    cert_user_manager = CertificateUserManager()
    await cert_user_manager.add_user(Path(certs.trusted_certs_dir) / "mo_client_cert.der",    name="Python-M+O-Client")
    await cert_user_manager.add_user(Path(certs.trusted_certs_dir) / "uaexpert.der",          name="UA-Expert-Client")
    await cert_user_manager.add_user(Path(certs.trusted_certs_dir) / "uaexpert_OMAG.der",     name="UA-Expert-Client-OMAG")

    limits = config.transport_limits
    buffer_sz = limits.recv_buffer_bytes
    max_msg_sz = limits.max_message_bytes

    server = Server(user_manager=cert_user_manager)
    await server.init()

    await server.set_application_uri(config.application_uri)
    server.set_endpoint(config.endpoint)

    server.limits = TransportLimits(
        max_recv_buffer=buffer_sz,
        max_send_buffer=limits.send_buffer_bytes,
        max_chunk_count=math.ceil(max_msg_sz / buffer_sz),
        max_message_size=max_msg_sz,
    )

    server.set_security_policy(
        [ua.SecurityPolicyType.Aes256Sha256RsaPss_SignAndEncrypt],
        permission_ruleset=SimpleRoleRuleset(),
    )

    # Load server certificate and private key
    await server.load_certificate(str(certs.server_cert))
    await server.load_private_key(str(certs.server_key))

    # Truststore
    trust_store = TrustStore([Path(certs.trusted_certs_dir)], [])
    await trust_store.load()
    validator = CertificateValidator(
        options=CertificateValidatorOptions.TRUSTED_VALIDATION | CertificateValidatorOptions.PEER_CLIENT,
        trust_store=trust_store,
    )
    server.set_certificate_validator(validator)

    idx = await server.register_namespace(config.namespace_uri)
    obj = await server.nodes.objects.add_object(idx, "RequestHandler")

    # Define input arguments
    args: list[tuple[str, ua.ObjectIds, int, list, str]] = [
        ("IssuerID",               ua.ObjectIds.String,   -1, [],  "Unique identifier of the request issuer"),
        ("Credentials",            ua.ObjectIds.String,   -1, [],  "Credentials of the request issuer"),
        ("Issuer characteristics", ua.ObjectIds.String,    1, [0], "Origin tags of the request"),
        ("Timestamp",              ua.ObjectIds.DateTime, -1, [],  "Timestamp of Request"),
        ("Description",            ua.ObjectIds.String,    1, [0], "Description of Request"),
        ("Impact",                 ua.ObjectIds.String,   -1, [],  "Impact of Request"),
        ("Parameters",             ua.ObjectIds.String,   -1, [],  "Parameters affected by the Request"),
        ("Modification",           ua.ObjectIds.String,   -1, [],  "Requested Modification"),
        ("Priority",               ua.ObjectIds.Int32,    -1, [],  "Priority"),
    ]

    input_args: list[ua.Argument] = []
    for name, data_type, value_rank, array_dims, desc in args:
        arg = ua.Argument()
        arg.Name = name
        arg.DataType = ua.NodeId(data_type)
        arg.ValueRank = value_rank
        arg.ArrayDimensions = array_dims
        arg.Description = ua.LocalizedText(desc)
        input_args.append(arg)

    output_args: list[tuple[str, ua.ObjectIds, int, list, str]] = [
        ("RequestID",    ua.ObjectIds.String, -1, [], "Unique request Identifier"),
        ("Timestamp",    ua.ObjectIds.String, -1, [], "VoR Timestamp"),
        ("Notification", ua.ObjectIds.String, -1, [], "Notification of submission"),
    ]
    out_args: list[ua.Argument] = []
    for name, data_type, value_rank, array_dims, desc in output_args:
        arg = ua.Argument()
        arg.Name = name
        arg.DataType = ua.NodeId(data_type)
        arg.ValueRank = value_rank
        arg.ArrayDimensions = array_dims
        arg.Description = ua.LocalizedText(desc)
        out_args.append(arg)

    await obj.add_method(idx, "request", _submit_request, input_args, out_args)

    await add_user_manager_methods(server, config.namespace_uri)

    _logger.info("Starting OPC UA server...")
    return server