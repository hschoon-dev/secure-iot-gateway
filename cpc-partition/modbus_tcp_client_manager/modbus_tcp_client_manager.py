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
from defusedxml import ElementTree as ET
import json
import xmlschema
import logging
import os

from modbus_tcp_client import ModbusTCPClient
from grpc_sender import get_sender

_logger = logging.getLogger(__name__)

class ModbusClientManager:
    def __init__(self, xml_config_path: str, xsd_path: str, grpc_interface_ip_address: str, grpc_psmo_ip_address: str):
        self.xml_config_path = xml_config_path
        self.xsd_path = xsd_path
        self.endpoints = self.load_endpoints_from_xml()
        self.clients = self.create_clients()
        self.grpc_interface_ip_address = grpc_interface_ip_address
        self.grpc_psmo_ip_address = grpc_psmo_ip_address

        # Reuse snapshot dicts to reduce allocations/GC pressure (full snapshot semantics kept).
        self._snapshot: dict[str, dict] = {}
        self._entry_pool: dict[str, dict] = {}

        # Pre-create/reuse gRPC senders (lazy init inside get_sender).
        self._psmo_sender = get_sender(grpc_psmo_ip_address)
        self._interface_sender = get_sender(grpc_interface_ip_address)

        # Precompute constant connection status keys per client alias.
        self._conn_key: dict[str, str] = {}
        for c in self.clients:
            self._conn_key[c.serveralias] = f"ModbusTCP Connections:{c.serveralias}: Connection status"

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
        Attempt an initial connection to every configured Modbus TCP server.

        Unlike OpcUaClientManager, the pymodbus sync client connects lazily on
        the first read; this method therefore just logs the configured targets so
        connection failures during the first periodic_read() are not silent.
        A genuine connect() call would require switching to the async pymodbus
        client or using asyncio.to_thread — left as a future improvement.
        """
        if not self.clients:
            _logger.warning(
                "ModbusClientManager.start_clients: no clients configured "
                "(XML parse may have failed). periodic_read() will abort immediately."
            )
            return
        for client in self.clients:
            _logger.info(
                "Modbus TCP client configured for %s:%s (alias: %s). "
                "Connection will be attempted on first read.",
                client.ipaddr, client.port, client.serveralias,
            )

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
            # Dict reuse: keep full snapshot semantics but avoid allocating new dicts every tick.
            snap = self._snapshot
            snap.clear()
            client: ModbusTCPClient
            for client in self.clients:
                if not client.client.is_open:
                    # retry_connection() uses a synchronous pymodbus client and
                    # may block for a full TCP-connect timeout (several seconds).
                    # Running it directly in the async event loop would stall all
                    # other coroutines (OPC UA reads, gRPC sends) for that duration.
                    # asyncio.to_thread() offloads the blocking call to a worker
                    # thread so the event loop remains responsive.
                    await asyncio.to_thread(client.retry_connection)
                conn_key = self._conn_key.get(client.serveralias) or f"ModbusTCP Connections:{client.serveralias}: Connection status"
                if not client.client.is_open:  # Check again if the connection was successful
                    self._set_entry(
                        conn_key,
                        False,
                        "Boolean",
                        "Connection status to the Modbus server",
                    )
                if client.client.is_open:
                    self._set_entry(
                        conn_key,
                        True,
                        "Boolean",
                        "Connection status to the Modbus server",
                    )
                    for endpoint_name in client.endpoints:      
                        # TODO: Test with different endpoints and Modbus-Functions, e.g., Write Coils, Write Single Register, Write Multiple Registers
                        try:
                            if client.endpoints[endpoint_name]['function'] == 'Read Holding Registers':
                                register_values, datatype = client.fc03_read_holding_registers(endpoint_name)
                                if register_values is not None and datatype is not None:
                                    key = f"{client.serveralias}: {endpoint_name}"
                                    self._set_entry(key, register_values, datatype, f"{client.endpoints[endpoint_name]['description']}")
                            elif client.endpoints[endpoint_name]['function'] == 'Read Discrete Input':   
                                discrete_input_values = client.fc02_read_discrete_inputs(endpoint_name)
                                if discrete_input_values is not None:
                                    key = f"{client.serveralias}: {endpoint_name}"
                                    self._set_entry(key, discrete_input_values, "Boolean", f"{client.endpoints[endpoint_name]['description']}")
                            elif client.endpoints[endpoint_name]['function'] == 'Read Coil Status' or client.endpoints[endpoint_name]['function'] == 'Read Coils':
                                coil_status_values = client.fc01_read_coil_status(endpoint_name)
                                if coil_status_values is not None:
                                    key = f"{client.serveralias}: {endpoint_name}"
                                    self._set_entry(key, coil_status_values, "Boolean", f"{client.endpoints[endpoint_name]['description']}")
                        except Exception as e:
                            _logger.error(f"Error reading {endpoint_name} from {client.ipaddr} with alias {client.serveralias}: {e}")
                            key = f"{client.serveralias}: {endpoint_name}"
                            self._set_entry(key, "ERROR READING VALUE", "String", f"{client.endpoints[endpoint_name]['description']}")
            
            try:
                # Compact JSON encoding (less bytes + a bit less CPU)
                grpc_payload = json.dumps(snap, separators=(",", ":"), ensure_ascii=False)

                # gRPC calls are blocking -> send in worker threads and in parallel
                psmo_task = asyncio.to_thread(self._psmo_sender.send, grpc_payload, source="MODBUSTCP")
                iface_task = asyncio.to_thread(self._interface_sender.send, grpc_payload, source="MODBUSTCP")
                psmo_resp, iface_resp = await asyncio.gather(psmo_task, iface_task)
                if psmo_resp is None or iface_resp is None:
                    _logger.error("Error sending gRPC with JSON")
            except Exception as e:
                _logger.error(f"Exception sending gRPC with JSON: {e}")

            # Safety: keep entry pool from growing without bound in highly dynamic setups.
            # (Tune threshold to your expected max number of variables)
            if len(self._entry_pool) > 50_000:
                self._entry_pool.clear()

            await asyncio.sleep(interval)

    def load_endpoints_from_xml(self) -> dict[tuple[str, int, str], dict[str, dict[str, str | int]]] | None:
        # Returns None when the XML file cannot be parsed. Callers must guard
        # for None before iterating. create_clients() already does this check;
        # any future consumer of self.endpoints must do the same.
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