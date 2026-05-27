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

import requests
# defusedxml prevents XML entity-expansion (billion-laughs) and external-entity
# attacks on XML received from network sources (Flask bridge response, field
# devices). All other partitions already use defusedxml; this one must too.
# Note: defusedxml.ElementTree.fromstring() is a drop-in replacement.
# ET.tostring() and ET.SubElement() are write-side helpers that produce XML and
# are not vulnerable; they may remain as stdlib imports via an alias.
import xml.etree.ElementTree as _ET          # write-side helpers only
from defusedxml import ElementTree as ET     # read-side (fromstring / parse)
import sys
import threading
import time
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

# local imports
from db_manager import DatabaseManager
from config_loader import load_config

# ---------------------------------------------------------------------------
# Pydantic config
# ---------------------------------------------------------------------------

# CONFIG is populated inside main() after logging is set up, so that any
# Pydantic validation errors or YAML parse warnings are routed through the
# configured formatter rather than landing on the bare stderr default handler.
CONFIG = None  # type: ignore[assignment]  # assigned in main() before use

# ---------------------------------------------------------------------------
# Ruleset / database paths — all from config
# ---------------------------------------------------------------------------

#acceptance_ruleset_path          = CONFIG.acceptance_rulesets.ruleset
#acceptance_ruleset_path_modified = CONFIG.acceptance_rulesets.ruleset_modified

# ---------------------------------------------------------------------------
# MariaDB credentials — all from CONFIG.mariadb (env vars override via
# _apply_env_overrides in config_loader.py)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(
    log_level=logging.WARNING,
    log_file="default.log",
    max_bytes=1 * 1024 * 1024,
    backup_count=3,
) -> logging.Logger:

    log_format = (
        "[%(asctime)s] [%(levelname)-8s] "
        "[%(name)s:%(lineno)d] - %(message)s"
    )
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(log_format, datefmt=date_format)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    print(f"Logging to file: {log_file}")
    file_handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    logging.basicConfig(
        level=log_level,
        handlers=[console_handler, file_handler],
    )
    return logging.getLogger(__name__)


_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def initialize_database() -> DatabaseManager:
    """
    Initialize the database manager with MariaDB connection pool.

    Returns:
        DatabaseManager instance

    Raises:
        Exception if database connection fails
    """
    try:
        db = CONFIG.mariadb
        db_manager = DatabaseManager(
            host=db.host,
            port=db.port,
            user=db.user,
            password=db.password,
            database=db.database,
            pool_name=db.pool_name,
            pool_size=db.pool_size,
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


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def read_xml_file(filename: str) -> str:
    """Read XML file from disk."""
    with open(filename, "r", encoding="utf-8") as file:
        return file.read()


def add_affected_endpoints_to_xml(xml_data, affected_endpoints) -> str:
    """
    Return the acceptance ruleset XML extended with affected endpoint stubs.

    The result is returned as an in-memory string; no file is written.

    Previously this function wrote to the fixed path
    `config/Acceptance_Ruleset_modified.xml` before returning. Writing to a
    fixed path is a latent race condition: if two requests are ever processed
    concurrently (e.g. after the processing loop is parallelised), the second
    write corrupts the XML being consumed by the first request. Passing the
    XML string directly through the call chain avoids all file-system
    contention and removes the dependency on acceptance_ruleset_path_modified.
    """
    root = ET.fromstring(xml_data)      # defusedxml — see FIX-04

    affected_endpoints_elem = _ET.SubElement(root, "affected_endpoints")

    for endpoint in affected_endpoints:
        endpoint_elem = _ET.SubElement(affected_endpoints_elem, "affected_endpoint")
        name_elem = _ET.SubElement(endpoint_elem, "name")
        name_elem.text = endpoint[0]
        value_elem = _ET.SubElement(endpoint_elem, "value")
        value_elem.text = "0"

    return _ET.tostring(root, encoding="utf-8").decode("utf-8")


# ---------------------------------------------------------------------------
# Flask bridge communication — all URLs and timeouts from config
# ---------------------------------------------------------------------------

def send_request(xml_data) -> str | None:
    """Send request to Flask server bridge (CPC partition)."""
    url = CONFIG.flask_bridge.read_values_url
    headers = {"Content-Type": "application/xml"}
    try:
        response = requests.post(
            url, data=xml_data, headers=headers,
            timeout=CONFIG.flask_bridge.timeout_seconds,
        )
        if response.status_code == 200:
            _logger.debug(f"Response status code: {response.status_code}")
            _logger.debug(f"Response content: {response.text}")
            return response.text
        else:
            _logger.error(f"Error: {response.status_code} - {response.text}")
            return None
    except requests.RequestException as e:
        _logger.error(f"Request failed: {e}")
        return None


def send_back_results(affected_endpoints_dict):
    """Send results back to Flask server bridge for CPC system."""
    try:
        _logger.info(f"Sending back to Flask server: {affected_endpoints_dict}")
        url = CONFIG.flask_bridge.update_endpoints_url
        headers = {"Content-Type": "application/json"}
        response = requests.post(
            url, json=affected_endpoints_dict, headers=headers,
            timeout=CONFIG.flask_bridge.timeout_seconds,
        )
    except requests.RequestException as e:
        _logger.error(f"Error sending back to Flask server: {e}")
        return
    except Exception as e:
        _logger.error(f"Unexpected error: {e}")
        return

    if response.ok:
        try:
            _logger.info(f"Response from Flask server: {response.json()}")
        except ValueError:
            _logger.info(f"Response from Flask server (non-JSON body): {response.text!r}")
    else:
        _logger.error(
            f"Failed to send back to Flask server: {response.status_code} - {response.text}"
        )


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def acceptance_verification(xml_data):
    """
    Verify that request acceptance criteria are met.

    Checks that current values match required values in the XML structure.
    """
    root = ET.fromstring(xml_data)
    all_passed = True

    def verify_values(element, path=""):
        nonlocal all_passed
        current = None
        required = None

        for child in element:
            child_path = f"{path}/{child.tag}" if path else child.tag

            if child.tag == "current_value":
                current = child.text.strip()
            elif child.tag == "required_value":
                required = child.text.strip()
            else:
                verify_values(child, child_path)

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

    verify_values(root)

    if all_passed:
        _logger.info("The request is accepted and forwarded to the mapping verification step.")
    else:
        _logger.warning(
            "The request is not accepted and won't be forwarded to the mapping verification step."
        )
    return all_passed


def mapping_verification(request, xml_data):
    """Verify mapping constraints and calculate effective endpoint values."""
    root = ET.fromstring(xml_data)

    affected_endpoints_values = {}
    for endpoint in root.findall(".//affected_endpoint"):
        name = endpoint.find("name").text
        value = float(endpoint.find("value").text)
        _logger.debug(f"\n name: {name}, value: {value}")
        affected_endpoints_values[name] = value

    all_passed = True
    affected_endpoint_dict = affected_endpoints_values.copy()

    for endpoint in request["affected_endpoint_list"]:
        change_type: str
        condition: str
        name, change_type, _, condition = endpoint
        value = affected_endpoints_values.get(name)

        if value is not None:
            if "relative" in change_type:
                percent_change = float(change_type.split(",")[1].strip().replace("%", ""))
                process_value = value * (1 + percent_change / 100)
                affected_endpoint_dict[name] = process_value
            else:
                process_value = float(change_type.split(",")[1].strip())
                affected_endpoint_dict[name] = process_value
        else:
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
            "Completed: The request was verified through the mapping verification step and "
            "the mapped CPC endpoints were accepted and forwarded to the CPC system."
        )
    else:
        _logger.warning(
            "Not completed: The request failed the mapping verification step."
        )
        return None
    return affected_endpoint_dict


