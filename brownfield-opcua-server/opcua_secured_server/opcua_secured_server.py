"""
------------------------------------------------------------
 Modul:    brownfield-opcua-server/opcua_secured_server.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    Includes a secured OPC UA server for testing of the
    aggregation component of the Secure IoT Gateway.

 Autor(en):
    - Heiko Schoon

 Maintainer:
    - Heiko Schoon <heiko.schoon@hs-emden-leer.de>

 Hinweis:
    Do not use this code in production. It is for testing
    and demonstration purposes only.
------------------------------------------------------------
"""


import asyncio
import sys
#import argparse
import logging
from pathlib import Path
import random

from asyncua import ua
from asyncua import Server
from asyncua.crypto.permission_rules import SimpleRoleRuleset
from asyncua.server.user_managers import CertificateUserManager
from asyncua.crypto.security_policies import SecurityPolicyAes256Sha256RsaPss
from asyncua.crypto.validator import CertificateValidator, CertificateValidatorOptions
from asyncua.crypto.truststore import TrustStore

sys.path.insert(0, "..")

_logger = logging.getLogger(__name__)

cert_base =             Path(__file__).parent
server_cert =           Path(cert_base / "certificates/brownfield_server_cert.der")
server_private_key =    Path(cert_base / "certificates/brownfield_server_key.pem")
client_cert =           Path(cert_base / "certificates/trusted/cpc_client_cert.der")
#client_private_key =    Path(cert_base / "certificates/python-client/client_key.pem")


async def start_secured_server():
    server_app_uri = f"urn:freeopcua:brownfield_server" #NOTE: this value MUST match the configured certificate subjectAltName!

    cert_user_manager = CertificateUserManager()
    #await cert_user_manager.add_admin(client_cert, name='PythonClient')
    await cert_user_manager.add_user(client_cert, name='PythonClient')

    server = Server(user_manager=cert_user_manager)

    await server.init() 

    await server.set_application_uri(server_app_uri)
    server.set_endpoint("opc.tcp://0.0.0.0:4840/freeopcua/server/")
    server.set_security_policy([ua.SecurityPolicyType.Aes256Sha256RsaPss_SignAndEncrypt],
                            permission_ruleset=SimpleRoleRuleset())

    # load server certificate and private key. This enables endpoints with signing and encryption.
    await server.load_certificate(str(server_cert))
    await server.load_private_key(str(server_private_key))

    # TRUSTSTORE
    trust_store = TrustStore([Path(cert_base / "certificates/trusted")], [])
    await trust_store.load()
    validator = CertificateValidator(options=CertificateValidatorOptions.TRUSTED_VALIDATION | CertificateValidatorOptions.PEER_CLIENT, trust_store = trust_store)
    server.set_certificate_validator(validator)

    idx = 0
    # populating our address space
    myobj = await server.nodes.objects.add_object(idx, "MyObject")
    myvar = await myobj.add_variable(idx, "MyVariable", ua.Float(0.0), datatype=ua.NodeId(ua.ObjectIds.Float))
    await myvar.set_read_only()  # Set MyVariable to be writable by clients

    #idx = 1
    # Add the new variables
    system1_obj = await server.nodes.objects.add_object(idx, "System1")
    _logger.info(f"System 1: {system1_obj}")
    
    # 1. Key Personnel present (Boolean)
    key_personnel_var = await system1_obj.add_variable(idx, "KeyPersonnelPresent", False)
    await key_personnel_var.set_read_only()
    _logger.info(f"Key Personnel Present: {key_personnel_var}")
    
    # 2. System 1 available (Boolean)
    system1_available_var = await system1_obj.add_variable(idx, "SystemAvailable", True)
    await system1_available_var.set_read_only()
    _logger.info(f"System 1 Available: {system1_available_var}")
    
    # 3. Operation mode System 1 (String - with predefined values)
    operation_modes = ["idle", "stop", "busy", "emergency", "maintenance"]
    operation_mode_var = await system1_obj.add_variable(idx, "OperationMode", ua.String("idle"))
    await operation_mode_var.set_read_only()
    _logger.info(f"Operation Mode: {operation_mode_var}")
    
    # 4. Warning System 1 (String - with predefined values)
    warning_states = ["none", "warning"]
    warning_var = await system1_obj.add_variable(idx, "Warning", ua.String("none"))
    await warning_var.set_read_only()
    _logger.info(f"Warning System 1: {warning_var}")

    # starting server!
    async with server:
        _logger.warning("Server started!")
        while True:
            await asyncio.sleep(1)
            current_val = await myvar.get_value()
            count = current_val + ua.Float(0.15)
            await myvar.write_value(ua.Float(count))
            _logger.info(f"Current value of MyVariable: {count}")

            # Update the new variables with random values
            # 1. Key Personnel present - randomly change with 10% probability
            if random.random() < 0.1:
                new_personnel_state = not await key_personnel_var.get_value()
                await key_personnel_var.write_value(new_personnel_state)
                _logger.info(f"Key Personnel Present changed to: {new_personnel_state}")
            
            # 2. System 1 available - randomly change with 5% probability
            if random.random() < 0.05:
                new_system_available = not await system1_available_var.get_value()
                await system1_available_var.write_value(new_system_available)
                _logger.info(f"System Available changed to: {new_system_available}")
            
            # 3. Operation mode System 1 - randomly change with 15% probability
            if random.random() < 0.15:
                new_operation_mode = random.choice(operation_modes)
                await operation_mode_var.write_value(ua.String(new_operation_mode))
                _logger.info(f"Operation Mode changed to: {new_operation_mode}")
            
            # 4. Warning System 1 - randomly change with 8% probability
            if random.random() < 0.08:
                new_warning_state = random.choice(warning_states)
                await warning_var.write_value(ua.String(new_warning_state))
                _logger.info(f"Warning state changed to: {new_warning_state}")



