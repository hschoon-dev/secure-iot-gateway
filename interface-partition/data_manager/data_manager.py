"""
------------------------------------------------------------
 Modul:    interface-partition/data_manager.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    This module contains a data manager that handles the
    interaction between an OPC UA server and shared memory.
    It creates OPC UA objects and variables based on the
    contents of shared memory and updates them as needed.
    It supports both OPC UA and Modbus TCP shared memory as
    well as data type conversions.

 Autor(en):
    - Heiko Schoon

 Maintainer:
    - Heiko Schoon <heiko.schoon@hs-emden-leer.de>

 Hinweis:
    Ongoing development.
------------------------------------------------------------
"""

import asyncio
import logging
from asyncua import ua, Node, Server
from queue import Queue, Empty

_logger = logging.getLogger(__name__)


class DataManager:
    def __init__(self, opcua_server: Server, 
                 opcua_queue: Queue,
                 modbustcp_queue: Queue):
        self._server = opcua_server
        self._opcua_queue = opcua_queue
        self._modbustcp_queue = modbustcp_queue

    async def _create_opcua_objects(self, values: dict[str, dict[str, str | int | float | bool]],
                                    opcua_object_name: str) -> list[tuple[str, Node | None]]:
        """
        Create OPC UA objects and variables from shared memory values
        :param values: Dictionary mapping variable names to their properties
                                    Each value is a dict with 'value', 'varType', and 'description' keys
        :param opcua_object_name: Name of the OPC UA object
        :return: List of OPC UA variables
        """
        opcua_variables = []
        _idx = await self._server.register_namespace(f"idx.{opcua_object_name}.ua")
        obj = await self._server.nodes.objects.add_object(_idx, opcua_object_name)

        for name, varData in values.items():
            value = varData['value']
            varType = varData['varType']
            description = varData['description']
            # inside the name there is the first word before ":" e.g., "Ecotec: AM13 Volumenstrom 2"
            # depending on this word, create a new object and add the variable to it
            # if the object already exists, add the variable to it
            if ":" in name:
                object_name = name.split(":", 1)[0]
                object_name_rest = name.split(":", 1)[1]
                try:
                    new_obj = await obj.get_child(f"{_idx}:{object_name}")
                except Exception as e:
                    _logger.warning(f"Creating new object: {object_name}...")#
                    new_obj = await obj.add_object(_idx, object_name)                
                try:
                    converted_value = self._convert_value(varType, value)
                    var = await new_obj.add_variable(_idx, object_name_rest, converted_value)
                    await var.write_attribute(ua.AttributeIds.Description, 
                                              ua.DataValue(ua.Variant(ua.LocalizedText(description))))
                    opcua_variables.append((str(name), var))
                except ValueError as e:
                    _logger.error(f"Error converting value for {name}: {e}")
                    opcua_variables.append((str(name), None))
            else:
                _logger.error(f"Error creating object for {name}: No object name found.")
        _logger.debug(f"Initial OPC UA Variables: {opcua_variables}")
        return opcua_variables


    async def create_opcua_population(self, queue: Queue) -> list[tuple[str, Node | None]]:    
        """
        Waits for first valid message from queue and creates initial OPC UA population.
        """
        _logger.info("Waiting for first message...")
        variables = []
        while not variables:
            try:
                message = queue.get(timeout=1.0)
                _logger.info(f"Got message from queue: {type(message)}")
                _logger.info(f"{message}")
                if message["data"] is not None: # BUG Error creating population from queue: 'str' object has no attribute 'items'
                    _logger.info(f"Creating initial population for OPC UA from message {message['timestamp']}")
                    variables = await self._create_opcua_objects(message["data"], f"opcua_queue")
            except Empty:
                await asyncio.sleep(0.1)
            except Exception as e:
                _logger.error(f"Error creating population from queue: {e}")
        return variables

    async def create_modbustcp_population(self, queue: Queue) -> list[tuple[str, Node | None]]:
        """
        Waits for first valid message from queue and creates initial OPC UA population.
        """
        _logger.info("Waiting for first message...")
        variables = []
        while not variables:
            try:
                #message = queue.get(timeout=1.0)
                message = await asyncio.to_thread(queue.get, True, 1.0)
                _logger.info(f"Got message from queue: {type(message)}")
                if message["data"] is not None:
                    _logger.info(f"Creating initial population for OPC UA from message {message['timestamp']}")
                    variables = await self._create_opcua_objects(message["data"], f"modbustcp_queue")
            except Empty:
                await asyncio.sleep(0.1)
            except Exception as e:
                _logger.error(f"Error creating population from queue: {e}")
        return variables
    

    async def update_population_from_opcua_queue(self, queue: Queue, opcua_variables: list[tuple[str, Node | None]]) -> None:
        """Periodically updates OPC UA variables based on incoming queue messages."""
        while True:
            try:
                #message = queue.get(timeout=1.0)
                message = await asyncio.to_thread(queue.get, True, 1.0)
                data = message["data"]
                _logger.debug(f"Updating with message from {message['timestamp']}")

                list_a = list(data.keys())
                list_b = [name for name, _ in opcua_variables]
                intersection = set(list_a) & set(list_b)
                difference = set(list_a) - set(list_b)

                for name in intersection:
                    value = data[name]['value']
                    varType = data[name]['varType']
                    for var_name, node in opcua_variables:
                        if var_name == name and node is not None:
                            await node.set_value(self._convert_value(varType, value))

                for name in difference:
                    _logger.info(f"Adding new variable {name}")
                    new_vars = await self._create_opcua_objects({name: data[name]}, f"opcua_queue")
                    opcua_variables.extend(new_vars)

            except Empty:
                await asyncio.sleep(0.1)
            except Exception as e:
                _logger.error(f"Error updating variables from queue: {e}")
                await asyncio.sleep(0.5)



    async def update_population_from_modbustcp_queue(self, queue: Queue, modbus_tcp_variables: list[tuple[str, Node | None]]) -> None:
        """Periodically updates OPC UA variables based on incoming queue messages."""
        while True:
            try:
                message = queue.get(timeout=1.0)
                data = message["data"]
                _logger.debug(f"Updating with message from {message['timestamp']}")

                list_a = list(data.keys())
                list_b = [name for name, _ in modbus_tcp_variables]
                intersection = set(list_a) & set(list_b)
                difference = set(list_a) - set(list_b)

                for name in intersection:
                    value = data[name]['value']
                    varType = data[name]['varType']
                    for var_name, node in modbus_tcp_variables:
                        if var_name == name and node is not None:
                            await node.set_value(self._convert_value(varType, value))

                for name in difference:
                    _logger.info(f"Adding new variable {name}")
                    new_vars = await self._create_opcua_objects({name: data[name]}, f"opcua_queue")
                    modbus_tcp_variables.extend(new_vars)

            except Empty:
                await asyncio.sleep(0.1)
            except Exception as e:
                _logger.error(f"Error updating variables from queue: {e}")
                await asyncio.sleep(0.5)


    def _convert_value(self, varType: str, value: str | int | float | bool) -> ua.Variant:
        """
        Convert the value to the appropriate OPC UA data type
        :param varType: OPC UA data type
        :param value: Value to convert
        :return: Converted value
        """
        if varType == "Boolean":
            return ua.Variant(value, ua.VariantType.Boolean)
        elif varType == "Float":
            return ua.Variant(value, ua.VariantType.Float)
        elif varType == "Int64":
            return ua.Variant(value, ua.VariantType.Int64)
        elif varType == "UInt32":
            return ua.Variant(value, ua.VariantType.UInt32)
        elif varType == "Byte":
            return ua.Variant(value, ua.VariantType.Byte)
        elif varType == "Int32":
            return ua.Variant(value, ua.VariantType.Int32)
        elif varType == "Int16":
            return ua.Variant(value, ua.VariantType.Int16)
        elif varType == "UInt16":
            return ua.Variant(value, ua.VariantType.UInt16)
        elif varType == "String":
            return ua.Variant(value, ua.VariantType.String)
        # Add other conversions as needed
        else:
            raise ValueError(f"Unsupported varType: {varType}")