# ---------------------------------------------------------------------------
# Main processing loop
# ---------------------------------------------------------------------------

def pull_request_and_process(db_manager: DatabaseManager):
    """Main processing loop: pull requests from MariaDB and process them."""
    time.sleep(CONFIG.processing.startup_delay_seconds)

    while True:
        try:
            request = pull_request(db_manager)

            if request is not None:
                xml_data = read_xml_file(acceptance_ruleset_path)

                try:
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
                time.sleep(CONFIG.processing.idle_sleep_seconds)

        except Exception as e:
            _logger.error(f"An error occurred: {e}")


def main():
    """Main entry point that initializes the database and starts the request processor."""
    # Load config before setup_logging() so the log file path is available,
    # but after the import block so module-level symbols are resolved.
    # Pydantic validation errors here will go to stderr (acceptable: the
    # process cannot continue without a valid config anyway).
    global CONFIG          # FIX-18: CONFIG zuerst laden
    CONFIG = load_config(
        path=Path(__file__).parent / "config/settings.yaml",
        base_dir=Path(__file__).parent,
    )
    global acceptance_ruleset_path, acceptance_ruleset_path_modified
    acceptance_ruleset_path          = CONFIG.acceptance_rulesets.ruleset
    acceptance_ruleset_path_modified = CONFIG.acceptance_rulesets.ruleset_modified

    # Configure the root logger exactly once, as early as possible in the
    # process lifetime. All other modules obtain child loggers via
    # logging.getLogger(__name__) and inherit this configuration automatically.
    global _logger
    _logger = setup_logging(
        log_level=getattr(logging, CONFIG.logging.log_level.upper(), logging.WARNING),
        log_file=CONFIG.logging.log_file,
        max_bytes=CONFIG.logging.max_bytes,
        backup_count=CONFIG.logging.backup_count,
    )

    try:
        db_manager = initialize_database()
        _logger.info("Database connection pool initialized")
    except Exception as e:
        _logger.critical(f"Failed to initialize database: {e}")
        sys.exit(1)

    processor_thread = threading.Thread(
        target=pull_request_and_process,
        args=(db_manager,),
        daemon=True,
    )
    processor_thread.start()
    _logger.info("Request processor started in background thread")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _logger.info("Shutting down gracefully...")
        sys.exit(0)


if __name__ == "__main__":
    main()