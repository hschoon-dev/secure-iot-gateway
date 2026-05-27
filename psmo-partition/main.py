"""
------------------------------------------------------------
 Modul:    psmo-partition/main.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    This script serves as the main entry point for the
    plant-specific M+O partition of the Secure IoT Gateway.
    It initializes threads to read data from shared memory
    segments for OPC UA and Modbus TCP, using semaphores
    for synchronization. The retrieved data is placed into
    queues for further processing by plant-specific M+O
    implementations.
    This is a placeholder module for future plant-specific
    M+O implementations. It currently only provides an API
    to read shared memory segments for OPC UA and Modbus TCP
    data. Future processing can be added within the main
    loop where data is retrieved from the queues.


 Autor(en):
    - Heiko Schoon

 Maintainer:
    - heiko.schoon@hs-emden-leer.de

 Hinweis:
    Ongoing development. This is a placeholder module
    for future plant-specific M+O implementations. It 
    currently only provides an API to read shared
    memory segments for OPC UA and Modbus TCP data.
------------------------------------------------------------
"""

import logging
import time
import sys
from pathlib import Path
from queue import Queue
from logging.handlers import RotatingFileHandler

from grpc_json_handler import JSON_gRPC_Thread
from config_loader import load_config, PSMOConfig

# CONFIG is populated inside main() after logging is set up, so that any
# Pydantic validation errors or YAML parse warnings are routed through the
# configured formatter rather than landing on the bare stderr default handler.
CONFIG = None  # type: ignore[assignment]  # assigned in main() before use

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


def main():
    # Load config before setup_logging() so the log file path is available,
    # but after the import block so module-level symbols are resolved.
    # Pydantic validation errors here will go to stderr (acceptable: the
    # process cannot continue without a valid config anyway).
    global CONFIG          # FIX-18: CONFIG zuerst laden
    CONFIG = load_config(
        path=Path(__file__).parent / "config/settings.yaml",
        base_dir=Path(__file__).parent,
    )

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

    time.sleep(CONFIG.lifecycle.startup_delay_seconds)

    #opcua_queue = Queue(maxsize=2)
    #modbustcp_queue = Queue(maxsize=2)
    opcua_queue    = Queue(maxsize=CONFIG.queues.opcua_maxsize)
    modbustcp_queue = Queue(maxsize=CONFIG.queues.modbustcp_maxsize)

    #json_grpc_thread = JSON_gRPC_Thread(opcua_message_queue=opcua_queue, modbustcp_message_queue=modbustcp_queue)
    json_grpc_thread = JSON_gRPC_Thread(
    opcua_message_queue=opcua_queue,
    modbustcp_message_queue=modbustcp_queue,
    config=CONFIG.grpc_server,
    )
    json_grpc_thread.start()

    try:
        _logger.info("psM+O partition is running.")
        while True:
            if not opcua_queue.empty():
                item = opcua_queue.get()
                item_count = len(item.keys())
                _logger.info(f"Retrieved {item_count} items from OPC UA queue. Waiting to process...")
                _logger.info(f"Timestamp: {item['timestamp']}")
                _logger.info(f"Source: {item['source']}")
                _logger.info(f"Data: {item['data']}")

            if not modbustcp_queue.empty():
                item = modbustcp_queue.get()
                item_count = len(item.keys())
                _logger.info(f"Retrieved {item_count} items from ModbusTCP queue. Waiting to process...")
                _logger.info(f"Timestamp: {item['timestamp']}")
                _logger.info(f"Source: {item['source']}")
                _logger.info(f"Data: {item['data']}")

    except KeyboardInterrupt:
        # KeyboardInterrupt is NOT a subclass of Exception; it must be caught
        # first (or alone) so the except-Exception branch below cannot shadow it.
        # Without this order, Ctrl-C is swallowed and the gRPC thread is never
        # stopped, leaving the port bound until the OS kills the process.
        _logger.info("Keyboard interrupt received. Stopping gRPC thread...")
        json_grpc_thread.stop()
        json_grpc_thread.join()

    except Exception as e:
        _logger.error(f"Error handling main-process: {e}")

if __name__ == "__main__":
    main()