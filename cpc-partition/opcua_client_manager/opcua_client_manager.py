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
from grpc_sender import send_json_payload


_logger = logging.getLogger(__name__)


class OpcUaClientManager:
    def __init__(self, xml_config_path: str | Path, xsd_path: str | Path):
        self.xml_config_path = str(xml_config_path)
        self.xsd_path = str(xsd_path)
        self.clients: list[OpcUaClient] = self.parse_clients()

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
        client: OpcUaClient
        while True:
            opcua_values = {}
            for client in self.clients:
                if not client.connected and not client._stopped_reconnection_attempts:
                    await client.retry_connection()
                    if not client.connected:
                        opcua_values[f"OPC UA Connections:{client.alias}"] = {
                                                     "value": client.connected,
                                                     "varType": "Boolean",
                                                     "description": "Connection status to the OPC UA server"
                                                 }
                if client._stopped_reconnection_attempts:
                    self.clients.remove(client)
                    _logger.error(f"Removing OPC UA client for {client.server_app_uri} from the client list.")
                if client.connected:
                    opcua_values[f"OPC UA Connections:{client.alias}"] = {
                                                    "value": client.connected,
                                                    "varType": "Boolean",
                                                    "description": "Connection status to the OPC UA server"
                                                }
                    for node in client.nodes:
                        value = None
                        browse_name = None
                        if node['datatype'] != 'Object':
                            browse_name, value, datatype = await client.read_value(node['node_id'])
                            browse_name_with_namespace_alias = f"{node['namespace_alias']}:{browse_name}"
                            if value is not None:
                                #opcua_values[browse_name] = {
                                opcua_values[browse_name_with_namespace_alias] = {    
                                                            "value": value,
                                                            "varType": str(datatype),
                                                            "description": f"{node['description']}"
                                                        }
                            else:
                                _logger.error(f"Error reading value from {node['node_id']}")
                                #opcua_values[browse_name] = {
                                opcua_values[browse_name_with_namespace_alias] = {
                                                            "value": "Error reading value",
                                                            "varType": "String",
                                                            "description": f"{node['description']}"
                                                        }
                                
            # TODO: Test with gRPC: dann payload noch in die Funktion einfügen... plus IP:PORT
            try:
                grpc_payload = json.dumps(opcua_values)
                psmo_response = send_json_payload(grpc_payload, source="OPCUA", dest="192.168.0.123:50051") # psmo-Partition
                if psmo_response is None:
                    _logger.error(f"Error sending gRPC with JSON")
                interface_response = send_json_payload(grpc_payload, source="OPCUA", dest="192.168.0.121:50051") # Interface-Partition
                if interface_response is None:
                    _logger.error(f"Error sending gRPC with JSON")
            except Exception as e:
                _logger.error(f"Exception sending gRPC with JSON: {e}")

            await asyncio.sleep(interval)

    async def stop_clients(self) -> None:
        """
        Disconnect from all OPC UA servers
        """
        await asyncio.gather(*(client.disconnect() for client in self.clients))