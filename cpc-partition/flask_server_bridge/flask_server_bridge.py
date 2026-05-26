"""
------------------------------------------------------------
 Modul:    cpc-partition/flask_server_bridge/flask_server_bridge.py
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

from flask import Flask, request, Response, jsonify
from defusedxml import ElementTree as ET
from config_loader import EndpointFiles
from .cpc_clients_for_vor import OnDemandOpcUaRegistry, OnDemandModbusTCPRegistry

_logger = logging.getLogger(__name__)


def to_vor_text(value) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, str):
        s = value.strip()
        return s if s else "N/A"
    return str(value)


"""def resolve_config_paths() -> tuple[Path, Path | None, Path, Path | None]:
    candidates = [
        Path(__file__).parent.parent / "config"
    ]

    # --- OPC UA ---
    opc_xml_name = "opcua-endpoints_demonstrator.xml"
    opc_xsd_name = "opcua-endpoints.xsd"

    # --- Modbus TCP ---
    mb_xml_name = "modbustcp-endpoints_demonstrator.xml"
    mb_xsd_name = "modbustcp-endpoints.xsd"

    opc_xml_path: Path | None = None
    opc_xsd_path: Path | None = None
    mb_xml_path: Path | None = None
    mb_xsd_path: Path | None = None

    for base in candidates:
        if opc_xml_path is None and (base / opc_xml_name).exists():
            opc_xml_path = base / opc_xml_name
        if opc_xsd_path is None and (base / opc_xsd_name).exists():
            opc_xsd_path = base / opc_xsd_name

        if mb_xml_path is None and (base / mb_xml_name).exists():
            mb_xml_path = base / mb_xml_name
        if mb_xsd_path is None and (base / mb_xsd_name).exists():
            mb_xsd_path = base / mb_xsd_name

    if opc_xml_path is None:
        raise FileNotFoundError(
            f"Could not find {opc_xml_name} in any of: {', '.join(str(c) for c in candidates)}"
        )

    if mb_xml_path is None:
        raise FileNotFoundError(
            f"Could not find {mb_xml_name} in any of: {', '.join(str(c) for c in candidates)}"
        )

    if opc_xsd_path is None:
        _logger.warning("OPC UA XSD not found; will skip XSD validation for OPC UA XML.")
    if mb_xsd_path is None:
        _logger.warning("Modbus XSD not found; will skip XSD validation for Modbus XML.")

    _logger.warning("Using OPC UA XML: %s", opc_xml_path)
    if opc_xsd_path:
        _logger.warning("Using OPC UA XSD: %s", opc_xsd_path)

    _logger.warning("Using Modbus XML: %s", mb_xml_path)
    if mb_xsd_path:
        _logger.warning("Using Modbus XSD: %s", mb_xsd_path)

    return opc_xml_path, opc_xsd_path, mb_xml_path, mb_xsd_path
