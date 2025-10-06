"""
------------------------------------------------------------
 Modul:    cpc-partition/flask_server_bridge.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    This module contains a Flask server that acts as a bridge
    between the VoR framework and the cpc-partition.

 Autor(en):
    - Yuanchen Zhao (basic implementation of the Flask server)
    - Heiko Schoon (integration in Docker and modularization
      of the code)

 Maintainer:
    - Heiko Schoon <heiko.schoon@hs-emden-leer.de>

 Hinweis:
    Ongoing development. Not all functions are fully implemented.
    Flask server is for development and testing purposes only.
    Security aspects (e.g., authentication, encryption) are not
    fully addressed. Will be replaced by a gRPC server with mTLS.
------------------------------------------------------------
"""

from flask import Flask, app, request, Response, jsonify
from defusedxml import ElementTree as ET
import logging

# local import 
from .cpc_clients_for_vor import vor_5_placeholder, vor_6_placeholder, read_list_of_vars_from_opcua, placeholder_opcua_client

_logger = logging.getLogger(__name__)

class FlaskServerBridge:
    def __init__(self):
        self.app = Flask(__name__) #BUG: WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.           

        @self.app.route('/read_values_xml', methods=['POST'])
        def read_values_xml():
            # ------------------------------------------------------------
            # 1) Request-XML parsen → Variablenliste bauen
            # ------------------------------------------------------------
            try:
                xml_data = request.data.decode('utf-8', errors='replace')
                root = ET.fromstring(xml_data)  # <ruleset>…</ruleset>

                list_of_vars = []

                # feste Variablen nach deiner Logik/Benennung
                # Mapping: XML → OPC-UA-Variablenname
                fixed_map = [
                    # (<XPath auf current_value>, <OPC-UA-Var>)
                    ("key_personnel_present/current_value", "KeyPersonnelPresent"),
                    ("technical_system/availability/current_value", "SystemAvailable"),
                    ("technical_system/operation_mode/current_value", "OperationMode"),
                    ("technical_system/warning/current_value", "Warning"),
                ]
                for xpath, var in fixed_map:
                    elem = root.find(xpath)
                    if elem is not None:
                        list_of_vars.append(var)

                # dynamische Endpunkte
                affected = root.find("affected_endpoints")
                if affected is not None:
                    for ae in affected.findall("affected_endpoint"):
                        name_elem = ae.find("name")
                        if name_elem is not None and name_elem.text:
                            var_name = name_elem.text.strip()
                            if var_name:
                                list_of_vars.append(var_name)

                # deduplizieren, Reihenfolge egal
                list_of_vars = sorted(set(list_of_vars))
                _logger.debug(f"Vars to fetch: {list_of_vars}")

                if not list_of_vars:
                    return Response("<error>no variables requested</error>",
                                    mimetype="application/xml", status=400)

            except ET.ParseError as e:
                _logger.error(f"XML parse error: {e}")
                return Response("<error>invalid xml</error>", mimetype="application/xml", status=400)
            except Exception as e:
                _logger.exception(f"Error parsing XML request: {e}")
                return Response("<error>internal parse error</error>", mimetype="application/xml", status=500)

            # ------------------------------------------------------------
            # 2) Werte EINMALIG von OPC UA holen (hier: nur OPC UA; Modbus optional)
            #    – mit einfachem Timeout-Schutz
            # ------------------------------------------------------------
            DUMMY = {
                # feste Variablen
                "KeyPersonnelPresent": "true",          # aus OPC UA Bool oder string? capitalization? BUG: YYeesssssss!
                "SystemAvailable": "available",       # String/Enum
                "OperationMode": "idle",              # String/Enum
                "Warning": "none",                    # String/Enum

                # affected_endpoints (aus <name>)
                "Mixer_SP_Pump_A_Power": 8.0,           # int/float je nach Knoten-Typ
                "Pump_A_Power_Pump_A_Power": 8.0,
                "Pump_B_Power_Pump_A_Power": 8.0,
                "Heater_Power_Pump_A_Power": 8.0,
            }
            try:
                #client = placeholder_opcua_client()

                #async def _fetch():
                #    return await read_list_of_vars_from_opcua(client, list_of_vars)

                dict_of_fetched_values = DUMMY
                #try: #BUG: Flask does not support asyncio natively, so this might not work as intended.
                #    dict_of_fetched_values = await asyncio.wait_for(_fetch(), timeout=3.0)
                #except asyncio.TimeoutError:
                #    _logger.error("OPC UA fetch timed out")
                #    dict_of_fetched_values = {}
            except Exception as e:
                _logger.exception(f"Error fetching values: {e}")
                dict_of_fetched_values = {}

            if not dict_of_fetched_values:
                # Wir antworten konsistent mit N/A, statt komplett abzubrechen
                _logger.warning("No values fetched; returning N/A placeholders.")

            # ------------------------------------------------------------
            # 3) Antwort-XML befüllen (eingehendes XML wird überschrieben)
            #    - feste Felder
            #    - affected_endpoints
            #    Fehlende Werte → "N/A"
            # ------------------------------------------------------------
            try:
                # feste Variablen füllen
                fill_pairs = [
                    ("key_personnel_present/current_value", "KeyPersonnelPresent"),
                    ("technical_system/availability/current_value", "SystemAvailable"),
                    ("technical_system/operation_mode/current_value", "OperationMode"),
                    ("technical_system/warning/current_value", "Warning"),
                ]
                for xpath, var in fill_pairs:
                    elem = root.find(xpath)
                    if elem is not None:
                        val = dict_of_fetched_values.get(var, "N/A")
                        elem.text = str(val)

                # dynamische Endpunkte füllen
                affected = root.find("affected_endpoints")
                if affected is not None:
                    for ae in affected.findall("affected_endpoint"):
                        name_elem = ae.find("name")
                        value_elem = ae.find("value")
                        if name_elem is None or value_elem is None:
                            continue
                        var_name = (name_elem.text or "").strip()
                        if not var_name:
                            continue
                        value_elem.text = str(dict_of_fetched_values.get(var_name, "N/A"))

                filled_xml_bytes = ET.tostring(root, encoding='utf-8', method='xml')

            except Exception as e:
                _logger.exception(f"Error filling XML: {e}")
                return Response("<error>failed to build response</error>",
                                mimetype='application/xml', status=500)

            # ------------------------------------------------------------
            # 4) Response zurückgeben
            # ------------------------------------------------------------
            return Response(filled_xml_bytes, mimetype='application/xml', status=200)


        @self.app.route('/update_endpoints', methods=['POST'])
        def update_endpoints():
            # ------------------------------------------------------------
            # 1) Request-JSON parsen → Variablenliste bauen # BUG: Wieso jetzt plötzlich JSON???
            # ------------------------------------------------------------
            # BUG: Not implemented: Write the value back to the appropriate OPC UA or Modbus endpoint
            #instead_call_this = await vor_6_placeholder()
            #_logger.error(f"Called placeholder function: {instead_call_this}")
            data = request.get_json(force=True)
            _logger.error(f"update_endpoints called with data: {data}")

            # ------------------------------------------------------------
            # 2) Werte EINMALIG schreiben
            # ------------------------------------------------------------
            # BUG: Here the endpoints for OPC UA or Modbus should be determined from data
            opc_ua_endpoints = []
            modbus_endpoints = []
            # ... 
            results = {}
            # results = _write_values_to_opcua_and_modbus(opc_ua_endpoints, modbus_endpoints)


            # ------------------------------------------------------------
            # 4) Response zurückgeben
            # ------------------------------------------------------------
            # BUG: For now, we just echo back the received values with a dummy "ok" status
            results = {var_name: {"status": "ok", "value": value} for var_name, value in data.items()}
            return jsonify(results), 200

            
    def run(self, debug=False, threaded=True):
        self.app.run(debug=debug, host="0.0.0.0", port=5000, threaded=threaded)


if __name__ == '__main__':
    bridge = FlaskServerBridge()
    bridge.run()

# TODO: run OPC UA client and Flask server simultaneously by using mutithreading
# TODO: Inform the propagation frontend via the OPC UA client and Flask server that the next request can be pulled.
# frontend => request acceptance-variables from flask-server => grab values from OPC UA Clients => send to frontend
# frontend => send modifications => send to flask-server => implement in CPC => send feedback to frontend