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

from flask import Flask, request, Response
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
            # BUG: Not implemented: Parse the XML to identify requested variables and their sources (OPC UA or Modbus)
            call_this = vor_5_placeholder()
            _logger.error(f"Called placeholder function: {call_this}")  
            try:
                # Decode the incoming XML data
                xml_data = request.data.decode('utf-8')  
                root = ET.fromstring(xml_data)   

                list_of_vars = []
                parent = "0:System1" # BUG Should be configurable
                for tag, key in [
                    ("key_personnel_present/current_value", "KeyPersonnelPresent"),
                    (".//technical_system[@id='System_1']/system_available/current_value", "SystemAvailable"),
                    (".//technical_system[@id='System_1']/operation_mode/current_value", "OperationMode"),
                    (".//technical_system[@id='System_1']/warning/current_value", "Warning"),
                ]:
                    _logger.warning(f"Processing tag: {tag} with key: {key}")
                    list_of_vars.append(key)
                    #elem = root.find(tag)
                    #_logger.warning(f"Found element: {elem} for tag: {tag}")
                    #if elem is not None:
                    #    elem.text = str("not implemented")  # BUG: Here, you would implement the logic to fetch the actual value from OPC UA or Modbus
                
                _logger.warning(f"List of vars to fetch: {list_of_vars}")

                dict_of_fetched_values = read_list_of_vars_from_opcua(placeholder_opcua_client(), list_of_vars) # BUG: Not completed
                # TODO: continue programming processing...

                affected_endpoints_elem = root.find('affected_endpoints')
                if affected_endpoints_elem is not None:
                    for affected_endpoint in affected_endpoints_elem.findall('affected_endpoint'):
                        name_elem = affected_endpoint.find('name')
                        value_elem = affected_endpoint.find('value')
                        if name_elem is not None and value_elem is not None:
                            var_name = name_elem.text
                            # BUG: Here, you would implement the logic to fetch the actual value from OPC UA or Modbus
                            print(f"Updated {var_name}: value = {value_elem.text}")

                # Convert the modified tree back to a string
                filled_xml = ET.tostring(root, encoding='utf-8', method='xml')

                # Return the updated XML
                _logger.info(f"Processed XML and returning response: {filled_xml.decode('utf-8')}")
                return Response(filled_xml, mimetype='application/xml')

            except Exception as e:
                _logger.error(f"Error processing XML: {e}")
                return Response(f"<error>{str(e)}</error>", mimetype='application/xml')


        @self.app.route('/update_endpoints', methods=['POST'])
        def update_endpoints():
            # BUG: Not implemented: Write the value back to the appropriate OPC UA or Modbus endpoint
            instead_call_this = vor_6_placeholder()
            _logger.error(f"Called placeholder function: {instead_call_this}")
            data = request.get_json(force=True)
            results = {}

            for var_name, value in data.items(): # BUG: check data format
                try:
                    results[var_name] = {"status": "ok", "value": value}
                except Exception as e:
                    results[var_name] = {"status": "error", "error": str(e)}
            return Response(f"Update results: {results}", mimetype='application/json')
            #return jsonify({"status": "done", "results": results}) # BUG: why use this instead of Response?
            
    def run(self, debug=False, threaded=True):
        self.app.run(debug=debug, host="0.0.0.0", port=5000, threaded=threaded)


if __name__ == '__main__':
    bridge = FlaskServerBridge()
    bridge.run()

# TODO: run OPC UA client and Flask server simultaneously by using mutithreading
# TODO: Inform the propagation frontend via the OPC UA client and Flask server that the next request can be pulled.
# frontend => request acceptance-variables from flask-server => grab values from OPC UA Clients => send to frontend
# frontend => send modifications => send to flask-server => implement in CPC => send feedback to frontend