"""

class FlaskServerBridge:
    def __init__(self, opcua_files: EndpointFiles, modbustcp_files: EndpointFiles):
        """
        Args:
            opcua_files:    CONFIG.opcua.files    (xml_config + xsd_schema paths)
            modbustcp_files: CONFIG.modbustcp.files (xml_config + xsd_schema paths)
        """
        self.app = Flask(__name__)
 
        # Paths come directly from config — no filesystem search needed
        self.opcua_registry  = OnDemandOpcUaRegistry(
            opcua_files.xml_config,
            opcua_files.xsd_schema,
        )
        self.modbus_registry = OnDemandModbusTCPRegistry(
            modbustcp_files.xml_config,
            modbustcp_files.xsd_schema,
        )

        def resolve_any(name: str) -> tuple[str | None, str | None]:
            """
            Resolve a VoR name to either OPC UA or Modbus.

            Returns (protocol, resolved_key)
              protocol in {"opcua", "modbus"} or (None, None) if not resolvable.
            """
            k1 = self.opcua_registry.resolve(name)
            if k1:
                return "opcua", k1
            k2 = self.modbus_registry.resolve(name)
            if k2:
                return "modbus", k2
            return None, None

        @self.app.route("/read_values_xml", methods=["POST"])
        def read_values_xml():
            try:
                xml_data = request.data.decode("utf-8", errors="replace")
                root = ET.fromstring(xml_data)

                requested_names: list[str] = []

                # fixed map: keep VoR XML paths, but resolve to registry keys (OPC UA in your current design)
                fixed_map = [
                    ("key_personnel_present/current_value", "TestObject:KeyPersonnelPresent"),
                    ("technical_system/availability/current_value", "TestObject:SystemAvailable"),
                    ("technical_system/operation_mode/current_value", "TestObject:OperationMode"),
                    ("technical_system/warning/current_value", "TestObject:Warning"),
                ]
                for xpath, key in fixed_map:
                    elem = root.find(xpath)
                    if elem is not None:
                        requested_names.append(key)

                # affected endpoints: VoR may send plain DisplayName (OPC) or plain endpoint name (Modbus)
                affected = root.find("affected_endpoints")
                if affected is not None:
                    for ae in affected.findall("affected_endpoint"):
                        name_elem = ae.find("name")
                        if name_elem is not None and name_elem.text:
                            n = name_elem.text.strip()
                            if n:
                                requested_names.append(n)

                requested_names = sorted(set(requested_names))
                _logger.warning("Vars requested (raw): %s", requested_names)

                # --- resolve requested names across OPC UA + Modbus ---
                opcua_req: list[str] = []
                modbus_req: list[str] = []
                errors: dict[str, dict] = {}

                for raw in requested_names:
                    proto, resolved = resolve_any(raw)
                    if resolved and proto == "opcua":
                        opcua_req.append(resolved)
                    elif resolved and proto == "modbus":
                        modbus_req.append(resolved)
                    else:
                        # Provide ambiguity info across BOTH registries
                        if ":" not in raw:
                            opc_candidates = self.opcua_registry.display_to_keys.get(raw, [])
                            mb_candidates = self.modbus_registry.name_to_keys.get(raw, [])
                            candidates = sorted(set(opc_candidates + mb_candidates))
                            if len(candidates) > 1:
                                errors[raw] = {
                                    "status": "error",
                                    "reason": "ambiguous_endpoint",
                                    "candidates": candidates,
                                }
                            else:
                                errors[raw] = {"status": "error", "reason": "unknown_endpoint"}
                        else:
                            errors[raw] = {"status": "error", "reason": "unknown_endpoint"}

                opcua_req = sorted(set(opcua_req))
                modbus_req = sorted(set(modbus_req))

                if errors:
                    _logger.error("Name resolution errors: %s", errors)
                    return Response(
                        "<error>unknown_or_ambiguous_endpoint</error>",
                        mimetype="application/xml",
                        status=400,
                    )

                _logger.warning("Vars to fetch (resolved) OPC UA: %s", opcua_req)
                _logger.warning("Vars to fetch (resolved) Modbus: %s", modbus_req)

                if not opcua_req and not modbus_req:
                    return Response("<error>no variables requested</error>", mimetype="application/xml", status=400)

            except ET.ParseError as e:
                _logger.error("XML parse error: %s", e)
                return Response("<error>invalid xml</error>", mimetype="application/xml", status=400)
            except Exception as e:
                _logger.exception("Error parsing XML request: %s", e)
                return Response("<error>internal parse error</error>", mimetype="application/xml", status=500)

            # --- fetch values from OPC UA (async) + Modbus (sync) ---
            fetched: dict[str, object] = {}

            if opcua_req:
                try:
                    fetched.update(asyncio.run(self.opcua_registry.fetch(opcua_req, timeout_s=3.0)))
                except Exception as e:
                    _logger.exception("Error fetching OPC UA values: %s", e)

            if modbus_req:
                try:
                    fetched.update(self.modbus_registry.fetch(modbus_req))
                except Exception as e:
                    _logger.exception("Error fetching Modbus values: %s", e)

            # --- fill XML response ---
            try:
                # fixed values (typically OPC UA qualified keys)
                for xpath, key in fixed_map:
                    elem = root.find(xpath)
                    if elem is not None:
                        # If someday fixed_map contains a plain name, resolve it too:
                        _proto, resolved = resolve_any(key)
                        elem.text = to_vor_text(fetched.get(resolved or key))

                # affected endpoints
                if affected is not None:
                    for ae in affected.findall("affected_endpoint"):
                        name_elem = ae.find("name")
                        value_elem = ae.find("value")
                        if name_elem is None or value_elem is None:
                            continue

                        raw_name = (name_elem.text or "").strip()
                        if not raw_name:
                            continue

                        _proto, resolved = resolve_any(raw_name)
                        if not resolved:
                            # stable behavior: N/A if unknown
                            value_elem.text = "N/A"
                            continue

                        value_elem.text = to_vor_text(fetched.get(resolved))

                filled_xml_bytes = ET.tostring(root, encoding="utf-8", method="xml")

            except Exception as e:
                _logger.exception("Error filling XML: %s", e)
                return Response("<error>failed to build response</error>", mimetype="application/xml", status=500)

            return Response(filled_xml_bytes, mimetype="application/xml", status=200)

        @self.app.route("/update_endpoints", methods=["POST"])
        def update_endpoints():
            data = request.get_json(force=True) or {}
            _logger.error("update_endpoints called with data: %s", data)

            opcua_payload: dict[str, object] = {}
            modbus_payload: dict[str, object] = {}
            errors: dict[str, dict] = {}

            for raw_key, val in (data or {}).items():
                rk = (raw_key or "").strip()
                proto, resolved = resolve_any(rk)

                if not resolved or not proto:
                    if ":" not in rk:
                        opc_candidates = self.opcua_registry.display_to_keys.get(rk, [])
                        mb_candidates = self.modbus_registry.name_to_keys.get(rk, [])
                        candidates = sorted(set(opc_candidates + mb_candidates))
                        if len(candidates) > 1:
                            errors[rk] = {"reason": "ambiguous_endpoint", "candidates": candidates}
                        else:
                            errors[rk] = {"reason": "unknown_endpoint"}
                    else:
                        errors[rk] = {"reason": "unknown_endpoint"}
                    continue

                if proto == "opcua":
                    opcua_payload[resolved] = val
                elif proto == "modbus":
                    modbus_payload[resolved] = val

            if errors:
                _logger.error("update_endpoints resolution errors: %s", errors)
                return jsonify({"status": "error", "reason": "bad_endpoints", "details": errors}), 400

            results: dict[str, dict] = {}

            # OPC UA writes (async)
            if opcua_payload:
                try:
                    results.update(asyncio.run(self.opcua_registry.write(opcua_payload, timeout_s=3.0)))
                except Exception as e:
                    _logger.exception("update_endpoints OPC UA internal error: %s", e)
                    return jsonify({"status": "error", "reason": "internal_error"}), 500

            # Modbus writes (sync)
            if modbus_payload:
                try:
                    results.update(self.modbus_registry.write(modbus_payload, verify_readback=True))
                except Exception as e:
                    _logger.exception("update_endpoints Modbus internal error: %s", e)
                    return jsonify({"status": "error", "reason": "internal_error"}), 500

            return jsonify(results), 200

    #def run(self, debug: bool = False, threaded: bool = True):
    #    self.app.run(debug=debug, host="0.0.0.0", port=5000, threaded=threaded)
    def run(self, debug: bool = False, threaded: bool = True, host: str = "0.0.0.0", port: int = 5000):
        self.app.run(debug=debug, host=host, port=port, threaded=threaded)


if __name__ == "__main__":
    bridge = FlaskServerBridge()
    bridge.run()
