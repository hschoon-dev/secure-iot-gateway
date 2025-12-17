"""
------------------------------------------------------------
 Modul:    central-mo-client/main.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    Implements an OPC UA client for the central M+O application.
    It connects to the secured OPC UA server in the Secure IoT
    Gateway and submits requests for testing purposes.

 Autor(en):
    - Heiko Schoon

 Maintainer:
    - Heiko Schoon <heiko.schoon@hs-emden-leer.de>

 Hinweis:
    Do not use this code in production. It is for testing
    and demonstration purposes only.
------------------------------------------------------------
"""

from test_requests  import generate_request_parameters, create_request_arguments, add_users_to_user_manager
from asyncua import Client, ua
import asyncio
import logging
from asyncua.crypto.security_policies import SecurityPolicyAes256Sha256RsaPss
from asyncua.crypto.validator import CertificateValidator, CertificateValidatorOptions
from asyncua.crypto.truststore import TrustStore
from asyncua.ua import StatusCode, StatusCodes

from pathlib import Path
import sys
import os
from logging.handlers import RotatingFileHandler

path = os.path.dirname(os.path.abspath(__file__))
logging_path = os.path.join(path, "logs/app.log")

def setup_logging(
    log_level=logging.WARNING,
    log_file=logging_path,
    max_bytes=1 * 1024 * 1024,  # 1 MB
    backup_count=3
    ) -> logging.Logger:

    # Common log format
    log_format = (
        "[%(asctime)s] [%(levelname)-8s] "
        "[%(name)s:%(lineno)d] - %(message)s"
    )
    date_format = "%Y-%m-%d %H:%M:%S"

    formatter = logging.Formatter(log_format, datefmt=date_format)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # Rotating file handler
    print(f"Logging to file: {log_file}")
    file_handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    # Root logger config
    logging.basicConfig(
        level=log_level,
        handlers=[console_handler, file_handler],
    )

    return logging.getLogger(__name__)

_logger = setup_logging(logging.DEBUG)

async def submit_request(client: Client, in_args, params):
    """Submit the request to the server and log results"""
    try:
        # Find the method node
        objects = client.nodes.objects
        child = await objects.get_child(['2:RequestHandler'])
        
        _logger.info(f"Submit request with priority {params['priority']} at {params['timestamp']}")
        
        # Call the method
        try:
            result = await child.call_method("2:request", *in_args)
            
            # Parse output arguments
            _logger.info(f"Result: {result}")
            request_id, server_timestamp, notification = result
        except Exception as e:
            _logger.error(f"Error calling method: {e}")
            return None

        if "Submission received" in notification:
            _logger.info(f"Submission received for request {request_id} for issuer {params['issuer_id']} with parameters {params['parameters']} and modification {params['modification']}")
        # Log output arguments
        _logger.debug(f"Request ID:       {request_id}")
        _logger.debug(f"Server Timestamp: {server_timestamp}")
        _logger.debug(f"Notification:     {notification}")
        
        return result
    except Exception as e:
        _logger.error(f"Error calling method: {e}")
        return None
    
async def call_add_user_method(client: Client, admin: dict, users: dict):
    """Call the add user method on the server"""

    admin_id = list(admin.keys())[0]
    admin_credentials = admin[admin_id]
    try:
        # Find the method node
        objects = client.nodes.objects
        child = await objects.get_child(['2:UserManager'])
        
        for user, password in users.items():
            _logger.info(f"Adding user {user} with password {password}")
            try:
                res = await child.call_method("2:add_user",ua.Variant(admin_id, ua.VariantType.String), ua.Variant(admin_credentials, ua.VariantType.String), ua.Variant(user, ua.VariantType.String), ua.Variant(password, ua.VariantType.String))
                ua_status_code, ua_status_message = res
                _logger.debug(f"Method called for user {user} with credentials {password}: Result {res}")
                if str(ua_status_code) != str(StatusCode(StatusCodes.Good)):
                    _logger.error(f"Error adding user {user} with credentials {password}: {ua_status_message}")
                
            except Exception as e:
                _logger.error(f"Error calling method for user {user} with credentials {password}: {e}")
        return True
    
    except Exception as e:
        _logger.error(f"Error calling method: {e}")
        return None
    
