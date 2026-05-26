"""
------------------------------------------------------------
 Modul:    interface-partition/main.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    This script serves as the main entry point for the
    intermediate VoR partition of the Secure IoT Gateway.
    It handles pulling requests from a TinyDB database,
    processing them through acceptance and mapping verification,
    and providing feedback (not implemented yet) to the
    interface partition.
    The communication with the cpc-partition is temporarily
    handled via HTTP requests to a Flask server bridge.

 Autor(en):
    - Yuanchen Zhao (developer for the VoR framework)
    - Heiko Schoon (edited monolithic code into this module
      and prepared it for use in a containerized environment)

 Maintainer:
    - tbd

 Hinweis:
    Ongoing development. Flask server bridge is a temporary solution.
    Future work will focus on implementing a more robust communication
    mechanism between the partitions using gRPC with mTLS.
------------------------------------------------------------
"""

#import json
from datetime import datetime
import requests
import xml.etree.ElementTree as ET
import os
import sys
import threading
import time
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from tinydb import TinyDB, Query
from tinydb.storages import JSONStorage
from tinydb.middlewares import CachingMiddleware

# local imports
from config_loader import load_config, VoRCPCConfig

CONFIG = load_config(
    path=Path(__file__).parent / "config/settings.yaml",
    base_dir=Path(__file__).parent,
)

#path = os.path.dirname(os.path.abspath(__file__))
#acceptance_ruleset_path = os.path.join(path, "config/Acceptance_Ruleset.xml")
#acceptance_ruleset_path_modified = os.path.join(path, "config/Acceptance_Ruleset_modified.xml")

# NOTE: keep variable name for compatibility, but now it points to a TinyDB JSON file
#mapped_rq_database_path = os.path.join(path, "mnt/mapped_requests.json")
#mapped_rq_database_path = "/mnt/mapped_requests.json"
acceptance_ruleset_path          = CONFIG.acceptance_rulesets.ruleset
acceptance_ruleset_path_modified = CONFIG.acceptance_rulesets.ruleset_modified
mapped_rq_database_path          = CONFIG.database.db_path

#logging_path = os.path.join(path, "logs/app.log")

def setup_logging(
    log_level=logging.WARNING,
    log_file="default.log",
    max_bytes=1 * 1024 * 1024,  # 1 MB
    backup_count=3
    ) -> logging.Logger:

    # Common log format
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


def _open_tinydb():
    """
    Open TinyDB with caching enabled to reduce I/O.
    Caller must close() the returned db.
    """
    return TinyDB(mapped_rq_database_path, storage=CachingMiddleware(JSONStorage))


def _safe_datetime_from_any(value):
    """
    Best-effort conversion to datetime, matching the old sqlite workflow:
    - if ISO string -> datetime.fromisoformat
    - else return as-is if already datetime
    - else raise ValueError
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise ValueError(f"Unsupported timestamp type: {type(value)!r}")


# Pull the highest priority request from the database, and when there are multiple with the same highest priority,
# pull them in chronological order.
# TODO: change database method to a gRPC approach
def pull_request() -> dict | None:
    """
    TinyDB equivalent of:
        SELECT * FROM mapped_requests ORDER BY priority, generation_timestamp LIMIT 1
        DELETE FROM mapped_requests WHERE request_id = ?
    """
    db = None
    try:
        db = _open_tinydb()
        table = db.table("mapped_requests")

        rows = table.all()
        if not rows:
            _logger.debug("No records found in the database.")
            return None

        # Sort by priority (ascending) then generation_timestamp (ascending)
        # generation_timestamp can be stored as datetime, ISO string, or something else.
        def sort_key(doc):
            prio = doc.get("priority", 0)
            ts_raw = doc.get("generation_timestamp")
            try:
                ts = _safe_datetime_from_any(ts_raw)
            except Exception:
                # Put unparsable timestamps at the end deterministically
                ts = datetime.max
            return (prio, ts)

        rows.sort(key=sort_key)
        doc = rows[0]

        # Reformat the request into a dictionary for easier processing later
        # Keep behavior compatible with old sqlite-based code.
        request_dict = {
            "request_id": doc.get("request_id"),
            "generation_timestamp": _safe_datetime_from_any(doc.get("generation_timestamp")),
            "description": doc.get("description"),
            "impact": doc.get("impact"),
            "priority": doc.get("priority"),
            "tags": doc.get("tags"),
            # stored as list already (or list of lists); convert inner items to tuples
            "affected_endpoint_list": [tuple(item) for item in (doc.get("affected_endpoint_list") or [])],
        }
        _logger.debug(f"The current request being pulled is:\n{request_dict}")

        # After pulling the request from the database, remove it.
        R = Query()
        table.remove(R.request_id == request_dict["request_id"])

        # Persist changes (CachingMiddleware flushes on close)
        db.close()
        db = None

        return request_dict
    except Exception as e:
        _logger.error(f"Error pulling request from TinyDB: {e}")
        try:
            if db is not None:
                db.close()
        except Exception:
            pass
        return None


def read_xml_file(filename: str) -> str:
    with open(filename, "r", encoding="utf-8") as file:
        return file.read()


# Add the affected_endpoint to the XML
def add_affected_endpoints_to_xml(xml_data, affected_endpoints):
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
    #url = "http://192.168.156.14:5000/read_values_xml"
    url = CONFIG.flask_bridge.read_values_url

    headers = {"Content-Type": "application/xml"}
    #response = requests.post(url, data=xml_data, headers=headers)
    response = requests.post(
        url, data=xml_data, headers=headers,
        timeout=CONFIG.flask_bridge.timeout_seconds
    )

    if response.status_code == 200:  # 200 is the default normal value
        _logger.debug(f"Response status code: {response.status_code}")
        _logger.debug(f"Response content: {response.text}")
        return response.text  # type: str
    else:
        _logger.error(f"Error: {response.status_code} - {response.text}")
        return None


# TODO: Check for perfomance issues with large XML files and recursive functions
def acceptance_verification(xml_data):
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
    try:
        _logger.info(f"Sending back to Flask server: {affected_endpoints_dict}")
        #url = "http://192.168.156.14:5000/update_endpoints"
        url = CONFIG.flask_bridge.update_endpoints_url
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


"""def run_bridge():
    # Initialize the Flask server bridge
    bridge = FlaskServerBridge()
    bridge.run(debug=False, threaded=True)  # Start the Flask server in a separate thread"""


def pull_request_and_process():
    time.sleep(CONFIG.processing.startup_delay_seconds)

    while True:
        try:
            # Pull the highest priority request from the database
            try:
                request = pull_request()
            except Exception as e:
                _logger.error(f"Error pulling request from database: {e}")
                request = None

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
                time.sleep(CONFIG.processing.idle_sleep_seconds)  # Sleep for a short duration to avoid busy waiting
        except Exception as e:
            _logger.error(f"An error occurred: {e}")


def main():
    """
    Main entry point that starts the Flask server bridge in the main thread
    and the request processor in a separate thread.
    """
    # Start the request processing in a separate thread
    processor_thread = threading.Thread(target=pull_request_and_process, daemon=True)
    processor_thread.start()
    _logger.info("Request processor started in background thread")

    # Run the Flask server in the main thread
    # _logger.info("Starting Flask server bridge in the main thread")
    # run_bridge()  # This will block until the server terminates
    while True:
        time.sleep(1)


# TODO: send the to be implemented affected endpoint changes to OPC UA client in data_aggregation_server
# TODO: log the printed feedbacks.

if __name__ == "__main__":
    main()
