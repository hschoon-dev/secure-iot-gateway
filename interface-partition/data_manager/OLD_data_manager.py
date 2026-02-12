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
from asyncua import ua, Node, Server
from queue import Queue, Empty
from typing import Optional

_logger = logging.getLogger(__name__)

_TYPE_MAP = {
    "Boolean": ua.VariantType.Boolean,
    "Float": ua.VariantType.Float,
    "Int64": ua.VariantType.Int64,
    "UInt32": ua.VariantType.UInt32,
    "Byte": ua.VariantType.Byte,
    "Int32": ua.VariantType.Int32,
    "Int16": ua.VariantType.Int16,
    "UInt16": ua.VariantType.UInt16,
    "String": ua.VariantType.String,
}


class DataManager:
    def __init__(self, opcua_server: Server, 
                 opcua_queue: Queue,
                 modbustcp_queue: Queue):
        self._server = opcua_server
        self._opcua_queue = opcua_queue
        self._modbustcp_queue = modbustcp_queue
        self._endpoint_ns: dict[str, int] = {}
        self._endpoint_root: dict[str, Node] = {}
        self._last_values: dict[str, tuple] = {}
        self._endpoint_objects: dict[str, dict[str, Node]] = {}

    async def _create_opcua_objects(self,
        values: dict[str, dict[str, str | int | float | bool]],
        opcua_object_name: str
    #) -> list[tuple[str, Node | None]]:
    ) -> dict[str, Node]:
        """
        Create OPC UA objects and variables from shared memory values.
        values: { "<group>: <varname>": {"value": ..., "varType": ..., "description": ...}, ... }
        """
        #opcua_variables: list[tuple[str, Node | None]] = []
        opcua_variables: dict[str, Node] = {}
        #_idx = await self._server.register_namespace(f"idx.{opcua_object_name}.ua")
        #root_obj = await self._server.nodes.objects.add_object(_idx, opcua_object_name)

        _idx, root_obj = await self._get_or_create_endpoint_root(opcua_object_name)

        for name, varData in values.items():
            value = varData.get('value')
            varType = varData.get('varType')
            description = varData.get('description', "")

            if ":" not in name:
                _logger.error(f"Error creating object for {name}: No object name found.")
                continue

            object_name, object_name_rest = name.split(":", 1)
            object_name_rest = object_name_rest.strip()

            try:
                obj_cache = self._endpoint_objects[opcua_object_name]
                new_obj = obj_cache.get(object_name)

                if new_obj is None:
                    new_obj = await root_obj.add_object(_idx, object_name)
                    obj_cache[object_name] = new_obj

                converted_value = self._convert_value(varType, value)
                var = await new_obj.add_variable(_idx, object_name_rest, converted_value)
                await var.write_attribute(
                    ua.AttributeIds.Description,
                    ua.DataValue(ua.Variant(ua.LocalizedText(description)))
                )
                #opcua_variables.append((str(name), var))
                opcua_variables[name] = var
            except ValueError as e:
                _logger.error(f"Error converting value for {name}: {e}")
                #opcua_variables.append((str(name), None))
                #opcua_variables[name] = None # im dict nicht notwendig

        _logger.info("[%s] Created %d variables", opcua_object_name, len(opcua_variables))
        return opcua_variables

    async def _get_message_from_queue(self, queue: Queue, timeout_s: float = 1.0) -> dict:
        """
        Non-blocking wrapper for stdlib Queue.get using a thread to keep the event loop responsive.
        The event loop now always consumes queue.get() via asyncio.to_thread(...), so the blocking 
        call happens in a worker thread, not in the event loop.
        """
        try:
            message = await asyncio.to_thread(queue.get, True, timeout_s)
            return message
        except Empty:
            raise
        except Exception as e:
            _logger.error(f"Queue get error: {e}")
            raise

    def _parse_payload(self, raw) -> dict:
        """
        Accepts either a JSON string or a pre-parsed dict and returns a dict.
        """
        if raw is None:
            return {}
        if isinstance(raw, (dict, list)):
            return raw
        try:
            return json.loads(raw)
        except Exception as e:
            _logger.error(f"JSON parse error: {e}")
            return {}
        
    async def _get_or_create_endpoint_root(self, endpoint_label: str) -> tuple[int, Node]:
        if endpoint_label not in self._endpoint_ns:
            self._endpoint_ns[endpoint_label] = await self._server.register_namespace(f"idx.{endpoint_label}.ua")
        if endpoint_label not in self._endpoint_objects:
            self._endpoint_objects[endpoint_label] = {}
        idx = self._endpoint_ns[endpoint_label]

        root = self._endpoint_root.get(endpoint_label)
        if root is not None:
            return idx, root

        try:
            root = await self._server.nodes.objects.get_child(f"{idx}:{endpoint_label}")
        except Exception:
            root = await self._server.nodes.objects.add_object(idx, endpoint_label)

        self._endpoint_root[endpoint_label] = root
        return idx, root
    
    async def create_population(
        self,
        queue: Queue,
        endpoint_label: str,
        max_wait_s: float = 20.0,
    #) -> Optional[list[tuple[str, Node | None]]]:
    ) -> Optional[dict[str, Node]]:
        """
        Wait for first valid message from queue and create initial population.

        Returns:
        - list[...] on success
        - None on timeout (after logging an error)
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_wait_s

        _logger.info(f"[{endpoint_label}] Waiting for first message (max {max_wait_s}s)...")
        #variables: list[tuple[str, Node | None]] = []
        variables: dict[str, Node] = {}

        try:
            while not variables:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError(
                        f"[{endpoint_label}] Timed out after {max_wait_s}s waiting for first valid message."
                    )

                per_try_timeout = min(1.0, remaining)

                try:
                    message = await self._get_message_from_queue(queue, timeout_s=per_try_timeout)
                    _logger.info(f"[{endpoint_label}] Got message: type={type(message)}")

                    data = self._parse_payload(message.get("data"))
                    if data:
                        _logger.info(f"[{endpoint_label}] Creating initial population from {message.get('timestamp')}")
                        variables = await self._create_opcua_objects(data, endpoint_label)
                    else:
                        await asyncio.sleep(0.1)

                except Empty:
                    await asyncio.sleep(0.1)

                except asyncio.CancelledError:
                    raise  # don't swallow cancellation

                except Exception:
                    _logger.exception(f"[{endpoint_label}] Error creating population from queue")
                    await asyncio.sleep(0.1)

            return variables

        except asyncio.TimeoutError as e:
            _logger.error(str(e))
            return None

    """async def update_population(
        self,
        queue: Queue,
        variables: list[tuple[str, Node | None]],
        endpoint_label: str
    ) -> None:

        #Periodically update OPC UA variables based on incoming queue messages.
        #`variables` is the live list returned by create_population (mutated on growth).

        while True:
            try:
                message = await self._get_message_from_queue(queue, timeout_s=1.0)
                data = self._parse_payload(message.get("data"))
                if not isinstance(data, dict) or not data:
                    continue

                _logger.warning(f"[{endpoint_label}] Updating with message from {message.get('timestamp')}")

                names_in_data = set(data.keys())
                names_in_server = {name for name, _ in variables}

                intersection = names_in_data & names_in_server
                additions = names_in_data - names_in_server

                # Update existing
                if intersection:
                    # Build a map once for faster lookup
                    var_map = {name: node for name, node in variables}
                    for name in intersection:
                        entry = data[name]
                        value = entry.get('value')
                        varType = entry.get('varType')
                        node = var_map.get(name)
                        if node is not None:
                            try:
                                await node.set_value(self._convert_value(varType, value))
                            except Exception as e:
                                _logger.error(f"[{endpoint_label}] Set value failed for {name}: {e}")

                # Add new variables
                for name in additions:
                    _logger.info(f"[{endpoint_label}] Adding new variable {name}")
                    try:
                        new_vars = await self._create_opcua_objects({name: data[name]}, endpoint_label)
                        variables.extend(new_vars)
                    except Exception as e:
                        _logger.error(f"[{endpoint_label}] Error adding {name}: {e}")

            except Empty:
                await asyncio.sleep(0.1)
            except Exception as e:
                _logger.error(f"[{endpoint_label}] Error updating variables from queue: {e}")
                await asyncio.sleep(0.5)"""

    async def update_population(
        self,
        queue: Queue,
        variables: dict[str, Node],
        endpoint_label: str
    ) -> None:

        while True:
            try:
                message = await self._get_message_from_queue(queue, timeout_s=1.0)
                data = message.get("data")
                if not isinstance(data, dict) or not data:
                    continue

                for name, entry in data.items():
                    value = entry.get("value")
                    varType = entry.get("varType")
                    node = variables.get(name)

                    if node is not None:
                        new_value = (value, varType)
                        # Change detection AFTER node check
                        if self._last_values.get(name) == new_value:
                            continue

                        self._last_values[name] = new_value

                        try:
                            await node.set_value(
                                self._convert_value(varType, value)
                            )
                        except Exception:
                            _logger.exception("[%s] Set value failed for %s", endpoint_label, name)

                    else:
                        try:
                            new_vars = await self._create_opcua_objects(
                                {name: entry},
                                endpoint_label
                            
                            )
                            variables.update(new_vars)
                            self._last_values[name] = (value, varType)

                        except Exception:
                            _logger.exception("[%s] Error adding %s", endpoint_label, name)

            except Empty:
                await asyncio.sleep(0.05)



    def _convert_value(self, varType, value):
        try:
            return ua.Variant(value, _TYPE_MAP[varType])
        except KeyError:
            raise ValueError(f"Unsupported varType: {varType}")