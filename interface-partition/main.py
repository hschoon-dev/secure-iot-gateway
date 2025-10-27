"""
------------------------------------------------------------
 Modul:    interface-partition/main.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    The main function initializes and runs the OPC UA server
    for the interface partition of the Secure IoT Gateway.
    It sets up logging, shared memory, semaphores, and message
    queues for inter-process communication with other VoR
    components. The server populates its address space based
    on data from shared memory and periodically updates the
    values to reflect changes in the underlying data sources.
    The logging configuration supports both console and rotating
    file logging with adjustable log levels.

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
from logging.handlers import RotatingFileHandler
import os
import sys
import posix_ipc
import random
import argparse

from queue import Queue
from grpc_json_handler import JSON_gRPC_Thread

# Own modules
from interface_setup import setup_opcua_server
from data_manager import DataManager

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

_logger = setup_logging(logging.DEBUG)
#_logger = logging.getLogger(__name__)


async def send_vor_request(mq:posix_ipc.MessageQueue, request:str):
    # Initial filling of the message queue:
    for i in range(10):
        prio = random.randint(0, 31)
        mq.send(request.encode(), timeout=None, priority=prio)
        _logger.error(f"Filled mq with request: {request} with priority: {prio}")

    while True:
        try:
            prio = random.randint(0, 10)
            mq.send(request.encode(), timeout=None, priority=prio)

            _logger.error(f"Request sent: {request} with priority: {prio}")
        except Exception as e:
            _logger.error(f"Error sending request: {e}")
        await asyncio.sleep(2)
    

async def main():
    parser = argparse.ArgumentParser(description="Interface Partition OPC UA Server")
    parser.add_argument("--log-level", default="WARNING", help="Set the logging level")
    args = parser.parse_args()
    # TODO: Add more arguments for:
    # - authorizaton handler (config file and rbac ruleset)
    # - user manager (credentials db)
    # - shared memory and semaphore names for OPC UA and ModbusTCP
    # - message queue names for VoR requests

    log_level = getattr(logging, args.log_level.upper(), logging.WARNING)
    _logger = setup_logging(log_level)

    opcua_queue = Queue()
    modbustcp_queue = Queue()

    grpc_server_thread = JSON_gRPC_Thread(opcua_message_queue=opcua_queue, modbustcp_message_queue=modbustcp_queue)
    grpc_server_thread.start()

    server = await setup_opcua_server()
    await asyncio.sleep(5)


    # Initial shared memory reading for OPC UA Server setup
    opcua_variables = []
    #data_manager = DataManager(server, opcua_shm_name, opcua_sem_name, modbus_shm_name, modbus_sem_name)
    data_manager = DataManager(server, opcua_queue, modbustcp_queue)

    _logger.info("OPC UA Server of the interface partition is running.")
    async with server:
        try:
            _logger.info(f"Start populating...")
            
            # Create initial populations
            opcua_variables = await data_manager.create_population(opcua_queue, "OPCUA_Endpoints")
            _logger.info("Initial OPC UA values created from OPC UA Queue.")
            modbustcp_variables = await data_manager.create_population(modbustcp_queue, "ModbusTCP_Endpoints")
            _logger.info("Initial OPC UA values created from ModbusTCP Queue.")

            # Continuous updates (two independent tasks → no change in concurrency/threading behavior)
            periodic_update_opcua = asyncio.create_task(
                data_manager.update_population(opcua_queue, opcua_variables, "OPCUA_Endpoints")
            )
            periodic_update_modbustcp = asyncio.create_task(
                data_manager.update_population(modbustcp_queue, modbustcp_variables, "ModbusTCP_Endpoints")
            )
            await asyncio.gather(periodic_update_opcua, periodic_update_modbustcp)



        except asyncio.CancelledError:
            _logger.error("asyncio.CancelledError")

        except KeyboardInterrupt:
            #periodic_update.cancel()
            periodic_update_opcua.cancel()
            periodic_update_modbustcp.cancel()
            #periodic_vor_request.cancel()
            _logger.error("KeyboardInterrupt")

        finally:
            _logger.info("Tasks stopped")


if __name__ == "__main__":
    asyncio.run(main())