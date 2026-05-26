"""
------------------------------------------------------------
 Modul:    intermediate-vor-partition-cpc/main.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    This script serves as the main entry point for the
    intermediate VoR partition of the Secure IoT Gateway.
    It handles pulling requests from a MariaDB database,
    processing them through acceptance and mapping verification,
    and providing feedback to the interface partition.
    
    MIGRATION: Replaced TinyDB (JSON on NFS) with MariaDB for
    safe concurrent access from multiple virtualized systems.

 Autor(en):
    - Yuanchen Zhao (developer for the VoR framework)
    - Heiko Schoon (edited monolithic code into this module
      and prepared it for containerized environment)

 Maintainer:
    - tbd

 Hinweis:
    Ongoing development. Now uses MariaDB for safer concurrent access.
------------------------------------------------------------
"""

from datetime import datetime
import requests
import xml.etree.ElementTree as ET
import os
import sys
import threading
import time
import logging
from logging.handlers import RotatingFileHandler

# local imports
from db_manager import DatabaseManager

# TODO: should be in .env
DB_HOST="192.168.178.117"
DB_PORT=3306
DB_USER="iot_gateway"
DB_PASSWORD="your_secure_password"
DB_NAME="secure_iot_gateway"

path = os.path.dirname(os.path.abspath(__file__))
acceptance_ruleset_path = os.path.join(path, "config/Acceptance_Ruleset.xml")
acceptance_ruleset_path_modified = os.path.join(path, "config/Acceptance_Ruleset_modified.xml")

logging_path = os.path.join(path, "logs/app.log")

# ============================================================================
# Database Configuration (update with your actual MariaDB credentials)
# ============================================================================
DB_HOST = os.getenv("DB_HOST", "192.168.1.100")  # Pi with MariaDB
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "iot_gateway")
DB_PASSWORD = os.getenv("DB_PASSWORD", "your_secure_password")
DB_NAME = os.getenv("DB_NAME", "secure_iot_gateway")


