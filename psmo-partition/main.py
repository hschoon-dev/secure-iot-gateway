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
import os
from pathlib import Path
from queue import Queue
from logging.handlers import RotatingFileHandler

#from psmo_shm_handler import OPCUA_Thread, ModbusTCP_Thread
from grpc_json_handler import JSON_gRPC_Thread
from config_loader import load_config, PSMOConfig

CONFIG = load_config(
    path=Path(__file__).parent / "config/settings.yaml",
    base_dir=Path(__file__).parent,
)

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

_logger = setup_logging(
    log_level=logging.WARNING,
    log_file=CONFIG.logging.log_file,
    max_bytes=CONFIG.logging.max_bytes,
    backup_count=CONFIG.logging.backup_count,
)


def main():
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

    except Exception as e:
        _logger.error(f"Error handling main-process: {e}")

    except KeyboardInterrupt:
        json_grpc_thread.stop()
        json_grpc_thread.join()

if __name__ == "__main__":
    main()