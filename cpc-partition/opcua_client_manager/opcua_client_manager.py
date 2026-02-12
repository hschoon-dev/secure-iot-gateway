"""
------------------------------------------------------------
 Modul:    cpc-partition/opcua_client_manager.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    This module contains an OPC UA client manager that handles
    multiple OPC UA clients based on an XML configuration file.
    It supports secure connections, periodic reading of node values,
    and writing the values to shared memory for inter-process
    communication.

 Autor(en):
    - Heiko Schoon

 Maintainer:
    - Heiko Schoon <heiko.schoon@hs-emden-leer.de>

 Hinweis:
    Ongoing development.
------------------------------------------------------------
"""

import asyncio
from defusedxml import ElementTree as ET
from asyncua import  ua
from pathlib import Path
import json
import xmlschema
import logging
import os

from opcua_client import OpcUaClient
from grpc_sender import get_sender


_logger = logging.getLogger(__name__)


class OpcUaClientManager:
    def __init__(self, xml_config_path: str | Path, xsd_path: str | Path):
        self.xml_config_path = str(xml_config_path)
        self.xsd_path = str(xsd_path)
        self.clients: list[OpcUaClient] = self.parse_clients()

        # Reuse snapshot dicts to reduce allocations/GC pressure (full snapshot semantics kept).
        self._snapshot: dict[str, dict] = {}
        self._entry_pool: dict[str, dict] = {}

        # Pre-create/reuse gRPC senders (lazy init inside get_sender).
        self._psmo_sender = get_sender("192.168.156.13:50051")
        self._interface_sender = get_sender("192.168.156.12:50051")

        # Precompute connection status keys per client alias
        self._conn_key: dict[str, str] = {}
        for c in self.clients:
            self._conn_key[c.alias] = f"OPC UA Connections:{c.alias}"

    def _set_entry(self, key: str, value, varType: str, description: str) -> None:
        """Reuse inner dict objects for each key."""
        entry = self._entry_pool.get(key)
        if entry is None:
            entry = {}
            self._entry_pool[key] = entry
        entry["value"] = value
        entry["varType"] = varType
        entry["description"] = description
        self._snapshot[key] = entry

    def parse_clients(self) -> list[OpcUaClient]:
        """
        Parse the XML configuration file and create a list of OPC UA clients
        :return: A list of OPC UA clients
        """
        schema = xmlschema.XMLSchema(self.xsd_path)
        if not schema.is_valid(self.xml_config_path):
            _logger.error("The XML file does not conform to the provided XSD schema.")

        try:
            tree = ET.parse(self.xml_config_path)
            print(f"Size of OPC UA XML file:        {os.path.getsize(self.xml_config_path)}")
        except (ET.ParseError, FileNotFoundError) as e:
            _logger.error(f"Error parsing XML file: {e}")
            return []

        root = tree.getroot()
        clients = []
        for server in root.findall('server'):
            server_app_uri = server.find('server_app_uri').text
            client_app_uri = server.find('client_app_uri').text
            alias = server.find('alias').text

            security = server.find('security')
            security_settings = {
                'policy': security.find('policy').text,
                'mode': security.find('mode').text,
                'client_certificate': security.find('client_certificate').text if security.find('client_certificate') is not None else None,
                'client_private_key': security.find('client_private_key').text if security.find('client_private_key') is not None else None,
                'server_certificate': security.find('server_certificate').text if security.find('server_certificate') is not None else None,
                'username': security.find('username').text if security.find('username') is not None else None,
                'password': security.find('password').text if security.find('password') is not None else None
            }

            nodes = []
            for node in server.findall('nodes/node'):
                node_info = {}
                # String-Identifier is used in the Siemens S7 OPC UA server (OMAG usecase)
                if str(node.find('IdentifierType').text) == 'String':
                    node_id = ua.NodeId.from_string(f"ns={int(node.find('NamespaceIndex').text)};s={str(node.find('Identifier').text)}")
                    node_info = {
                        'node_id': node_id,
                        'datatype': node.find('datatype').text,
                        'description': node.find('description').text,
                        'namespace_alias': node.find('NamespaceAlias').text
                    }
                elif str(node.find('IdentifierType').text) == 'Numeric':
                    node_id = ua.NodeId(int(node.find('Identifier').text), int(node.find('NamespaceIndex').text))
                    node_info = {
                        'node_id': node_id,
                        'datatype': node.find('datatype').text,
                        'description': node.find('description').text,
                        'namespace_alias': node.find('NamespaceAlias').text
                    }
                else: # TODO: Implement GUID and Opaque/ByteString identifier types. See: https://reference.opcfoundation.org/Core/Part6/v105/docs/5.2.2.9
                    _logger.error(f"Unknown Identifier type: {node.find('Identifier').text}. Expected 'String' or 'Numeric'.")
                    raise NotImplementedError("GUID or Opaque identifier types are not supported.")
                nodes.append(node_info)

            client = OpcUaClient(server_app_uri, client_app_uri, alias, security_settings, nodes)
            clients.append(client)
        return clients

    async def start_clients(self) -> list[None]:
        """
        Connect to all OPC UA servers
        :return: A list of futures for the connection attempts
        """
        future_list = await asyncio.gather(*(client.connect() for client in self.clients))
        return future_list


    async def periodic_read(self, interval: float) -> None:
        """
        Periodically read values from OPC UA nodes and write them to shared memory
        :param interval: Time between reads in seconds
        :param shm_list: List of shared memory objects to write to
        :param semaphore_list: List of semaphores for synchronizing access to shared memory
        """
        while True:
            # Dict reuse: keep full snapshot semantics but avoid allocating new dicts every tick.
            snap = self._snapshot
            snap.clear()

            # Iterate over a copy to allow safe removal of stopped clients
            new_clients: list[OpcUaClient] = []
            for client in list(self.clients):
                if not client.connected and not client._stopped_reconnection_attempts:
                    await client.retry_connection()

                # Remove clients that have permanently stopped reconnecting
                if client._stopped_reconnection_attempts:
                    _logger.error("Removing OPC UA client for %s from the client list.", client.server_app_uri)
                    continue

                new_clients.append(client)

                conn_key = self._conn_key.get(client.alias) or f"OPC UA Connections:{client.alias}"
                self._set_entry(conn_key, bool(client.connected), "Boolean", "Connection status to the OPC UA server")

                if client.connected:
                    for node in client.nodes:
                        if node.get('datatype') == 'Object':
                            continue

                        browse_name, value, datatype = await client.read_value(node['node_id'])
                        browse_name_with_namespace_alias = f"{node['namespace_alias']}:{browse_name}"

                        if value is not None:
                            self._set_entry(
                                browse_name_with_namespace_alias,
                                value,
                                str(datatype),
                                f"{node['description']}",
                            )
                        else:
                            _logger.error("Error reading value from %s", node['node_id'])
                            self._set_entry(
                                browse_name_with_namespace_alias,
                                "Error reading value",
                                "String",
                                f"{node['description']}",
                            )

            # Replace client list with filtered list (safe)
            self.clients = new_clients

            try:
                grpc_payload = json.dumps(snap, separators=(",", ":"), ensure_ascii=False)

                # gRPC calls are blocking -> send in worker threads and in parallel
                psmo_task = asyncio.to_thread(self._psmo_sender.send, grpc_payload, source="OPCUA")
                iface_task = asyncio.to_thread(self._interface_sender.send, grpc_payload, source="OPCUA")
                psmo_resp, iface_resp = await asyncio.gather(psmo_task, iface_task)
                if psmo_resp is None or iface_resp is None:
                    _logger.error("Error sending gRPC with JSON")
            except Exception as e:
                _logger.error("Exception sending gRPC with JSON: %s", e)

            # Safety: keep entry pool from growing without bound in highly dynamic setups.
            if len(self._entry_pool) > 50_000:
                self._entry_pool.clear()

            await asyncio.sleep(interval)

    async def stop_clients(self) -> None:
        """
        Disconnect from all OPC UA servers
        """
        await asyncio.gather(*(client.disconnect() for client in self.clients))