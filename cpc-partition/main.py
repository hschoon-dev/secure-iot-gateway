"""
------------------------------------------------------------
 Modul:    cpc-partition/main.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    This module is the main entry point for the CPC partition
    of the Secure IoT Gateway. It initializes and starts the
    OPC UA and Modbus TCP clients, sets up shared memory
    and semaphores for inter-process communication, and runs
    a Flask server to bridge (temporary) communication with 
    other VoR components.

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
import sys
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from multiprocessing import shared_memory
import threading
import posix_ipc

# local imports
from opcua_client_manager import OpcUaClientManager
from modbus_tcp_client_manager import ModbusClientManager

from flask_server_bridge.flask_server_bridge import FlaskServerBridge

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

_logger = setup_logging(logging.WARNING)

async def opcua_service() -> None:
    """
    This function starts the OPC UA service and reads the data from the OPC UA server.
    """
    sys.path.insert(0, "..")
    path_base = Path(__file__).parent
    xml_config_file_opcua =  Path(path_base / "config/opcua-endpoints_factory_and_docker.xml")
    xsd_file_opcua = Path(path_base / "config/opcua-endpoints.xsd")

    opcua_interval = 1 # Interval in seconds
    opcua_shm_name = 'opcua_shm'
    opcua_shm_size = 1024*10
    opcua_semaphore_name = 'opcua_semaphore'

    # Prepare lists for shm and semaphore
    opcua_shm_psmo = shared_memory.SharedMemory(name=f"{opcua_shm_name}_psmo", create=True, size=opcua_shm_size)
    opcua_shm_interface = shared_memory.SharedMemory(name=f"{opcua_shm_name}_interface", create=True, size=opcua_shm_size)
    opcua_shm_list = [opcua_shm_psmo, opcua_shm_interface]
    
    opcua_semaphore_psmo = posix_ipc.Semaphore(f"{opcua_semaphore_name}_psmo", posix_ipc.O_CREX)
    opcua_semaphore_interface = posix_ipc.Semaphore(f"{opcua_semaphore_name}_interface", posix_ipc.O_CREX)
    opcua_sem_list = [opcua_semaphore_psmo, opcua_semaphore_interface]

    opcua_manager = OpcUaClientManager(xml_config_file_opcua, xsd_file_opcua)
    if await opcua_manager.start_clients() == []:
        _logger.error(f"Start clients returned empty list.")
        return
    await opcua_manager.periodic_read(opcua_interval, opcua_shm_list, opcua_sem_list)

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
    sys.path.insert(0, "..")
    path_base = Path(__file__).parent
    xml_config_file_modbustcp =  Path(path_base / "config/modbustcp-endpoints_ecotec.xml")
    xsd_file_modbustcp = Path(path_base / "config/modbustcp-endpoints.xsd")

    modbus_interval = 1
    modbus_shm_name = 'modbus_shm'
    modbus_shm_size = 1024*12
    modbus_semaphore_name = 'modbus_semaphore'

    # Prepare lists for shm and semaphore
    modbus_shm_psmo = shared_memory.SharedMemory(name=f"{modbus_shm_name}_psmo", create=True, size=modbus_shm_size)
    modbus_shm_interface = shared_memory.SharedMemory(name=f"{modbus_shm_name}_interface", create=True, size=modbus_shm_size)
    modbus_shm_list = [modbus_shm_psmo, modbus_shm_interface]
    
    modbus_semaphore_psmo = posix_ipc.Semaphore(f"{modbus_semaphore_name}_psmo", posix_ipc.O_CREX)
    modbus_semaphore_interface = posix_ipc.Semaphore(f"{modbus_semaphore_name}_interface", posix_ipc.O_CREX)
    modbus_sem_list = [modbus_semaphore_psmo, modbus_semaphore_interface]

    modbus_manager = ModbusClientManager(xml_config_file_modbustcp, xsd_file_modbustcp)
    await modbus_manager.start_clients()
    await modbus_manager.periodic_read(modbus_interval, modbus_shm_list, modbus_sem_list)

def modbus_tcp_service_thread() -> None:
    """
    This function starts the Modbus TCP service in a new thread.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(modbus_tcp_service())
    loop.close()

def run_flask_server() -> None:
    """
    This function starts the Flask server.
    """
    bridge = FlaskServerBridge()
    bridge.run(debug=False, threaded=True)

async def main():
    await asyncio.sleep(3)

    threads = []
    opcua_thread = threading.Thread(target=opcua_service_thread)
    threads.append(opcua_thread)
    modbus_thread = threading.Thread(target=modbus_tcp_service_thread)
    threads.append(modbus_thread)

    # NEW
    flask_thread = threading.Thread(target=run_flask_server)
    threads.append(flask_thread)

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
        _logger.info("Clients stopped")

if __name__ == "__main__":
    asyncio.run(main())