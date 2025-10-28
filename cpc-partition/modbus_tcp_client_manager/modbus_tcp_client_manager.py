"""
------------------------------------------------------------
 Modul:    cpc-partition/modbus_tcp_client_manager.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    This module contains Modbus TCP client manager implementation
    for managing multiple Modbus TCP clients in the context of
    the CPC partitions data aggregation.
    It supports connections, periodic reading of node values,
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
#import xml.etree.ElementTree as ET
from defusedxml import ElementTree as ET
#from multiprocessing import shared_memory
import json
import xmlschema
import logging
import os
#import posix_ipc

from modbus_tcp_client import ModbusTCPClient
from grpc_sender import send_json_payload

_logger = logging.getLogger(__name__)


class ModbusClientManager:
    def __init__(self, xml_config_path: str, xsd_path: str):
        self.xml_config_path = xml_config_path
        self.xsd_path = xsd_path
        self.endpoints = self.load_endpoints_from_xml()
        self.clients = self.create_clients()

    def create_clients(self) -> list[ModbusTCPClient]:
        """
        Create ModbusTCP clients for each server in the endpoints dictionary.
        return: A list of ModbusTCP clients.
        """
        modbus_clients = []
        if self.endpoints is None:
            return []
        else:
            for ipaddr, port, serveralias in self.endpoints:
                client_endpoints = self.endpoints[(ipaddr, port, serveralias)]
                modbus_client = ModbusTCPClient(ipaddr, port, serveralias, client_endpoints)
                modbus_clients.append(modbus_client)
        return modbus_clients

    async def start_clients(self) -> None:
        """
        Connect to the ModbusTCP servers.
        """
        #await asyncio.gather(*(client.connect() for client in self.clients))
        pass

    async def stop_clients(self) -> None:
        """
        Close the ModbusTCP connections.
        """
        client: ModbusTCPClient
        for client in self.clients:
            client.client.close()
    
    async def periodic_read(self, interval: float) -> None:
        """
        Periodically read the ModbusTCP values and write them to shared memory.
        interval: The time interval in seconds between each read operation.
        shm_list: A list of shared memory objects to write the ModbusTCP values to.
        semaphore_list: A list of semaphores to control access to the shared memory objects.
        """
        # Abort if no Modbus clients have been created
        if self.clients == []:
            _logger.error(f"Modbus client list is empty. Periodic value reading aborted.")
            return

        while True:
            modbus_values = {}
            client: ModbusTCPClient
            for client in self.clients:
                if not client.client.is_open:
                    client.retry_connection()
                if not client.client.is_open: # Check again if the connection was successful
                    modbus_values[f"ModbusTCP Connections:{client.serveralias}: Connection status"] = {
                                                    "value": False,
                                                    "varType": "Boolean",
                                                    "description": "Connection status to the Modbus server"
                                                }
                if client.client.is_open:
                    modbus_values[f"ModbusTCP Connections:{client.serveralias}: Connection status"] = {
                                                    "value": True,
                                                    "varType": "Boolean",
                                                    "description": "Connection status to the Modbus server"
                                                }
                    for endpoint_name in client.endpoints:      
                        # TODO: Test with different endpoints and Modbus-Functions, e.g., Write Coils, Write Single Register, Write Multiple Registers
                        try:
                            if client.endpoints[endpoint_name]['function'] == 'Read Holding Registers':
                                register_values, datatype = client.fc03_read_holding_registers(endpoint_name)
                                if register_values is not None and datatype is not None:
                                    modbus_values[f"{client.serveralias}: {endpoint_name}"] = {
                                                            "value": register_values,
                                                            "varType": datatype,
                                                            "description": f"{client.endpoints[endpoint_name]['description']}"
                                                        }
                            elif client.endpoints[endpoint_name]['function'] == 'Read Discrete Input':   
                                discrete_input_values = client.fc02_read_discrete_inputs(endpoint_name)
                                if discrete_input_values is not None:
                                    modbus_values[f"{client.serveralias}: {endpoint_name}"] = {
                                                            "value": discrete_input_values,
                                                            "varType": "Boolean",
                                                            "description": f"{client.endpoints[endpoint_name]['description']}"
                                                        }
                            elif client.endpoints[endpoint_name]['function'] == 'Read Coil Status' or client.endpoints[endpoint_name]['function'] == 'Read Coils':
                                coil_status_values = client.fc01_read_coil_status(endpoint_name)
                                if coil_status_values is not None:
                                    modbus_values[f"{client.serveralias}: {endpoint_name}"] = {
                                                            "value": coil_status_values,
                                                            "varType": "Boolean",
                                                            "description": f"{client.endpoints[endpoint_name]['description']}"
                                                        }
                        except Exception as e:
                            _logger.error(f"Error reading {endpoint_name} from {client.ipaddr} with alias {client.serveralias}: {e}")
                            modbus_values[f"{client.serveralias}: {endpoint_name}"] = {
                                                        "value": "ERROR READING VALUE",
                                                        "varType": "String",
                                                        "description": f"{client.endpoints[endpoint_name]['description']}"
                                                    }
            
            # TODO: Test with gRPC: dann payload noch in die Funktion einfügen... plus IP:PORT
            try:
                grpc_payload = json.dumps(modbus_values)
                response = send_json_payload(grpc_payload, source="MODBUSTCP", dest="172.20.128.6:50051") # psmo-Partition
                if response is None:
                    _logger.error(f"Error sending gRPC with JSON")
                interface_response = send_json_payload(grpc_payload, source="MODBUSTCP", dest="172.20.128.7:50051") # Interface-Partition
                if interface_response is None:
                    _logger.error(f"Error sending gRPC with JSON")
            except Exception as e:
                _logger.error(f"Exception sending gRPC with JSON: {e}")

            await asyncio.sleep(interval)

    def load_endpoints_from_xml(self) -> dict[tuple[str, int, str], dict[str, dict[str, str | int]]]:
        """
        Load the ModbusTCP endpoints from an XML file and return a dictionary with the server's IP address, port, and alias as the key.
        The value is a dictionary with the endpoint name as the key and the endpoint details as the value.
        """
        # Validate the XML file against the XSD file
        schema = xmlschema.XMLSchema(self.xsd_path)
        if not schema.is_valid(self.xml_config_path):
            _logger.error("The XML file does not conform to the provided XSD schema.")

        # Load the XML file
        try:
            tree = ET.parse(self.xml_config_path)
            print(f"Size of ModbusTCP XML file:    {os.path.getsize(self.xml_config_path)}")
        except(ET.ParseError, FileNotFoundError) as e:
            _logger.error(f"Error parsing XML file: {e}")
            return None
        root = tree.getroot()

        endpoints = {}
        for server in root.findall('server'):
            ipaddr = server.find('ipaddr').text
            port = int(server.find('port').text)
            serveralias = server.find('serveralias').text

            # Create a dictionary to store the server's endpoints
            server_endpoints = {}
            for endpoint in server.find('endpoints').findall('endpoint'):
                name = endpoint.find('name').text
                function = endpoint.find('function').text
                address = int(endpoint.find('address').text)
                quantity = int(endpoint.find('quantity').text)
                offset = int(endpoint.find('offset').text)
                type = endpoint.find('type').text
                description = endpoint.find('description').text

                # Create a dictionary to store the endpoint details
                endpoint_details = {
                    'name': name,
                    'function': function,
                    'address': address,
                    'quantity': quantity,
                    'offset': offset,
                    'type': type,
                    'description': description
                }
                server_endpoints[name] = endpoint_details

            # Add the server's endpoints to the endpoints dictionary
            endpoints[(ipaddr, port, serveralias)] = server_endpoints
        return endpoints