async def clear_database(client: Client, admin: dict, users: dict):
    """Call the clear database method on the server"""
    admin_id = list(admin.keys())[0]
    admin_credentials = admin[admin_id]
    try:
        # Find the method node
        objects = client.nodes.objects
        child = await objects.get_child(['2:UserManager'])
        
        _logger.debug(f"Clearing user manager database")
        for user, password in users.items():
            _logger.info(f"Clearing user {user} with password {password}")
            try:
                res = await child.call_method("2:remove_user",ua.Variant(admin_id, ua.VariantType.String), ua.Variant(admin_credentials, ua.VariantType.String), ua.Variant(user, ua.VariantType.String))
                _logger.debug(f"Method called for user {user} with credentials {password}: Result {res}")
                ua_status_code, ua_status_message = res
                if str(ua_status_code) != str(StatusCode(StatusCodes.Good)):
                    _logger.error(f"Error clearing database: {ua_status_message}")
            except Exception as e:
                _logger.error(f"Error calling method for user {user} with credentials {password}: {e}")
        return True
    except Exception as e:
        _logger.error(f"Error calling method: {e}")
        return None

async def setup_client(max_retries=5, retry_delay=5):
    """Setup and connect to OPC UA client with security"""
    _logger.info(f"Central M+O Application started.")

    #url = "opc.tcp://interface-partition:4840/freeopcua/server/"  # Ensure this matches the server address
    url = "opc.tcp://192.168.0.121:4840/freeopcua/server/"

    cert_base = Path(__file__).parent
    client_cert = Path(cert_base / "certificates/python_client/mo_client_cert.der")
    client_private_key = Path(cert_base / "certificates/python_client/mo_client_key.pem")
    server_cert = Path(cert_base / "certificates/trusted/interface_server_cert.der")

    client = Client(url)
    client.application_uri = f"urn:freeopcua:client" #TODO: this value MUST match the configured certificate subjectAltName!
    # Set a reasonable timeout for operations
    client.session_timeout = 30000  # 30 seconds in milliseconds
    
    await client.set_security(
        SecurityPolicyAes256Sha256RsaPss,
        certificate=str(client_cert),
        private_key=str(client_private_key),
        server_certificate=server_cert
    )
    
    trust_store = TrustStore([Path(cert_base / "certificates/trusted")], [])
    await trust_store.load()
    validator = CertificateValidator(CertificateValidatorOptions.TRUSTED_VALIDATION | CertificateValidatorOptions.PEER_SERVER, trust_store)
    client.certificate_validator = validator

    # Implement retry logic for connecting to the server
    for attempt in range(max_retries):
        try:
            _logger.info(f"Attempting to connect to OPC UA server (Attempt {attempt+1}/{max_retries})")
            # Use a reasonable timeout for the connection attempt
            await asyncio.wait_for(client.connect(), timeout=10)
            _logger.info("Successfully connected to OPC UA server")
            return client
        except asyncio.TimeoutError:
            _logger.warning(f"Connection attempt {attempt+1} timed out")
        except Exception as e:
            _logger.error(f"Connection attempt {attempt+1} failed: {e}")
        
        if attempt < max_retries - 1:
            _logger.info(f"Waiting {retry_delay} seconds before retry...")
            await asyncio.sleep(retry_delay)
    
    _logger.error(f"Failed to connect after {max_retries} attempts")
    raise ConnectionError(f"Could not connect to OPC UA server at {url}")

async def is_client_connected(client):
    """Check if client is still connected and operational"""
    try:
        # Simple test to check if the connection is still alive
        await asyncio.wait_for(client.nodes.server_state.read_value(), timeout=5)
        return True
    except Exception:
        return False

async def main():
    """Main function to execute request submissions in a loop"""
    await asyncio.sleep(15)  # Initial delay to ensure server is up
    client = None
    try:
        client = await setup_client()
        
        admin, users = add_users_to_user_manager()
        await call_add_user_method(client, admin, users)
        
        calls = 0
        while calls < 10000:
            try:
                # Check the connection before attempting operations
                if not await is_client_connected(client):
                    _logger.warning("Connection lost. Attempting to reconnect...")
                    await client.disconnect()
                    client = await setup_client()
                
                try:
                    params = generate_request_parameters()

                except Exception as e:
                    _logger.error(f"Error generating request parameters: {e}")
                    continue
                in_args = create_request_arguments(params)
                await submit_request(client, in_args, params)
            except Exception as e:
                _logger.error(f"Error in request cycle: {e}")  
            calls += 1
            await asyncio.sleep(.1)  # Increased sleep to reduce load on server
        
    except Exception as e:
        _logger.error(f"Main loop error: {e}")
    finally:
        if client:
            try:
                await client.disconnect()
            except Exception as e:
                _logger.error(f"Error disconnecting client: {e}")


if __name__ == "__main__":
    asyncio.run(main())