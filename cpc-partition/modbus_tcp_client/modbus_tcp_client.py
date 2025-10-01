from pyModbusTCP.client import ModbusClient
from pyModbusTCP.utils import test_bit, set_bit
import logging
import time

_logger = logging.getLogger(__name__)

class ModbusTCPClient:
    def __init__(self, ipaddr: str, port: int, serveralias: str, endpoints: dict[str, dict[str, str | int | bool]]):
        self.ipaddr = ipaddr
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
        return: The value of the coil.
        """
        endpoint = self.endpoints[name]
        address = endpoint['address']
        quantity = endpoint['quantity']
        request = self.client.read_coils(address, quantity)
        return request[0]

    def fc02_read_discrete_inputs(self, name: str) -> bool | None:
        """
        Read discrete inputs from the ModbusTCP server.
        name: The name of the endpoint to read.
        return: The value of the discrete input.
        """
        endpoint = self.endpoints[name]
        address = endpoint['address']
        quantity = endpoint['quantity']
        request = self.client.read_discrete_inputs(address, quantity)
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

    # def write_coils(self, name, value):
    #     endpoint = self.endpoints[name]
    #     address = endpoint['address']

    #     # Create a write coils request
    #     response = self.client.write_single_coil(address, value)
    #     return response

    # def write_registers(self, name, value):
    #     endpoint = self.endpoints[name]
    #     address = endpoint['address']

    #     # Create a write registers request
    #     response = self.client.write_multiple_registers(address, value)
    #     return response