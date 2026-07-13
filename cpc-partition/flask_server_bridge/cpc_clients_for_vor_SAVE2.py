"""
------------------------------------------------------------
 Modul:    cpc-partition/flask_server_bridge/cpc_clients_for_vor.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    Client implementations for communication with the CPC in
    the context of the VoR framework (OPC UA + Modbus).

 Autor(en):
    - Heiko Schoon

 Maintainer:
    - Heiko Schoon <heiko.schoon@hs-emden-leer.de>

 Hinweis:
    Ongoing development.
------------------------------------------------------------
"""

from __future__ import annotations
import asyncio
import logging
from pathlib import Path
from typing import Any
from defusedxml import ElementTree as ET
import xmlschema
from asyncua import ua

# local imports:
from opcua_client import OpcUaClient
from modbus_tcp_client import ModbusTCPClient



_logger = logging.getLogger(__name__)

class OnDemandModbusTCPRegistry:
    """
    Builds Modbus TCP clients + endpoint lookup from xml config.

    Lookup keys:
      - Preferred:  "ServerAlias:Name"
      - Else (only if globally unique): "Name"

    Builds reverse index:
      Name -> [qualified keys]

    Stores:
      key -> (client, endpoint_meta)
    where endpoint_meta includes address/quantity/offset/function/type for dispatch.

    XSD validation is OPTIONAL: if XSD missing/unreadable, we log and continue.
    """

    def __init__(self, xml_config_path: str | Path, xsd_path: str | Path | None = None):
        self.xml_config_path = str(xml_config_path)
        self.xsd_path = str(xsd_path) if xsd_path else None

        self.clients: list[ModbusTCPClient] = []

        # key -> (client, endpoint_meta)
        self.endpoint_lookup: dict[str, tuple[ModbusTCPClient, dict[str, object]]] = {}

        # Name -> list of qualified keys
        self.name_to_keys: dict[str, list[str]] = {}

        self.duplicate_keys: set[str] = set()

        self._build()

    # compatibility: some older code expects .endpoints
    @property
    def endpoints(self) -> dict[str, tuple[ModbusTCPClient, dict[str, object]]]:
        return self.endpoint_lookup

    def _build(self) -> None:
        # Optional XSD validation
        if self.xsd_path:
            try:
                schema = xmlschema.XMLSchema(self.xsd_path)
                if not schema.is_valid(self.xml_config_path):
                    _logger.error("Modbus XML does not conform to XSD: %s", self.xml_config_path)
            except Exception as e:
                _logger.warning("Skipping Modbus XSD validation (XSD not accessible): %s", e)

        tree = ET.parse(self.xml_config_path)
        root = tree.getroot()

        seen_keys: set[str] = set()

        for server in root.findall("server"):
            ipaddr = (server.findtext("ipaddr") or "").strip()
            port_txt = (server.findtext("port") or "").strip()
            serveralias = (server.findtext("serveralias") or "").strip()

            if not ipaddr or not port_txt or not serveralias:
                continue

            port = int(port_txt)

            # Build per-server endpoints dict for ModbusTCPClient
            per_server_endpoints: dict[str, dict[str, str | int | bool]] = {}

            endpoints_elem = server.find("endpoints")
            if endpoints_elem is None:
                continue

            for ep in endpoints_elem.findall("endpoint"):
                name = (ep.findtext("name") or "").strip()
                function = (ep.findtext("function") or "").strip()
                address_txt = (ep.findtext("address") or "").strip()
                quantity_txt = (ep.findtext("quantity") or "").strip()
                offset_txt = (ep.findtext("offset") or "-1").strip()
                typ = (ep.findtext("type") or "").strip()
                desc = (ep.findtext("description") or "").strip()

                if not name or not address_txt or not quantity_txt:
                    continue

                address = int(address_txt)
                quantity = int(quantity_txt)
                offset = int(offset_txt) if offset_txt else -1
                read_target = (ep.findtext("read_target") or "").strip() or None

                per_server_endpoints[name] = {
                    "address": address,
                    "quantity": quantity,
                    "offset": offset,
                    "function": function,
                    "type": typ,
                    "description": desc,
                    "serveralias": serveralias,
                    "read_target": read_target,
                }

            client = ModbusTCPClient(ipaddr=ipaddr, port=port, serveralias=serveralias, endpoints=per_server_endpoints)
            self.clients.append(client)

            # Register endpoints into global lookup with qualified keys
            for name, meta in per_server_endpoints.items():
                key = f"{serveralias}:{name}"

                if key in seen_keys:
                    self.duplicate_keys.add(key)
                    _logger.warning("Duplicate Modbus registry key '%s'. Keeping first, skipping later.", key)
                    continue

                seen_keys.add(key)
                self.endpoint_lookup[key] = (client, meta)

                self.name_to_keys.setdefault(name, []).append(key)

        # normalize reverse index
        for n in list(self.name_to_keys.keys()):
            self.name_to_keys[n] = sorted(set(self.name_to_keys[n]))

        if self.duplicate_keys:
            _logger.warning("Duplicate keys detected in Modbus registry: %s", sorted(self.duplicate_keys))

        _logger.warning(
            "OnDemandModbusTCPRegistry built: %d clients, %d endpoints (lookup keys)",
            len(self.clients),
            len(self.endpoint_lookup),
        )

    # ---- resolving helpers -------------------------------------------------

    def resolve(self, name: str) -> str | None:
        """
        Resolve an incoming name to a registry key.

        Rules:
          1) if name exists as-is in endpoint_lookup -> return it
          2) if name looks like "Alias:Name" but not found -> None
          3) else treat as plain Name:
                - if exactly 1 key exists -> return it
                - if 0 or >1 keys -> None
        """
        if not name:
            return None

        if name in self.endpoint_lookup:
            return name

        if ":" in name:
            return None

        keys = self.name_to_keys.get(name, [])
        if len(keys) == 1:
            return keys[0]

        return None

    def resolve_many(self, names: list[str]) -> tuple[list[str], dict[str, dict]]:
        """
        Returns:
          (resolved_keys, errors)

        errors[name] includes:
          - unknown_endpoint
          - ambiguous_endpoint + candidates
        """
        resolved: list[str] = []
        errors: dict[str, dict] = {}

        for n in names:
            n = (n or "").strip()
            if not n:
                continue

            hit = self.resolve(n)
            if hit:
                resolved.append(hit)
                continue

            if ":" not in n:
                candidates = self.name_to_keys.get(n, [])
                if len(candidates) > 1:
                    errors[n] = {"status": "error", "reason": "ambiguous_endpoint", "candidates": candidates}
                else:
                    errors[n] = {"status": "error", "reason": "unknown_endpoint"}
            else:
                errors[n] = {"status": "error", "reason": "unknown_endpoint"}

        return sorted(set(resolved)), errors

    # ---- Modbus dispatch ---------------------------------------------------

    def _read_one(self, key: str) -> object | None:
        hit = self.endpoint_lookup.get(key)
        if hit is None:
            return None

        client, meta = hit
        fn = (meta.get("function") or "").strip().lower()
        # normalize common naming variants
        # (your XML has mixed: "Read Coils", "Read Coil Status", "Read Discrete Input", etc.)
        try:
            if "read coils" in fn or "read coil status" in fn:
                # FC01
                # meta stored under unqualified endpoint name in client.endpoints
                local_name = key.split(":", 1)[1]
                return client.fc01_read_coil_status(local_name)

            if "read discrete" in fn:
                # FC02
                local_name = key.split(":", 1)[1]
                return client.fc02_read_discrete_inputs(local_name)

            if "read holding" in fn:
                # FC03
                local_name = key.split(":", 1)[1]
                v, _dt = client.fc03_read_holding_registers(local_name)
                return v

            _logger.error("Unsupported Modbus read function for %s: %s", key, fn)
            return None
        except Exception as e:
            _logger.exception("Modbus read failed for %s: %s", key, e)
            # attempt reconnect throttled
            try:
                client.retry_connection()
            except Exception:
                pass
            return None

    def fetch(self, keys: list[str]) -> dict[str, object]:
        """
        Synchronous fetch. Returns dict[key] = value
        """
        results: dict[str, object] = {}
        for k in keys or []:
            results[k] = self._read_one(k)
        return results

    def write(self, values: dict[str, object], verify_readback: bool = True) -> dict[str, dict]:
        """
        Synchronous write with optional read-back verification.

        Returns per-key result dict, aligned with OPC UA style:
        {"status": "ok", ...} or {"status": "error", "reason": "...", ...}

        Modbus read/write split:
        In Brownfield devices the write address often differs from the read address
        (e.g. LOGO!: write FC05 to coil 8257, read back via FC01 from coil 8193).
        The Write-Endpoint carries an optional <read_target> element naming the
        corresponding Read-Endpoint.  If present, verify_readback uses that endpoint
        instead of reading back from the write address itself.
        """
        results: dict[str, dict] = {}

        for key, raw_val in (values or {}).items():
            hit = self.endpoint_lookup.get(key)
            if hit is None:
                results[key] = {"status": "error", "reason": "unknown_endpoint", "value": raw_val}
                continue

            client, meta = hit
            fn = (meta.get("function") or "").strip().lower()
            typ = (meta.get("type") or "").strip().lower()
            local_name = key.split(":", 1)[1]

            # --- resolve read_target for verify_readback ---
            read_target_name = (meta.get("read_target") or "").strip() or None
            rb_client = client
            rb_local = local_name
            rb_fn = fn
            if read_target_name:
                serveralias = (meta.get("serveralias") or "").strip()
                rt_qualified = f"{serveralias}:{read_target_name}" if serveralias else read_target_name
                rt_hit = self.endpoint_lookup.get(rt_qualified) or self.endpoint_lookup.get(read_target_name)
                if rt_hit is None:
                    _logger.error(
                        "read_target '%s' (resolved as '%s') not found in registry for key '%s'",
                        read_target_name, rt_qualified, key,
                    )
                    results[key] = {
                        "status": "error",
                        "reason": "read_target_not_found",
                        "read_target": read_target_name,
                        "value": raw_val,
                    }
                    continue
                rb_client, rb_meta = rt_hit
                rb_local = rt_qualified.split(":", 1)[1] if ":" in rt_qualified else read_target_name
                rb_fn = (rb_meta.get("function") or "").strip().lower()
                _logger.warning("Modbus verify readback: '%s' -> read_target '%s'", key, rt_qualified)

            try:
                # --- COILS -------------------------------------------------------
                if "write single coil" in fn:
                    # force boolean-ish
                    if isinstance(raw_val, bool):
                        v = raw_val
                    else:
                        s = str(raw_val).strip().lower()
                        v = s in ("1", "true", "yes", "y", "on")

                    ok = client.write_coils(local_name, v)
                    if not ok:
                        results[key] = {"status": "error", "reason": "write_failed", "value": v}
                        continue

                    if verify_readback:
                        if "read coils" in rb_fn or "read coil status" in rb_fn:
                            rb = rb_client.fc01_read_coil_status(rb_local)
                        elif "read discrete" in rb_fn:
                            rb = rb_client.fc02_read_discrete_inputs(rb_local)
                        else:
                            rb = rb_client.fc01_read_coil_status(rb_local)
                        if rb == v:
                            results[key] = {"status": "ok", "value": rb}
                        else:
                            results[key] = {
                                "status": "error",
                                "reason": "verification_failed",
                                "written": v,
                                "read_back": rb,
                            }
                    else:
                        results[key] = {"status": "ok", "value": v}
                    continue

                # --- HOLDING REGISTERS ------------------------------------------
                # FC06: Write Single Register
                if "write single register" in fn:
                    reg_val = int(raw_val) if not isinstance(raw_val, list) else int(raw_val[0])
                    ok = client.write_single_register(local_name, reg_val)
                    if not ok:
                        results[key] = {"status": "error", "reason": "write_failed", "value": reg_val}
                        continue
                    if verify_readback:
                        rb, _dt = rb_client.fc03_read_holding_registers(rb_local)
                        if rb == reg_val:
                            results[key] = {"status": "ok", "value": rb}
                        else:
                            results[key] = {
                                "status": "error",
                                "reason": "verification_failed",
                                "written": reg_val,
                                "read_back": rb,
                            }
                    else:
                        results[key] = {"status": "ok", "value": reg_val}
                    continue

                is_write_regs = (
                    ("write multiple registers" in fn)
                    or ("write registers" in fn)
                    or ("write register" in fn)
                )
                is_holding = ("holding" in fn) or ("holding" in typ)

                # allow writing if explicitly write-regs OR if endpoint is holding-regs
                if is_write_regs or is_holding:
                    # Modbus holding registers are 16-bit; client.write_multiple_registers expects list[int]
                    if isinstance(raw_val, list):
                        regs = [int(x) for x in raw_val]
                    else:
                        # IMPORTANT: this will truncate floats (e.g. 9.4 -> 9).
                        # If you need float32 packing or scaling, handle that before calling write().
                        regs = [int(raw_val)]

                    ok = client.write_registers(local_name, regs)
                    if not ok:
                        results[key] = {"status": "error", "reason": "write_failed", "value": regs}
                        continue

                    if verify_readback:
                        rb, _dt = rb_client.fc03_read_holding_registers(rb_local)
                        expected = regs[0] if regs else None
                        if rb == expected:
                            results[key] = {"status": "ok", "value": rb}
                        else:
                            results[key] = {
                                "status": "error",
                                "reason": "verification_failed",
                                "written": expected,
                                "read_back": rb,
                            }
                    else:
                        results[key] = {"status": "ok", "value": regs}
                    continue

                # --- UNSUPPORTED -------------------------------------------------
                results[key] = {
                    "status": "error",
                    "reason": f"unsupported_write_function({fn})",
                    "value": raw_val,
                }

            except Exception as e:
                _logger.exception("Modbus write failed for %s: %s", key, e)
                try:
                    client.retry_connection()
                except Exception:
                    pass
                results[key] = {"status": "error", "reason": "write_failed", "error": str(e), "value": raw_val}

        return results



