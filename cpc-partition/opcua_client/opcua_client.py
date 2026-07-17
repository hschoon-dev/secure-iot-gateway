"""
------------------------------------------------------------
 Modul:    cpc-partition/opcua_client.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    This module contains OPC UA client implementation for
    communication with OPC UA servers in the context of
    the CPC partition.

 Autor(en):
    - Heiko Schoon

 Maintainer:
    - Heiko Schoon <heiko.schoon@hs-emden-leer.de>

 Hinweis:
    Ongoing development.
------------------------------------------------------------
"""

from asyncua import Client, ua
from asyncua.crypto.security_policies import (
    SecurityPolicyBasic128Rsa15,
    SecurityPolicyBasic256,
    SecurityPolicyBasic256Sha256,
    SecurityPolicyAes128Sha256RsaOaep,
    SecurityPolicyAes256Sha256RsaPss
)
from asyncua.crypto.validator import CertificateValidator, CertificateValidatorOptions
from asyncua.crypto.truststore import TrustStore
from pathlib import Path
import logging
import time
from typing import Optional

_logger = logging.getLogger(__name__)

SECURITY_POLICY_MAP = {
    "SecurityPolicyNone": None,
    "SecurityPolicyBasic128Rsa15": SecurityPolicyBasic128Rsa15,
    "SecurityPolicyBasic256": SecurityPolicyBasic256,
    "SecurityPolicyBasic256Sha256": SecurityPolicyBasic256Sha256,
    "SecurityPolicyAes128Sha256RsaOaep": SecurityPolicyAes128Sha256RsaOaep,
    "SecurityPolicyAes256Sha256RsaPss": SecurityPolicyAes256Sha256RsaPss,
}

class OpcUaClient:
    def __init__(self, server_app_uri: str, client_app_uri: str, alias: str, 
                 security_settings: dict[str, str | None],
                   nodes: list[dict[str, ua.NodeId | str]],
                   cert_base: "Path | str | None" = None):
        self.server_app_uri = server_app_uri
        self.security_settings = security_settings
        self.alias = alias
        self.client = Client(url=server_app_uri)
        self.client.application_uri = client_app_uri
        self.nodes = nodes
        self.connected = False
        self._retry_interval = 10
        self._retry_count = 0
        self._max_retries = 6
        self._stopped_reconnection_attempts = False
        self._last_connection_attempt_time = 0
        # Directory that the client_certificate/client_private_key/
        # server_certificate paths in security_settings are relative to.
        # Defaults to this module's own directory for backward
        # compatibility, but OpcUaClientManager passes the endpoint XML
        # config's own directory instead, so relative cert paths in that
        # XML resolve next to it (e.g. on the read-only config volume)
        # rather than next to this .py file.
        self.cert_base = Path(cert_base) if cert_base is not None else Path(__file__).parent

    async def connect(self) -> None:
        cert_base = self.cert_base

        policy = self.security_settings['policy']
        # BUG: User authentication via username and password is not implemented for FreeOpcUa Server. This is supported by other OSS or commercial OPC UA servers.
        # https://github.com/FreeOpcUa/opcua-asyncio/blob/b8a796f1c04c2f1f535622e208817e1f237b5eb4/asyncua/server/user_managers.py#L11
        if self.security_settings['username'] is not None and self.security_settings['password'] is not None:
            self.client.set_user(self.security_settings['username'])
            self.client.set_password(self.security_settings['password'])
            _logger.warning(f"User authentication via username and password is not implemented for FreeOpcUa Servers.")
        if policy == 'SecurityPolicyNone':
            try:
                await self.client.connect()
                self.connected = True
                _logger.info(f"Connected to {self.server_app_uri}")
            except Exception as e:
                self.connected = False
                _logger.error(f"Error connecting to {self.server_app_uri}.")
        else:
            client_cert = Path(cert_base / self.security_settings['client_certificate'])
            client_private_key = Path(cert_base / self.security_settings['client_private_key'])
            server_cert = Path(cert_base / self.security_settings['server_certificate'])

            await self.client.set_security(
                SECURITY_POLICY_MAP[policy],
                certificate=str(client_cert),
                private_key=str(client_private_key),
                server_certificate=server_cert
            )

            trust_store = TrustStore([Path(cert_base / "certificates/trusted")], [])
            await trust_store.load()
            validator = CertificateValidator(CertificateValidatorOptions.TRUSTED_VALIDATION | CertificateValidatorOptions.PEER_SERVER, trust_store)
            self.client.certificate_validator = validator
            try:
                await self.client.connect()
                self.connected = True
                _logger.info(f"Connected to {self.server_app_uri}")
            except Exception as e:
                self.connected = False
                _logger.error(f"Error connecting to {self.server_app_uri}.")


    async def retry_connection(self) -> None:
        """
        Retry to connect to the OPC UA server with a minimum interval between attempts.
        """
        if self._retry_count >= self._max_retries:
            self._stopped_reconnection_attempts = True
            _logger.error(f"Maximum retry attempts reached for {self.server_app_uri}. Giving up.")
            return

        current_time = time.time()
        if current_time - self._last_connection_attempt_time < self._retry_interval:
            return  # Do not attempt to reconnect if the retry interval has not passed
        
        self._last_connection_attempt_time = current_time  # Update the last connection attempt time
        
        try:
            await self.client.connect()
            self.connected = True
            _logger.info(f"(Re)connection to {self.server_app_uri} successful.")
        except Exception as e:
            self.connected = False
            self._retry_count += 1
            _logger.warning(f"Reconnection to {self.server_app_uri} failed.")


    async def read_value(self, node_id: ua.NodeId) -> tuple[str | None, Optional[any], str | None]:
        """
        Read a value from an OPC UA node
        :param node_id: The OPC UA node ID to read from
        :return: Tuple of (browse_name, value, varType) or (None, None, None) if there was an error
        """
        try:
            _logger.debug(f"Reading value from {node_id} on {self.server_app_uri}")
            node = self.client.get_node(node_id)
            qualified_name = await node.read_browse_name()
            if qualified_name is None:
                _logger.error(f"Could not read browse name from {node_id} on {self.server_app_uri}.")
                        
            browse_name = f"{qualified_name.NamespaceIndex}:{qualified_name.Name}"
            value = await node.get_value()
            datatype = await node.read_data_value()
            varType = datatype.Value.VariantType.name
            return browse_name, value, varType
        except Exception as e:
            _logger.error(f"Error reading value from {node_id} on {self.server_app_uri}. Error: {e}")
            return None, None, None

    async def write_value(self, node_id: ua.NodeId, value: any) -> None:
        """
        Write a value to an OPC UA node
        :param node_id: The OPC UA node ID to write to
        :param value: The value to write
        """
        try:
            node = self.client.get_node(node_id)
            await node.set_value(value)
        except Exception as e:
            _logger.error(f"Error writing value to {node_id}.")

    async def disconnect(self) -> None:
        await self.client.disconnect()
        _logger.warning(f"Disconnected from {self.server_app_uri}")