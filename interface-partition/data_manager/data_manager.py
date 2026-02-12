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
import json
import logging
from queue import Empty, Queue
from typing import Any, Optional

from asyncua import Node, Server, ua

_logger = logging.getLogger(__name__)

_TYPE_MAP: dict[str, ua.VariantType] = {
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
    """
    Notes on RAM/CPU optimizations implemented here:
    - variables are stored as dict[name -> Node] for O(1) lookups
    - per-endpoint caches:
        - root folder node
        - group object nodes (no expensive get_child browse per update)
        - variable nodes (avoid re-creating / re-browsing)
        - last values (change detection) per endpoint to avoid collisions
    - cache reconciliation to prevent unbounded growth of caches when names change
    """

    def __init__(self, opcua_server: Server, opcua_queue: Queue, modbustcp_queue: Queue):
        self._server = opcua_server
        self._opcua_queue = opcua_queue
        self._modbustcp_queue = modbustcp_queue

        # Per-endpoint caches
        self._endpoint_ns: dict[str, int] = {}
        self._endpoint_root: dict[str, Node] = {}
        self._endpoint_objects: dict[str, dict[str, Node]] = {}  # endpoint -> group -> object node
        self._endpoint_vars: dict[str, dict[str, Node]] = {}     # endpoint -> fullName -> variable node
        self._last_values: dict[str, dict[str, tuple[Any, Any]]] = {}  # endpoint -> fullName -> (value, varType)

        # Light periodic housekeeping
        self._gc_counter: dict[str, int] = {}

    async def _get_message_from_queue(self, queue: Queue, timeout_s: float = 1.0) -> dict:
        """
        Non-blocking wrapper for stdlib Queue.get using a thread.
        """
        try:
            return await asyncio.to_thread(queue.get, True, timeout_s)
        except Empty:
            raise
        except Exception as e:
            _logger.error("Queue get error: %s", e)
            raise

    def _parse_payload(self, raw: Any) -> Any:
        """
        Accepts either a JSON string or a pre-parsed dict/list and returns it.
        """
        if raw is None:
            return {}
        if isinstance(raw, (dict, list)):
            return raw
        try:
            return json.loads(raw)
        except Exception as e:
            _logger.error("JSON parse error: %s", e)
            return {}

    async def _get_or_create_endpoint_root(self, endpoint_label: str) -> tuple[int, Node]:
        if endpoint_label not in self._endpoint_ns:
            self._endpoint_ns[endpoint_label] = await self._server.register_namespace(f"idx.{endpoint_label}.ua")

        # Ensure per-endpoint caches exist
        self._endpoint_objects.setdefault(endpoint_label, {})
        self._endpoint_vars.setdefault(endpoint_label, {})
        self._last_values.setdefault(endpoint_label, {})
        self._gc_counter.setdefault(endpoint_label, 0)

        idx = self._endpoint_ns[endpoint_label]

        root = self._endpoint_root.get(endpoint_label)
        if root is not None:
            return idx, root

        # We try to re-use existing root if present; this happens when server keeps address space.
        try:
            root = await self._server.nodes.objects.get_child(f"{idx}:{endpoint_label}")
        except Exception:
            root = await self._server.nodes.objects.add_object(idx, endpoint_label)

        self._endpoint_root[endpoint_label] = root
        return idx, root

    def _convert_value(self, varType: Any, value: Any) -> ua.Variant:
        try:
            vt = _TYPE_MAP[varType]
        except KeyError:
            raise ValueError(f"Unsupported varType: {varType!r}")
        return ua.Variant(value, vt)

    async def _create_opcua_objects(
        self,
        values: dict[str, dict[str, Any]],
        endpoint_label: str,
    ) -> dict[str, Node]:
        """
        Create OPC UA objects/variables for entries.

        values:
            { "<group>: <varname>": {"value": ..., "varType": ..., "description": ...}, ... }
        """
        created: dict[str, Node] = {}
        idx, root_obj = await self._get_or_create_endpoint_root(endpoint_label)

        obj_cache = self._endpoint_objects[endpoint_label]
        var_cache = self._endpoint_vars[endpoint_label]

        for full_name, varData in values.items():
            if ":" not in full_name:
                _logger.error("Error creating object for %s: No object name found.", full_name)
                continue

            group, var_name = full_name.split(":", 1)
            group = group.strip()
            var_name = var_name.strip()

            value = varData.get("value")
            varType = varData.get("varType")
            description = varData.get("description", "")

            if not varType:
                _logger.error("[%s] Missing varType for %s", endpoint_label, full_name)
                continue

            # If we already know this variable node, just return it
            existing_var = var_cache.get(full_name)
            if existing_var is not None:
                created[full_name] = existing_var
                continue

            try:
                # Get or create group object via cache (avoid get_child browse)
                group_obj = obj_cache.get(group)
                if group_obj is None:
                    group_obj = await root_obj.add_object(idx, group)
                    obj_cache[group] = group_obj

                # Create variable (if it already exists in address space but not in cache,
                # add_variable might raise; we catch and try a single get_child as fallback)
                converted_value = self._convert_value(varType, value)

                try:
                    var_node = await group_obj.add_variable(idx, var_name, converted_value)
                except Exception:
                    # Fallback: try to find existing var (one-time browse) and then set value
                    try:
                        var_node = await group_obj.get_child(f"{idx}:{var_name}")
                        await var_node.set_value(converted_value)
                    except Exception:
                        raise

                # Set description once
                try:
                    await var_node.write_attribute(
                        ua.AttributeIds.Description,
                        ua.DataValue(ua.Variant(ua.LocalizedText(description))),
                    )
                except Exception:
                    # non-fatal
                    _logger.debug("[%s] Failed to write description for %s", endpoint_label, full_name, exc_info=True)

                var_cache[full_name] = var_node
                created[full_name] = var_node

            except ValueError as e:
                _logger.error("[%s] Error converting value for %s: %s", endpoint_label, full_name, e)
            except Exception:
                _logger.exception("[%s] Error creating variable %s", endpoint_label, full_name)

        if created:
            _logger.info("[%s] Created %d variables", endpoint_label, len(created))
        return created

    def _reconcile_caches(self, endpoint_label: str, variables: dict[str, Node]) -> None:
        """
        Prevent silent cache growth when device mapping changes.
        Does not delete nodes in the UA server (that’s a separate lifecycle decision),
        but keeps our Python-side caches bounded to active names/groups.
        """
        # Prune last_values to active vars
        last = self._last_values.get(endpoint_label, {})
        if last:
            active = set(variables.keys())
            for k in list(last.keys()):
                if k not in active:
                    last.pop(k, None)

        # Prune variable cache to active vars
        var_cache = self._endpoint_vars.get(endpoint_label, {})
        if var_cache:
            active = set(variables.keys())
            for k in list(var_cache.keys()):
                if k not in active:
                    var_cache.pop(k, None)

        # Prune group object cache to groups that still exist in variables
        obj_cache = self._endpoint_objects.get(endpoint_label, {})
        if obj_cache:
            groups = {k.split(":", 1)[0].strip() for k in variables.keys() if ":" in k}
            for g in list(obj_cache.keys()):
                if g not in groups:
                    obj_cache.pop(g, None)

    async def create_population(
        self,
        queue: Queue,
        endpoint_label: str,
        max_wait_s: float = 20.0,
    ) -> Optional[dict[str, Node]]:
        """
        Wait for first valid message from queue and create initial population.
        Returns dict[name -> Node] on success, None on timeout.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_wait_s

        _logger.info("[%s] Waiting for first message (max %.1fs)...", endpoint_label, max_wait_s)
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

                    data = self._parse_payload(message.get("data"))
                    if isinstance(data, dict) and data:
                        _logger.info("[%s] Creating initial population from %s", endpoint_label, message.get("timestamp"))
                        variables = await self._create_opcua_objects(data, endpoint_label)

                        # Keep caches bounded to what is active right now
                        self._reconcile_caches(endpoint_label, variables)
                    else:
                        await asyncio.sleep(0.1)

                except Empty:
                    await asyncio.sleep(0.1)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _logger.exception("[%s] Error creating population from queue", endpoint_label)
                    await asyncio.sleep(0.1)

            return variables

        except asyncio.TimeoutError as e:
            _logger.error("%s", str(e))
            return None

    async def update_population(
        self,
        queue: Queue,
        variables: dict[str, Node],
        endpoint_label: str,
    ) -> None:
        """
        Periodically update OPC UA variables based on incoming queue messages.
        variables: dict[name -> Node] (mutated as it grows).
        """
        idx, _ = await self._get_or_create_endpoint_root(endpoint_label)  # ensure caches exist
        last = self._last_values[endpoint_label]

        while True:
            try:
                message = await self._get_message_from_queue(queue, timeout_s=1.0)

                data = message.get("data")
                if not isinstance(data, dict) or not data:
                    continue

                for name, entry in data.items():
                    if not isinstance(entry, dict):
                        continue

                    value = entry.get("value")
                    varType = entry.get("varType")
                    if not varType:
                        _logger.error("[%s] Missing varType for %s", endpoint_label, name)
                        continue

                    node = variables.get(name)

                    if node is not None:
                        new_value = (value, varType)
                        if last.get(name) == new_value:
                            continue
                        last[name] = new_value

                        try:
                            await node.set_value(self._convert_value(varType, value))
                        except Exception:
                            _logger.exception("[%s] Set value failed for %s", endpoint_label, name)
                    else:
                        # Create missing variable and cache it
                        try:
                            new_vars = await self._create_opcua_objects({name: entry}, endpoint_label)
                            if new_vars:
                                variables.update(new_vars)
                                # Seed change-detection cache
                                last[name] = (value, varType)
                        except Exception:
                            _logger.exception("[%s] Error adding %s", endpoint_label, name)

                # Periodic housekeeping: prune caches occasionally (cheap & prevents slow leaks)
                self._gc_counter[endpoint_label] += 1
                if self._gc_counter[endpoint_label] >= 200:
                    self._gc_counter[endpoint_label] = 0
                    self._reconcile_caches(endpoint_label, variables)

            except Empty:
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                raise
            except Exception:
                _logger.exception("[%s] Error updating variables from queue", endpoint_label)
                await asyncio.sleep(0.2)