class OnDemandOpcUaRegistry:
    """
    Builds OPC UA clients + node lookup from xml config.

    Lookup keys:
      - If NamespaceAlias present:  "NamespaceAlias:DisplayName"   (preferred)
      - Else:                       "DisplayName"                 (only if no alias exists)

    Additionally builds an index:
      DisplayName -> [qualified keys]
    so the bridge can resolve plain DisplayName coming from VoR.

    Stores datatype as string for safe casting before writes.
    XSD validation is OPTIONAL: if XSD missing/unreadable, we log and continue.
    """

    def __init__(self, xml_config_path: str | Path, xsd_path: str | Path | None = None):
        self.xml_config_path = str(xml_config_path)
        self.xsd_path = str(xsd_path) if xsd_path else None

        self.clients: list[OpcUaClient] = []

        # key -> (client, node_id, datatype)
        self.node_lookup: dict[str, tuple[OpcUaClient, ua.NodeId, str]] = {}

        # DisplayName -> list of registry keys that refer to it
        self.display_to_keys: dict[str, list[str]] = {}

        self.duplicate_keys: set[str] = set()

        self._build()

    # compatibility: older code referenced registry.endpoints
    @property
    def endpoints(self) -> dict[str, tuple[OpcUaClient, ua.NodeId, str]]:
        return self.node_lookup

    def _build(self) -> None:
        # Optional XSD validation
        if self.xsd_path:
            try:
                schema = xmlschema.XMLSchema(self.xsd_path)
                if not schema.is_valid(self.xml_config_path):
                    _logger.error("OPC UA XML does not conform to XSD: %s", self.xml_config_path)
            except Exception as e:
                _logger.warning("Skipping XSD validation (XSD not accessible): %s", e)

        tree = ET.parse(self.xml_config_path)
        root = tree.getroot()

        seen_keys: set[str] = set()

        for server in root.findall("server"):
            server_app_uri = server.findtext("server_app_uri")
            client_app_uri = server.findtext("client_app_uri")
            alias = server.findtext("alias")

            sec = server.find("security")
            security_settings = {
                "policy": sec.findtext("policy") if sec is not None else None,
                "mode": sec.findtext("mode") if sec is not None else None,
                "client_certificate": sec.findtext("client_certificate") if sec is not None else None,
                "client_private_key": sec.findtext("client_private_key") if sec is not None else None,
                "server_certificate": sec.findtext("server_certificate") if sec is not None else None,
                "username": sec.findtext("username") if sec is not None else None,
                "password": sec.findtext("password") if sec is not None else None,
            }

            client = OpcUaClient(server_app_uri, client_app_uri, alias, security_settings, nodes=[])
            self.clients.append(client)

            for node in server.findall("nodes/node"):
                display_name = (node.findtext("DisplayName") or "").strip()
                ns_alias = (node.findtext("NamespaceAlias") or "").strip()
                id_type = (node.findtext("IdentifierType") or "").strip()
                ns_idx_txt = node.findtext("NamespaceIndex")
                ident = (node.findtext("Identifier") or "").strip()

                if not display_name or not ns_idx_txt:
                    continue

                ns_idx = int(ns_idx_txt)

                datatype = (
                    node.findtext("datatype")
                    or node.findtext("DataType")
                    or node.findtext("Datatype")
                    or "String"
                ).strip()

                if id_type == "String":
                    node_id = ua.NodeId.from_string(f"ns={ns_idx};s={ident}")
                elif id_type == "Numeric":
                    node_id = ua.NodeId(int(ident), ns_idx)
                else:
                    raise NotImplementedError(f"IdentifierType {id_type} not supported")

                # POLICY: if alias exists, only register alias-qualified key
                if ns_alias:
                    key = f"{ns_alias}:{display_name}"
                else:
                    key = display_name

                if key in seen_keys:
                    self.duplicate_keys.add(key)
                    _logger.warning(
                        "Duplicate registry key '%s' (server=%s, node_id=%s). Keeping first, skipping later.",
                        key,
                        alias,
                        node_id,
                    )
                    continue

                seen_keys.add(key)
                self.node_lookup[key] = (client, node_id, datatype)

                # Build reverse index: DisplayName -> [keys]
                self.display_to_keys.setdefault(display_name, []).append(key)

        # Keep reverse index stable for logs/debug
        for dn in list(self.display_to_keys.keys()):
            self.display_to_keys[dn] = sorted(set(self.display_to_keys[dn]))

        if self.duplicate_keys:
            _logger.warning("Duplicate keys detected in registry: %s", sorted(self.duplicate_keys))

        _logger.warning(
            "OnDemandOpcUaRegistry built: %d clients, %d nodes (lookup keys)",
            len(self.clients),
            len(self.node_lookup),
        )

    # ---- resolving helpers -------------------------------------------------

    def resolve(self, name: str) -> str | None:
        """
        Resolve an incoming name to a registry key.

        Rules:
          1) if name exists as-is in node_lookup -> return name
          2) if name looks like "Alias:DisplayName" but not found -> None
          3) else treat as plain DisplayName:
                - if exactly 1 key exists -> return it
                - if 0 or >1 keys -> None
        """
        if not name:
            return None

        if name in self.node_lookup:
            return name

        # if caller already gave namespace but key doesn't exist
        if ":" in name:
            return None

        keys = self.display_to_keys.get(name, [])
        if len(keys) == 1:
            return keys[0]

        return None

    def resolve_many(self, names: list[str]) -> tuple[list[str], dict[str, dict]]:
        """
        Resolve multiple names.

        Returns:
          (resolved_keys, errors)

        errors[name] includes:
          - unknown_endpoint
          - ambiguous_endpoint + candidates
        """
        resolved: list[str] = []
        errors: dict[str, dict] = {}

        for n in names:
            n = (n or "").strip()
            if not n:
                continue

            hit = self.resolve(n)
            if hit:
                resolved.append(hit)
                continue

            # If plain DisplayName: check ambiguity candidates
            if ":" not in n:
                candidates = self.display_to_keys.get(n, [])
                if len(candidates) > 1:
                    errors[n] = {"status": "error", "reason": "ambiguous_endpoint", "candidates": candidates}
                else:
                    errors[n] = {"status": "error", "reason": "unknown_endpoint"}
            else:
                errors[n] = {"status": "error", "reason": "unknown_endpoint"}

        return sorted(set(resolved)), errors

    # ---- type casting / IO -------------------------------------------------

    def _cast_for_datatype(self, datatype: str, value: Any) -> ua.Variant:
        dt = (datatype or "String").strip().lower()

        if dt in ("bool", "boolean"):
            if isinstance(value, bool):
                b = value
            else:
                s = str(value).strip().lower()
                b = s in ("1", "true", "yes", "y", "on")
            return ua.Variant(b, ua.VariantType.Boolean)

        # IMPORTANT: Float != Python float (otherwise becomes Double)
        if dt == "float":
            return ua.Variant(float(value), ua.VariantType.Float)

        if dt == "double":
            return ua.Variant(float(value), ua.VariantType.Double)

        if dt == "int16":
            return ua.Variant(int(value), ua.VariantType.Int16)
        if dt == "uint16":
            return ua.Variant(int(value), ua.VariantType.UInt16)
        if dt in ("int32", "int", "integer"):
            return ua.Variant(int(value), ua.VariantType.Int32)
        if dt in ("uint32", "uint"):
            return ua.Variant(int(value), ua.VariantType.UInt32)
        if dt == "int64":
            return ua.Variant(int(value), ua.VariantType.Int64)
        if dt == "uint64":
            return ua.Variant(int(value), ua.VariantType.UInt64)

        return ua.Variant("" if value is None else str(value), ua.VariantType.String)

    async def fetch(self, var_names: list[str], timeout_s: float = 3.0) -> dict[str, Any]:
        by_client: dict[OpcUaClient, list[tuple[str, ua.NodeId]]] = {}

        for req_name in var_names:
            hit = self.node_lookup.get(req_name)
            if hit is None:
                continue
            client, node_id, _dt = hit
            by_client.setdefault(client, []).append((req_name, node_id))

        results: dict[str, Any] = {}

        async def _read_for_client(client: OpcUaClient, items: list[tuple[str, ua.NodeId]]):
            await client.connect()
            try:
                if not client.connected:
                    _logger.error("OPC UA client not connected: %s", getattr(client, "server_app_uri", "?"))
                    return
                for req_name, node_id in items:
                    _bn, value, _vt = await client.read_value(node_id)
                    results[req_name] = value
            finally:
                await client.disconnect()

        tasks = [asyncio.wait_for(_read_for_client(c, items), timeout=timeout_s) for c, items in by_client.items()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        return results

    async def write(self, values: dict[str, Any], timeout_s: float = 3.0) -> dict[str, dict]:
        by_client: dict[OpcUaClient, list[tuple[str, ua.NodeId, str, ua.Variant]]] = {}
        results: dict[str, dict] = {}

        for name, raw in (values or {}).items():
            hit = self.node_lookup.get(name)
            if hit is None:
                results[name] = {"status": "error", "reason": "unknown_endpoint", "value": raw}
                continue

            client, node_id, datatype = hit
            try:
                cast_val = self._cast_for_datatype(datatype, raw)
            except Exception as e:
                results[name] = {
                    "status": "error",
                    "reason": f"type_cast_failed({datatype})",
                    "error": str(e),
                    "value": raw,
                }
                continue

            by_client.setdefault(client, []).append((name, node_id, datatype, cast_val))

        async def _write_for_client(client: OpcUaClient, items: list[tuple[str, ua.NodeId, str, ua.Variant]]):
            await client.connect()
            try:
                if not client.connected:
                    for name, _nid, _dt, v in items:
                        results[name] = {"status": "error", "reason": "connect_failed", "value": v.Value}
                    return

                for name, node_id, datatype, v in items:
                    try:
                        await client.write_value(node_id, v)

                        # read-back verification
                        _bn, read_val, _vt = await client.read_value(node_id)

                        if read_val == v.Value:
                            results[name] = {"status": "ok", "value": read_val, "datatype": datatype}
                        else:
                            results[name] = {
                                "status": "error",
                                "reason": "verification_failed",
                                "written": v.Value,
                                "read_back": read_val,
                                "datatype": datatype,
                            }
                    except Exception as e:
                        results[name] = {
                            "status": "error",
                            "reason": "write_failed",
                            "error": str(e),
                            "datatype": datatype,
                            "value": v.Value,
                        }
            finally:
                await client.disconnect()

        tasks = [asyncio.wait_for(_write_for_client(c, items), timeout=timeout_s) for c, items in by_client.items()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        return results