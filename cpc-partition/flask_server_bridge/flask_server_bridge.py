"""
------------------------------------------------------------
 Modul:    cpc-partition/flask_server_bridge/flask_server_bridge.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from flask import Flask, request, Response, jsonify
from defusedxml import ElementTree as ET

from .cpc_clients_for_vor import OnDemandOpcUaRegistry

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


def resolve_config_paths() -> tuple[Path, Path | None]:
    candidates = [
        Path("/app/config"),
        Path("/app/flask_server_bridge/config"),
        Path("/app/cpc-partition/config"),
        Path(__file__).resolve().parent / "config",
        Path(__file__).resolve().parents[1] / "config",
        Path(__file__).resolve().parents[2] / "config",
    ]

    xml_name = "opcua-endpoints_demonstrator.xml"
    xsd_name = "opcua-endpoints.xsd"

    xml_path = None
    xsd_path = None

    for base in candidates:
        if xml_path is None and (base / xml_name).exists():
            xml_path = base / xml_name
        if xsd_path is None and (base / xsd_name).exists():
            xsd_path = base / xsd_name

    if xml_path is None:
        raise FileNotFoundError(
            f"Could not find {xml_name} in any of: {', '.join(str(c) for c in candidates)}"
        )

    if xsd_path is None:
        _logger.warning("XSD not found; will skip XSD validation for OPC UA XML.")

    _logger.warning("Using OPC UA XML: %s", xml_path)
    if xsd_path:
        _logger.warning("Using OPC UA XSD: %s", xsd_path)

    return xml_path, xsd_path


class FlaskServerBridge:
    def __init__(self):
        self.app = Flask(__name__)

        xml_path, xsd_path = resolve_config_paths()
        self.opcua_registry = OnDemandOpcUaRegistry(xml_path, xsd_path)

        @self.app.route("/read_values_xml", methods=["POST"])
        def read_values_xml():
            try:
                xml_data = request.data.decode("utf-8", errors="replace")
                root = ET.fromstring(xml_data)

                requested_names: list[str] = []

                # fixed map: keep VoR XML paths, but resolve to registry keys
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

                # affected endpoints: VoR may send plain DisplayName (e.g., MotorSpeed_SP)
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

                # resolve any plain DisplayName to unique qualified key
                resolved_keys, errors = self.opcua_registry.resolve_many(requested_names)

                if errors:
                    # If VoR requests unknown/ambiguous, answer 400 (better than silently N/A)
                    _logger.error("Name resolution errors: %s", errors)
                    return Response(
                        "<error>unknown_or_ambiguous_endpoint</error>",
                        mimetype="application/xml",
                        status=400,
                    )

                _logger.warning("Vars to fetch (resolved): %s", resolved_keys)

                if not resolved_keys:
                    return Response("<error>no variables requested</error>", mimetype="application/xml", status=400)

            except ET.ParseError as e:
                _logger.error("XML parse error: %s", e)
                return Response("<error>invalid xml</error>", mimetype="application/xml", status=400)
            except Exception as e:
                _logger.exception("Error parsing XML request: %s", e)
                return Response("<error>internal parse error</error>", mimetype="application/xml", status=500)

            try:
                fetched = asyncio.run(self.opcua_registry.fetch(resolved_keys, timeout_s=3.0))
            except Exception as e:
                _logger.exception("Error fetching values: %s", e)
                fetched = {}

            # --- fill fixed values (these are already qualified keys) ---
            try:
                for xpath, key in fixed_map:
                    elem = root.find(xpath)
                    if elem is not None:
                        elem.text = to_vor_text(fetched.get(key))

                # --- fill affected endpoints ---
                if affected is not None:
                    for ae in affected.findall("affected_endpoint"):
                        name_elem = ae.find("name")
                        value_elem = ae.find("value")
                        if name_elem is None or value_elem is None:
                            continue
                        raw_name = (name_elem.text or "").strip()
                        if not raw_name:
                            continue

                        resolved = self.opcua_registry.resolve(raw_name)
                        if not resolved:
                            # keep stable behavior: N/A if unknown
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

            # resolve incoming keys (VoR may send plain DisplayName)
            resolved_payload: dict[str, object] = {}
            errors: dict[str, dict] = {}

            for raw_key, val in data.items():
                rk = (raw_key or "").strip()
                resolved = self.opcua_registry.resolve(rk)
                if not resolved:
                    if ":" not in rk:
                        candidates = self.opcua_registry.display_to_keys.get(rk, [])
                        if len(candidates) > 1:
                            errors[rk] = {"reason": "ambiguous_endpoint", "candidates": candidates}
                        else:
                            errors[rk] = {"reason": "unknown_endpoint"}
                    else:
                        errors[rk] = {"reason": "unknown_endpoint"}
                    continue

                resolved_payload[resolved] = val

            if errors:
                _logger.error("update_endpoints resolution errors: %s", errors)
                return jsonify({"status": "error", "reason": "bad_endpoints", "details": errors}), 400

            try:
                results = asyncio.run(self.opcua_registry.write(resolved_payload, timeout_s=3.0))
                return jsonify(results), 200
            except Exception as e:
                _logger.exception("update_endpoints internal error: %s", e)
                return jsonify({"status": "error", "reason": "internal_error"}), 500

    def run(self, debug=False, threaded=True):
        self.app.run(debug=debug, host="0.0.0.0", port=5000, threaded=threaded)


if __name__ == "__main__":
    bridge = FlaskServerBridge()
    bridge.run()