def setup_logging(
    log_level=logging.WARNING,
    log_file="default.log",
    max_bytes=1 * 1024 * 1024,  # 1 MB
    backup_count=3,
) -> logging.Logger:
    """
    Configure logging with console and rotating file handler.
    """
    log_format = (
        "[%(asctime)s] [%(levelname)-8s] "
        "[%(name)s:%(lineno)d] - %(message)s"
    )
    date_format = "%Y-%m-%d %H:%M:%S"

    formatter = logging.Formatter(log_format, datefmt=date_format)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # Rotating file handler
    print(f"Logging to file: {log_file}")
    file_handler = RotatingFileHandler(
        #log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    # Root logger config
    logging.basicConfig(
        level=log_level,
        handlers=[console_handler, file_handler],
    )
    return logging.getLogger(__name__)

_logger = setup_logging(
    log_level=logging.WARNING,
    log_file=CONFIG.logging.log_file,
    max_bytes=CONFIG.logging.max_bytes,
    backup_count=CONFIG.logging.backup_count,
)


def initialize_database() -> DatabaseManager:
    """
    Initialize the database manager with MariaDB connection pool.
    
    Returns:
        DatabaseManager instance
        
    Raises:
        Exception if database connection fails
    """
    try:
        db_manager = DatabaseManager(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            pool_size=5,
        )
        _logger.info("Database manager initialized successfully")
        return db_manager
    except Exception as e:
        _logger.critical(f"Failed to initialize database: {e}")
        raise


def pull_request(db_manager: DatabaseManager) -> dict | None:
    """
    Pull the highest priority request from MariaDB database.
    
    The stored procedure `get_next_request()` ensures atomic retrieval
    and deletion, preventing data corruption under concurrent access.
    
    Args:
        db_manager: DatabaseManager instance
        
    Returns:
        Request dictionary or None if no requests exist
    """
    try:
        request_dict = db_manager.pull_next_request()
        
        if request_dict:
            _logger.debug(f"Pulled request: {request_dict['request_id']}")
            
            # Ensure affected_endpoint_list is a list of tuples
            if isinstance(request_dict.get("affected_endpoint_list"), list):
                request_dict["affected_endpoint_list"] = [
                    tuple(item) if isinstance(item, (list, tuple)) else item
                    for item in request_dict["affected_endpoint_list"]
                ]
        else:
            _logger.debug("No requests found in database")
            
        return request_dict
        
    except Exception as e:
        _logger.error(f"Error pulling request from database: {e}")
        return None


def read_xml_file(filename: str) -> str:
    """
    Read XML file from disk.
    """
    with open(filename, "r", encoding="utf-8") as file:
        return file.read()


def add_affected_endpoints_to_xml(xml_data, affected_endpoints):
    """
    Add affected endpoint information to XML structure.
    """
    root = ET.fromstring(xml_data)

    # Create the 'affected_endpoints' node if not exists
    affected_endpoints_elem = ET.SubElement(root, "affected_endpoints")

    for endpoint in affected_endpoints:
        endpoint_elem = ET.SubElement(affected_endpoints_elem, "affected_endpoint")

        # Create 'name' and 'value' nodes inside 'affected_endpoint'
        name_elem = ET.SubElement(endpoint_elem, "name")
        name_elem.text = endpoint[0]  # Set the name to the first item in the tuple

        value_elem = ET.SubElement(endpoint_elem, "value")
        value_elem.text = "0"  # Set the initial value to 0

    # Return the updated XML string
    updated_xml = ET.tostring(root, encoding="utf-8").decode("utf-8")

    # Save the modified XML to a new file for debugging
    with open(acceptance_ruleset_path_modified, "w", encoding="utf-8") as file:
        file.write(updated_xml)

    return updated_xml


def send_request(xml_data) -> str | None:
    """
    Send request to Flask server bridge (CPC partition).
    """
    url = "http://192.168.178.114:5000/read_values_xml"

    headers = {"Content-Type": "application/xml"}
    try:
        response = requests.post(url, data=xml_data, headers=headers, timeout=10)

        if response.status_code == 200:
            _logger.debug(f"Response status code: {response.status_code}")
            _logger.debug(f"Response content: {response.text}")
            return response.text  # type: str
        else:
            _logger.error(f"Error: {response.status_code} - {response.text}")
            return None
    except requests.RequestException as e:
        _logger.error(f"Request failed: {e}")
        return None


def acceptance_verification(xml_data):
    """
    Verify that request acceptance criteria are met.
    
    Checks that current values match required values in the XML structure.
    """
    # Generate an Element object, which is the root node of the XML tree
    root = ET.fromstring(xml_data)

    all_passed = True

    def verify_values(element, path=""):
        nonlocal all_passed
        current = None
        required = None

        # Iterate all the child nodes of the current node.
        for child in element:
            child_path = f"{path}/{child.tag}" if path else child.tag

            if child.tag == "current_value":
                current = child.text.strip()
            elif child.tag == "required_value":
                required = child.text.strip()
            else:
                verify_values(child, child_path)

            # If a mismatch is found, exit immediately and return.
            if not all_passed:
                return

        if current is not None and required is not None:
            if current != required:
                key_name = path.split("/")[-1] if "/" in path else path
                if "technical_system" in path:
                    _logger.warning(
                        f"The request is not accepted: {key_name} in technical_system, current='{current}'"
                    )
                else:
                    _logger.warning(
                        f"The request is not accepted: {key_name}, current='{current}'"
                    )
                all_passed = False

    # Start mapping verification from the root element
    verify_values(root)

    if all_passed:
        _logger.info(
            "The request is accepted and forwarded to the mapping verification step."
        )
    else:
        _logger.warning(
            "The request is not accepted and won't be forwarded to the mapping verification step."
        )
    return all_passed


def mapping_verification(request, xml_data):
    """
    Verify mapping constraints and calculate effective endpoint values.
    """
    # request.affected_endpoint_list
    root = ET.fromstring(xml_data)

    # Extract the variables and their values into a dictionary
    affected_endpoints_values = {}
    for endpoint in root.findall(".//affected_endpoint"):
        name = endpoint.find("name").text
        value = float(endpoint.find("value").text)  # current process value
        _logger.debug(f"\n name: {name}, value: {value}")
        affected_endpoints_values[name] = value

    all_passed = True

    affected_endpoint_dict = affected_endpoints_values.copy()

    # Calculate the effective value based on the provided process value, or set the effective value according to
    # the preset value, and use the effective value to validate the mapping verification constraints
    for endpoint in request["affected_endpoint_list"]:
        change_type: str
        condition: str
        name, change_type, _, condition = endpoint
        value = affected_endpoints_values.get(name)

        if value is not None:
            if "relative" in change_type:
                percent_change = float(
                    change_type.split(",")[1].strip().replace("%", "")
                )  # strip deletes spaces
                process_value = value * (1 + percent_change / 100)
                affected_endpoint_dict[name] = process_value
            else:
                process_value = float(change_type.split(",")[1].strip())
                affected_endpoint_dict[name] = process_value
        else:
            # If we can't resolve the current value, fail safe
            all_passed = False
            break

        if "==" in condition:
            check_value = float(condition.split("==")[1].strip())
            if process_value != check_value:
                all_passed = False
                break
        elif "<=" in condition:
            check_value = float(condition.split("<=")[1].strip())
            if process_value > check_value:
                all_passed = False
                break
        elif ">=" in condition:
            check_value = float(condition.split(">=")[1].strip())
            if process_value < check_value:
                all_passed = False
                break
        elif "<" in condition:
            check_value = float(condition.split("<")[1].strip())
            if process_value >= check_value:
                all_passed = False
                break
        elif ">" in condition:
            check_value = float(condition.split(">")[1].strip())
            if process_value <= check_value:
                all_passed = False
                break

    if all_passed:
        _logger.info(
            "Completed: The request was verified through the mapping verification step and the mapped CPC endpoints "
            "were accepted and forwarded to the CPC system or component responsible for effecting the described change."
        )
    else:
        _logger.warning(
            "Not completed: The request failed the mapping verification step and the described change won't be Implemented."
        )
        return None
    return affected_endpoint_dict


def send_back_results(affected_endpoints_dict):
    """
    Send results back to Flask server bridge for CPC system.
    """
    try:
        _logger.info(f"Sending back to Flask server: {affected_endpoints_dict}")
        url = "http://192.168.178.114:5000/update_endpoints"
        headers = {"Content-Type": "application/json"}
        #response = requests.post(
        #    url, json=affected_endpoints_dict, headers=headers, timeout=5
        #)
        response = requests.post(
            url, json=affected_endpoints_dict, headers=headers,
            timeout=CONFIG.flask_bridge.timeout_seconds
        )
    except requests.RequestException as e:
        _logger.error(f"Error sending back to Flask server: {e}")
        return
    except Exception as e:
        _logger.error(f"Unexpected error: {e}")
        return

    if response.ok:
        # Try to parse JSON – if not possible, log text
        try:
            _logger.info(f"Response from Flask server: {response.json()}")
        except ValueError:
            _logger.info(
                f"Response from Flask server (non-JSON body): {response.text!r}"
            )
    else:
        _logger.error(
            f"Failed to send back to Flask server: {response.status_code} - {response.text}"
        )


def pull_request_and_process(db_manager: DatabaseManager):
    """
    Main processing loop: pull requests from MariaDB and process them.
    """
    time.sleep(2)

    while True:
        try:
            # Pull the highest priority request from the database
            request = pull_request(db_manager)

            if request is not None:
                xml_data = read_xml_file(acceptance_ruleset_path)

                try:
                    # Add affected endpoints to the XML data
                    xml_data_with_endpoints = add_affected_endpoints_to_xml(
                        xml_data, request["affected_endpoint_list"]
                    )

                    filled_xml = send_request(xml_data_with_endpoints)
                except Exception as e:
                    _logger.error(f"Error sending request to Flask server: {e}")
                    filled_xml = None

                if filled_xml and acceptance_verification(filled_xml):
                    try:
                        affected_endpoints_dict = mapping_verification(request, filled_xml)
                        _logger.info(f"Affected endpoints dict: {affected_endpoints_dict}")
                    except Exception as e:
                        _logger.error(f"Error during mapping verification: {e}")
                        affected_endpoints_dict = None

                    if affected_endpoints_dict is not None:
                        try:
                            send_back_results(affected_endpoints_dict)
                        except Exception as e:
                            _logger.error(f"Error sending back results to Flask server: {e}")

            if request is None:
                time.sleep(0.5)  # Sleep for a short duration to avoid busy waiting
        except Exception as e:
            _logger.error(f"An error occurred: {e}")


def main():
    """
    Main entry point that initializes the database and starts the request processor.
    """
    try:
        # Initialize database connection pool
        db_manager = initialize_database()
        _logger.info("Database connection pool initialized")
    except Exception as e:
        _logger.critical(f"Failed to initialize database: {e}")
        sys.exit(1)

    # Start the request processing in a separate thread
    processor_thread = threading.Thread(
        target=pull_request_and_process, 
        args=(db_manager,), 
        daemon=True
    )
    processor_thread.start()
    _logger.info("Request processor started in background thread")

    # Keep the main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _logger.info("Shutting down gracefully...")
        sys.exit(0)


if __name__ == "__main__":
    main()