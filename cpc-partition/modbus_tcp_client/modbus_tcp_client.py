"""
------------------------------------------------------------
 Modul:    cpc-partition/modbus_tcp_client.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    This module contains Modbus TCP client implementation for
    communication with Modbus TCP servers in the context of
    the CPC partition.

 Autor(en):
    - Heiko Schoon

 Maintainer:
    - Heiko Schoon <heiko.schoon@hs-emden-leer.de>

 Hinweis:
    Ongoing development.
------------------------------------------------------------
"""

from pyModbusTCP.client import ModbusClient
from pyModbusTCP.utils import test_bit, set_bit
import logging
import time

_logger = logging.getLogger(__name__)

class ModbusTCPClient:
    def __init__(self, ipaddr: str, port: int, serveralias: str, endpoints: dict[str, dict[str, str | int | bool]]):
        self.ipaddr = ipaddr
        self.port = port          # store so callers (e.g. start_clients logging) can read it
        self.endpoints = endpoints
        self.serveralias = serveralias
        self.client = ModbusClient(host=ipaddr, port=port, unit_id=1, auto_open=True)
        self.client.timeout = 1.0
        self.status = self.client.is_open
        self._last_connection_attempt_time = 0
        self._retry_interval = 5
    
    def retry_connection(self) -> None:
        """
        Retry to connect to the ModbusTCP server.
        """
        current_time = time.time()
        if current_time - self._last_connection_attempt_time < self._retry_interval:
            return  # Do not attempt to reconnect if the retry interval has not passed
        self._last_connection_attempt_time = current_time # Update the last connection attempt time

        connected = self.client.open()
        if connected:
            self.status = True
            _logger.info(f"(Re)connection to {self.client.host} successful.")  
        else:
            self.status = False
            _logger.error(f"Reconnection to {self.client.host} failed.")  

    def fc01_read_coil_status(self, name: str) -> bool | None:
        """
        Read coil status from the ModbusTCP server.
        name: The name of the endpoint to read.
        return: The value of the coil, or None on failure.
        """
        endpoint = self.endpoints[name]
        address = endpoint['address']
        quantity = endpoint['quantity']
        request = self.client.read_coils(address, quantity)
        if request is None:
            _logger.error("fc01_read_coil_status: no response from server for endpoint '%s' (addr %s)", name, address)
            return None
        return request[0]

    def fc02_read_discrete_inputs(self, name: str) -> bool | None:
        """
        Read discrete inputs from the ModbusTCP server.
        name: The name of the endpoint to read.
        return: The value of the discrete input, or None on failure.
        """
        endpoint = self.endpoints[name]
        address = endpoint['address']
        quantity = endpoint['quantity']
        request = self.client.read_discrete_inputs(address, quantity)
        if request is None:
            _logger.error("fc02_read_discrete_inputs: no response from server for endpoint '%s' (addr %s)", name, address)
            return None
        return request[0]

    def fc03_read_holding_registers(self, name: str) -> tuple[int | bool | None, str | None]:
        """
        Read holding registers from the ModbusTCP server.
        name: The name of the endpoint to read.
        return: A tuple with the value and the datatype of the value.
        """
        endpoint = self.endpoints[name]
        address = endpoint['address']
        quantity = endpoint['quantity']
        bit_offset = endpoint['offset']

        # Create a read registers request
        request = self.client.read_holding_registers(address, quantity)
        if request is not None and bit_offset > -1:
            value = test_bit(request[0], bit_offset)
            datatype = "Boolean"# if bit_offset > -1 else "ByteString"
            return value, datatype
        elif request is not None and bit_offset == -1:
            return request[0], "UInt16"
        else:
            return None, None

    """
    Implementierung der Schreibefunktionen für das Verification-of-Request
    """
    def fc05_write_single_coil(self, name: str, value: bool) -> bool:
        """
        Write a single coil via FC05.
        name: The name of the endpoint to write.
        value: Boolean coil value.
        return: True on success, False on failure.
        """
        endpoint = self.endpoints.get(name)
        if endpoint is None:
            _logger.error("fc05_write_single_coil: unknown endpoint '%s'", name)
            return False
        address = endpoint['address']
        response = self.client.write_single_coil(address, value)
        if not response:
            _logger.error(
                "fc05_write_single_coil: write failed for endpoint '%s' (addr %s, value %s)",
                name, address, value,
            )
            return False
        return True

    # backwards-compat alias
    def write_coils(self, name: str, value: bool) -> bool:
        return self.fc05_write_single_coil(name, value)

    def write_single_register(self, name: str, value: int) -> bool:
        """Write a single holding register via FC06."""
        endpoint = self.endpoints.get(name)
        if endpoint is None:
            _logger.error("write_single_register: unknown endpoint '%s'", name)
            return False
        address = endpoint['address']
        response = self.client.write_single_register(address, value)
        if not response:
            _logger.error(
                "write_single_register: write failed for endpoint '%s' (addr %s, value %s)",
                name, address, value,
            )
            return False
        return True

    def write_registers(self, name: str, value: list[int]) -> bool:
        """Write multiple holding registers via FC16."""
        endpoint = self.endpoints.get(name)
        if endpoint is None:
            _logger.error("write_registers: unknown endpoint '%s'", name)
            return False
        address = endpoint['address']
        response = self.client.write_multiple_registers(address, value)
        if not response:
            _logger.error(
                "write_registers: write failed for endpoint '%s' (addr %s, value %s)",
                name, address, value,
            )
            return False
        return True