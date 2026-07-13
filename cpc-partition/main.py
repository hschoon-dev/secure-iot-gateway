"""
------------------------------------------------------------
 Modul:    cpc-partition/main.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    This module is the main entry point for the CPC partition
    of the Secure IoT Gateway. It initializes the OPC UA and Modbus TCP
    clients and exposes the typed CPC pipeline through gRPC with mutual TLS.

 Autor(en):
    - Heiko Schoon

 Maintainer:
    - Heiko Schoon <heiko.schoon@hs-emden-leer.de>

 Hinweis:
    Ongoing development.
------------------------------------------------------------
"""

import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
import threading

# local imports
from opcua_client_manager import OpcUaClientManager
from modbus_tcp_client_manager import ModbusClientManager
from flask_server_bridge.flask_server_bridge import FlaskServerBridge
from config_loader import load_config, CPCConfig
from grpc_sender import init_ssl_credentials
from pipeline_server import build_pipeline_server

#sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# CONFIG is populated inside main() after logging is set up, so that any
# Pydantic validation errors or YAML parse warnings are routed through the
# configured formatter rather than landing on the bare stderr default handler.
CONFIG = None  # type: ignore[assignment]  # assigned in main() before use
#init_ssl_credentials(CONFIG.grpc_certs)

#path = os.path.dirname(os.path.abspath(__file__))
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

# Module-level logger: handlers are not attached here. Logging is configured
# inside main() so that importing this module in a test or another context
# does not silently create log files or pollute the root logger's handler list.
_logger = logging.getLogger(__name__)


async def opcua_service() -> None:
    """
    This function starts the OPC UA service and reads the data from the OPC UA server.
    """
    opcua_config            = CONFIG.opcua
    xml_config_file_opcua   = opcua_config.files.xml_config
    xsd_file_opcua          = opcua_config.files.xsd_schema
    opcua_interval          = opcua_config.interval
    opcua_grpc_target_interface    = opcua_config.grpc_targets.interface_partition
    opcua_grpc_target_psmo         = opcua_config.grpc_targets.psmo_partition

    opcua_manager = OpcUaClientManager(
        xml_config_file_opcua,
        xsd_file_opcua,
        opcua_grpc_target_interface,
        opcua_grpc_target_psmo,
    )
    # start_clients() returns a list of None values (one per client on success).
    # An empty list means no clients were configured at all (XML parse failed),
    # not that all connections failed. Check the client list directly instead.
    await opcua_manager.start_clients()
    if not opcua_manager.clients:
        _logger.error(
            "OPC UA client list is empty after XML parse. "
            "Check the XML config file and XSD validation errors above."
        )
        return
    await opcua_manager.periodic_read(opcua_interval)

def opcua_service_thread() -> None:
    """
    This function starts the OPC UA service in a new thread.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(opcua_service())
    loop.close()

async def modbus_tcp_service() -> None:
    """
    This function starts the Modbus TCP service and reads the data from the Modbus TCP server.
    """
    modbustcp_config            = CONFIG.modbustcp
    xml_config_file_modbustcp   = modbustcp_config.files.xml_config
    xsd_file_modbustcp          = modbustcp_config.files.xsd_schema
    modbus_interval             = modbustcp_config.interval
    modbus_grpc_target_interface    = modbustcp_config.grpc_targets.interface_partition
    modbus_grpc_target_psmo         = modbustcp_config.grpc_targets.psmo_partition

    modbus_manager = ModbusClientManager(xml_config_file_modbustcp, xsd_file_modbustcp, modbus_grpc_target_interface, modbus_grpc_target_psmo)
    await modbus_manager.start_clients()
    await modbus_manager.periodic_read(modbus_interval)

def modbus_tcp_service_thread() -> None:
    """
    This function starts the Modbus TCP service in a new thread.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(modbus_tcp_service())
    loop.close()

def run_flask_server(bridge: FlaskServerBridge) -> None:
    """
    This function starts the Flask server.
    """
    #bridge = FlaskServerBridge()
    #bridge.run(debug=False, threaded=True)

    bridge.run(
        host=CONFIG.flask_bridge.host,
        port=CONFIG.flask_bridge.port,
        debug=CONFIG.flask_bridge.debug,
        threaded=CONFIG.flask_bridge.threaded,
    )

async def main():
    global CONFIG
    # Load config before setup_logging() so the log file path is available,
    # but after the import block so module-level symbols are resolved.
    # Pydantic validation errors here will go to stderr (acceptable: the
    # process cannot continue without a valid config anyway).
    CONFIG = load_config(
        path=Path(__file__).parent / "config/settings.yaml",
        base_dir=Path(__file__).parent,
    )
    init_ssl_credentials(CONFIG.grpc_certs)

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
    
    await asyncio.sleep(3)

    bridge = FlaskServerBridge(
        opcua_files=CONFIG.opcua.files,
        modbustcp_files=CONFIG.modbustcp.files,
    )
    pipeline_server = build_pipeline_server(bridge)
    pipeline_server.start()
    _logger.warning("CPC typed gRPC server listening on 50053 (mTLS)")

    threads = []
    opcua_thread = threading.Thread(target=opcua_service_thread)
    threads.append(opcua_thread)
    modbus_thread = threading.Thread(target=modbus_tcp_service_thread)
    threads.append(modbus_thread)
    if os.getenv("ENABLE_LEGACY_FLASK_BRIDGE", "false").strip().lower() in (
        "1", "true", "yes", "on"
    ):
        flask_thread = threading.Thread(target=run_flask_server, args=(bridge,))
        threads.append(flask_thread)
        _logger.warning("Legacy unauthenticated Flask bridge explicitly enabled")
    else:
        _logger.info("Legacy Flask bridge disabled; CPC accepts typed gRPC/mTLS only")

    try:
        print("CPC-Partition is running.")
        thread: threading.Thread = None
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        pipeline_server.stop(grace=5).wait()
        _logger.info("Clients stopped")

if __name__ == "__main__":
    asyncio.run(main())
