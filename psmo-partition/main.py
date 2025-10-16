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
import queue
import time
import sys
import os
from logging.handlers import RotatingFileHandler

#from psmo_shm_handler import OPCUA_Thread, ModbusTCP_Thread
from grpc_json_handler import JSON_gRPC_Thread

path = os.path.dirname(os.path.abspath(__file__))
logging_path = os.path.join(path, "logs/app.log")

def setup_logging(
    log_level=logging.WARNING,
    log_file=logging_path,
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
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    # Root logger config
    logging.basicConfig(
        level=log_level,
        handlers=[console_handler, file_handler],
    )

    return logging.getLogger(__name__)

_logger = setup_logging(logging.INFO)


def main():
    time.sleep(7)
    #opcua_shm_name = 'opcua_shm_psmo'
    #opcua_semaphore_name = 'opcua_semaphore_psmo'
    opcua_queue = queue.Queue(maxsize=5)
    #opcua_thread = OPCUA_Thread(opcua_semaphore_name, opcua_shm_name, opcua_queue)

    #modbus_shm_name = 'modbus_shm_psmo'
    #modbus_semaphore_name = 'modbus_semaphore_psmo'
    modbustcp_queue = queue.Queue(maxsize=5)
    #modbus_thread = ModbusTCP_Thread(modbus_semaphore_name, modbus_shm_name, modbustcp_queue)

    json_grpc_thread = JSON_gRPC_Thread(opcua_message_queue=opcua_queue, modbustcp_message_queue=modbustcp_queue)
    json_grpc_thread.start()

    #opcua_thread.start()
    #modbus_thread.start()

    try:
        _logger.info("psM+O partition is running.")
        while True:
            if not opcua_queue.empty():
                item = opcua_queue.get()
                item_count = len(item.keys())
                _logger.info(f"Retrieved {item_count} items from OPC UA queue. Waiting to process...")
                _logger.info(f"Timestamp: {item["timestamp"]}")
                _logger.info(f"Source: {item["source"]}")
                _logger.info(f"Data: {item["data"]}")
            if not modbustcp_queue.empty():
                item = modbustcp_queue.get()
                item_count = len(item.keys())
                _logger.info(f"Retrieved {item_count} items from ModbusTCP queue. Waiting to process...")
                _logger.info(f"Timestamp: {item["timestamp"]}")
                _logger.info(f"Source: {item["source"]}")
                _logger.info(f"Data: {item["data"]}")
            #time.sleep(.05)
    except Exception as e:
        _logger.error(f"Error handling main-process: {e}")
    except KeyboardInterrupt:
        #opcua_thread.stop()
        #modbus_thread.stop()
        json_grpc_thread.stop()
        #opcua_thread.join()
        #modbus_thread.join()
        json_grpc_thread.join()

if __name__ == "__main__":
    main()