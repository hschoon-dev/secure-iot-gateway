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
import json
from multiprocessing import shared_memory
from asyncua import ua, Node, Server
import posix_ipc
import hashlib
from typing import Any

_logger = logging.getLogger(__name__)


class DataManager:
    def __init__(self, opcua_server: Server, opcua_shared_mem: str, opcua_semaphore: str,
                 modbus_shared_mem: str, modbus_semaphore: str):
        self._server = opcua_server
        self._opcua_shm = opcua_shared_mem
        self._opcua_sem = opcua_semaphore
        self._modbus_shm = modbus_shared_mem
        self._modbus_sem = modbus_semaphore

    async def _create_opcua_objects(self, shared_memory_values: dict[str, dict[str, str | int | float | bool]],
                                    opcua_object_name: str) -> list[tuple[str, Node | None]]:
        """
        Create OPC UA objects and variables from shared memory values
        :param shared_memory_values: Dictionary mapping variable names to their properties
                                    Each value is a dict with 'value', 'varType', and 'description' keys
        :param opcua_object_name: Name of the OPC UA object
        :return: List of OPC UA variables
        """
        opcua_variables = []
        _idx = await self._server.register_namespace(f"idx.{opcua_object_name}.ua")
        obj = await self._server.nodes.objects.add_object(_idx, opcua_object_name)

        for name, varData in shared_memory_values.items():
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


    async def create_opcua_population(self) -> list[tuple[str, Node | None]]:
        """
        Create the initial population of OPC UA variables from OPC UA shared memory
        """
        opcua_variables = []
        opcua_semaphore = None

        while opcua_variables == []:
            try:
                opcua_semaphore = posix_ipc.Semaphore(self._opcua_sem)
                opcua_shm = shared_memory.SharedMemory(name=self._opcua_shm)
                opcua_semaphore.acquire()
                opcua_variables = await self._create_opcua_objects(json.loads(bytes(opcua_shm.buf[:]).decode('utf-8').rstrip('\x00')), "opcua_shm")
                opcua_semaphore.release()
            except Exception as e:
                _logger.error(f"OPC UA: Error initializing shared memory while populating server: {e}")
                opcua_variables = []
                opcua_semaphore.release()
            await asyncio.sleep(0.1)
        return opcua_variables

    async def create_modbus_population(self) -> list[tuple[str, Node | None]]:
        """
        Create the initial population of OPC UA variables from Modbus TCP shared memory
        """
        modbus_variables = []
        modbus_semaphore = None

        while modbus_variables == []:
            try:
                modbus_semaphore = posix_ipc.Semaphore(self._modbus_sem)
                modbus_shm = shared_memory.SharedMemory(name=self._modbus_shm)
                modbus_semaphore.acquire()
                modbus_variables = await self._create_opcua_objects(json.loads(bytes(modbus_shm.buf[:]).decode('utf-8').rstrip('\x00')), "modbus_shm")
                modbus_semaphore.release()
            except Exception as e:
                _logger.error(f"ModbusTCP: Error initializing shared memory while populating server: {e}")
                modbus_variables = []
                modbus_semaphore.release()
            await asyncio.sleep(0.1)
        return modbus_variables
    

    async def update_population_from_opcua_shm(self, opcua_variables: list[tuple[str, Node | None]]) -> None:
        """
        Update the population of OPC UA variables from OPC UA shared memory
        :param opcua_variables: List of OPC UA variables
        """
        # Initialize values at the beginning
        opcua_values: dict[str, dict[str, Any]] = {}
        opcua_shm_response: str = ""
        opcua_semaphore = None
        try:
            opcua_semaphore = posix_ipc.Semaphore(self._opcua_sem)
            opcua_shm = shared_memory.SharedMemory(name=self._opcua_shm)
            opcua_shm_size = opcua_shm.size
            while True:
                try:
                    # Read the content from shared memory
                    if opcua_variables is not None:
                        opcua_semaphore.acquire()
                        opcua_values_json = bytes(opcua_shm.buf[:]).decode('utf-8').rstrip('\x00')
                        if opcua_values_json:

                            while opcua_values_json == opcua_shm_response:
                                opcua_semaphore.release()
                                await asyncio.sleep(.01)
                                opcua_semaphore.acquire()
                                opcua_values_json = bytes(opcua_shm.buf[:]).decode('utf-8').rstrip('\x00')
                            try:
                                opcua_values = json.loads(opcua_values_json)
                                _logger.debug(f"Shared Memory Content of {self._opcua_shm}: {json.dumps(opcua_values, indent=4)}")
                            except json.JSONDecodeError as e:
                                _logger.error(f"Error decoding JSON from shared memory: {e}")
                            opcua_shm_response = hashlib.sha256(opcua_values_json.encode()).hexdigest()
                            opcua_shm.buf[:opcua_shm_size] = b'\x00' * opcua_shm_size  # Clear the shared memory buffer
                            opcua_shm.buf[:len(opcua_shm_response)] = opcua_shm_response.encode('utf-8')
                        opcua_semaphore.release()
                        
                        if opcua_values:
                            list_a = [name for name, varData in opcua_values.items()]
                            list_b = [name for name, var_node in opcua_variables]
                            intersection = list(set(list_a) & set(list_b))
                            difference = list(set(list_a) - set(list_b))
                            _logger.debug(f"Intersection: {intersection}")
                            _logger.debug(f"Difference: {difference}")

                            for name, varData in opcua_values.items():
                                if name in intersection:
                                    value = varData['value']
                                    varType = varData['varType']
                                    for var_name, test_var in opcua_variables:
                                        if var_name == name:
                                            test_var: Node
                                            await test_var.set_value(self._convert_value(varType, value))

                                if name in difference:
                                    _logger.info(f"Adding new variable: {name}...")
                                    _idx = await self._server.register_namespace(f"idx.opcua_shm.ua")
                                    obj = await self._server.nodes.objects.get_child(f"{_idx}:opcua_shm")
                                    # inside the name there is the first word before ":" e.g., "Ecotec: AM13 Volumenstrom 2"
                                    # depending on this word, create a new object and add the variable to it
                                    # if the object already exists, add the variable to it
                                    if ":" in name:
                                        object_name = name.split(":", 1)[0]
                                        object_name_rest = name.split(":", 1)[1]
                                        try:
                                            new_obj = await obj.get_child(f"{_idx}:{object_name}")
                                        except Exception as e:
                                            _logger.info(f"Creating new object: {object_name}...")
                                            new_obj = await obj.add_object(_idx, object_name)
                                        try:
                                            converted_value = self._convert_value(varType, value)
                                            var = await new_obj.add_variable(_idx, object_name_rest, converted_value)
                                            opcua_variables.append((str(name), var))
                                        except ValueError as e:
                                            _logger.error(f"Error converting value for {name}: {e}")
                                            opcua_variables.append((str(name), None))
                                    else:
                                        _logger.error(f"Error creating object for {name}: No object name found.")

                    await asyncio.sleep(0.01)
                except Exception as e:
                    _logger.error(f"Error reading shared memory while updating server objects: {e}")

        except FileNotFoundError as e:
            _logger.error(f"Shared memory {e} not found.")
        except Exception as e:
            _logger.error(f"Error initializing shared memory while updating server objects: {e}")
            if opcua_semaphore is not None:
                opcua_semaphore.close()



    async def update_population_from_modbus_tcp_shm(self, modbus_tcp_variables: list[tuple[str, Node | None]]) -> None:
        """
        Update the population of OPC UA variables from Modbus TCP shared memory
        :param modbus_tcp_variables: List of OPC UA variables
        """
        # Initialize values at the beginning
        modbus_values: dict[str, dict[str, Any]] = {}
        modbus_shm_response: str = ""
        modbus_semaphore = None
        try:
            modbus_semaphore = posix_ipc.Semaphore(self._modbus_sem)
            modbus_shm = shared_memory.SharedMemory(name=self._modbus_shm)
            modbus_shm_size = modbus_shm.size
            while True:
                try:
                    # Read the content from shared memory
                    if modbus_tcp_variables is not None:
                        modbus_semaphore.acquire()
                        modbus_values_json = bytes(modbus_shm.buf[:]).decode('utf-8').rstrip('\x00')
                        if modbus_values_json:
                            while modbus_values_json == modbus_shm_response:
                                modbus_semaphore.release()
                                await asyncio.sleep(.01)
                                modbus_semaphore.acquire()
                                modbus_values_json = bytes(modbus_shm.buf[:]).decode('utf-8').rstrip('\x00')
                            try:
                                modbus_values = json.loads(modbus_values_json)
                                _logger.debug(f"Shared Memory Content of {self._modbus_shm}: {json.dumps(modbus_values, indent=4)}")
                            except json.JSONDecodeError as e:
                                _logger.error(f"Error decoding JSON from shared memory: {e}")
                            modbus_shm_response = hashlib.sha256(modbus_values_json.encode()).hexdigest()
                            modbus_shm.buf[:modbus_shm_size] = b'\x00' * modbus_shm_size  # Clear the shared memory buffer
                            modbus_shm.buf[:len(modbus_shm_response)] = modbus_shm_response.encode('utf-8')
                        modbus_semaphore.release()
                        
                        if modbus_values:
                            list_a = [name for name, varData in modbus_values.items()]
                            list_b = [name for name, var_node in modbus_tcp_variables]
                            intersection = list(set(list_a) & set(list_b))
                            difference = list(set(list_a) - set(list_b))
                            _logger.debug(f"Intersection: {intersection}")
                            _logger.debug(f"Difference: {difference}")

                            for name, varData in modbus_values.items():
                                if name in intersection:
                                    value = varData['value']
                                    varType = varData['varType']
                                    for var_name, test_var in modbus_tcp_variables:
                                        if var_name == name:
                                            test_var: Node
                                            await test_var.set_value(self._convert_value(varType, value))
                                if name in difference:
                                    _logger.info(f"Adding new variable: {name}...")
                                    _idx = await self._server.register_namespace(f"idx.modbus_shm.ua")
                                    obj = await self._server.nodes.objects.get_child(f"{_idx}:modbus_shm")

                                    # inside the name there is the first word before ":" e.g., "Ecotec: AM13 Volumenstrom 2"
                                    # depending on this word, create a new object and add the variable to it
                                    # if the object already exists, add the variable to it
                                    if ":" in name:
                                        object_name = name.split(":", 1)[0]
                                        object_name_rest = name.split(":", 1)[1]
                                        try:
                                            new_obj = await obj.get_child(f"{_idx}:{object_name}")
                                        except Exception as e:
                                            _logger.info(f"Creating new object: {object_name}...")
                                            new_obj = await obj.add_object(_idx, object_name)

                                        try:
                                            converted_value = self._convert_value(varType, value)
                                            var = await new_obj.add_variable(_idx, object_name_rest, converted_value)
                                            modbus_tcp_variables.append((str(name), var))
                                        except ValueError as e:
                                            _logger.error(f"Error converting value for {name}: {e}")
                                            modbus_tcp_variables.append((str(name), None))
                                    else:
                                        _logger.error(f"Error creating object for {name}: No object name found.")

                    await asyncio.sleep(0.01)
                except Exception as e:
                    _logger.error(f"Error reading shared memory while updating server objects: {e}")

        except FileNotFoundError as e:
            _logger.error(f"Shared memory {e} not found.")
        except Exception as e:
            _logger.error(f"Error initializing shared memory while updating server objects: {e}")
            if modbus_semaphore is not None:
                modbus_semaphore.close()


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