def run_server():
    asyncio.run(start_secured_server())


if __name__ == "__main__":
    run_server()

'''import asyncio
import sys
#import argparse
import logging
from pathlib import Path

from asyncua import ua
from asyncua import Server
from asyncua.crypto.permission_rules import SimpleRoleRuleset
from asyncua.server.user_managers import CertificateUserManager
from asyncua.crypto.security_policies import SecurityPolicyAes256Sha256RsaPss
from asyncua.crypto.validator import CertificateValidator, CertificateValidatorOptions
from asyncua.crypto.truststore import TrustStore

sys.path.insert(0, "..")

logging.basicConfig(level=logging.WARNING)
_logger = logging.getLogger(__name__)

OPCUA_ROLE_SERVER = True
CLIENT_LOOP = False

cert_base =             Path(__file__).parent
server_cert =           Path(cert_base / "certificates/brownfield_server_cert.der")
server_private_key =    Path(cert_base / "certificates/brownfield_server_key.pem")
client_cert =           Path(cert_base / "certificates/trusted/client_cert.der")
#client_private_key =    Path(cert_base / "certificates/python-client/client_key.pem")


async def main():
    server_app_uri =   f"brownfield-server"

    cert_user_manager = CertificateUserManager()
    #await cert_user_manager.add_admin(client_cert, name='PythonClient')
    await cert_user_manager.add_user(client_cert, name='PythonClient')

    server = Server(user_manager=cert_user_manager)

    await server.init()

    await server.set_application_uri(server_app_uri)
    server.set_endpoint("opc.tcp://0.0.0.0:4840/freeopcua/server/")
    server.set_security_policy([ua.SecurityPolicyType.Aes256Sha256RsaPss_SignAndEncrypt],
                            permission_ruleset=SimpleRoleRuleset())

    # load server certificate and private key. This enables endpoints with signing and encryption.
    await server.load_certificate(str(server_cert))
    await server.load_private_key(str(server_private_key))

    # TRUSTSTORE
    trust_store = TrustStore([Path(cert_base / "certificates/trusted")], [])
    await trust_store.load()
    validator = CertificateValidator(options=CertificateValidatorOptions.TRUSTED_VALIDATION | CertificateValidatorOptions.PEER_CLIENT, trust_store = trust_store)
    server.set_certificate_validator(validator)

    idx = 0
    # populating our address space
    myobj = await server.nodes.objects.add_object(idx, "MyObject")
    myvar = await myobj.add_variable(idx, "MyVariable", ua.Float(0.0), datatype=ua.NodeId(ua.ObjectIds.Float))
    await myvar.set_read_only()  # Set MyVariable to be writable by clients

    print(myvar.nodeid)
    print(myobj.nodeid)

    # starting server!
    async with server:
        _logger.warning("Server started!")
        while True:
            await asyncio.sleep(1)
            current_val = await myvar.get_value()
            count = current_val + ua.Float(0.15)
            await myvar.write_value(ua.Float(count))


if __name__ == "__main__":
    asyncio.run(main())'''