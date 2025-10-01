from flask import Flask, request, Response
import xml.etree.ElementTree as ET

class FlaskServerBridge:
    def __init__(self):
        self.app = Flask(__name__) #BUG: WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
        @self.app.route('/process_xml', methods=['POST'])
        def process_xml():
            try:
                # Decode the incoming XML data
                xml_data = request.data.decode('utf-8')  
                root = ET.fromstring(xml_data)           

                # Provide corresponding data ('serve the dish') based on the XML file ('menu') provided by the Flask client.
                root.find("key_personnel_present/current_value").text = "true"
                root.find(".//technical_system[@id='System_1']/availability/current_value").text = "available"
                root.find(".//technical_system[@id='System_1']/operation_mode/current_value").text = "idle"
                root.find(".//technical_system[@id='System_1']/warning/current_value").text = "none"        
                
                # Iterate through all affected endpoints and update their values
                affected_endpoints_elem = root.find('affected_endpoints')
                if affected_endpoints_elem is not None:
                    for affected_endpoint in affected_endpoints_elem.findall('affected_endpoint'):
                        # Assign value of 10 for each affected endpoint
                        value_elem = affected_endpoint.find('value')
                        if value_elem is not None:
                            value_elem.text = '10'
                            
                            # Print to verify the assignment
                            name_elem = affected_endpoint.find('name')
                            print(f"Updated {name_elem.text}: value = {value_elem.text}")

                # Convert the modified tree back to a string
                filled_xml = ET.tostring(root, encoding='utf-8', method='xml')

                # Return the updated XML
                return Response(filled_xml, mimetype='application/xml')

            except Exception as e:
                return Response(f"<error>{str(e)}</error>", mimetype='application/xml')
            
    def run(self, debug=False, threaded=True):
        self.app.run(debug=debug, host="0.0.0.0", port=5000, threaded=threaded)


if __name__ == '__main__':
    bridge = FlaskServerBridge()
    bridge.run()

# TODO: run OPC UA client and Flask server simultaneously by using mutithreading
# TODO: Inform the propagation frontend via the OPC UA client and Flask server that the next request can be pulled.
# frontend => request acceptance-variables from flask-server => grab values from OPC UA Clients => send to frontend
# frontend => send modifications => send to flask-server => implement in CPC => send feedback to frontend