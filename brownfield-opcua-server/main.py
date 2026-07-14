"""
------------------------------------------------------------
 Modul:    brownfield-opcua-server/main.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    Implements the secured and unsecured OPC UA servers
    needed for the brownfield test scenario. It is used
    to test the secure-iot-gateway/cpc-partition.

 Autor(en):
    - Heiko Schoon

 Maintainer:
    - Heiko Schoon <heiko.schoon@hs-emden-leer.de>

 Hinweis:
    Do not use this code in production. It is for testing
    and demonstration purposes only.
------------------------------------------------------------
"""

import asyncio
import multiprocessing
import logging
from logging.handlers import RotatingFileHandler
import sys
import os

from opcua_unsecured_server import start_unsecured_server
from opcua_secured_server import start_secured_server
from security_mode import insecure_opcua_test_server_enabled

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

def run_unsecured_server():
    asyncio.run(start_unsecured_server())

def run_secured_server():
    asyncio.run(start_secured_server())

if __name__ == "__main__":
    secured_process = multiprocessing.Process(target=run_secured_server)
    processes = [secured_process]

    if insecure_opcua_test_server_enabled():
        _logger.warning("Starting the NoSecurity OPC UA server in explicit test mode.")
        processes.append(multiprocessing.Process(target=run_unsecured_server))
    else:
        _logger.info("NoSecurity OPC UA server is disabled.")

    try:
        for process in processes:
            process.start()
        print("Brownfield secured OPC UA server started successfully.")
        for process in processes:
            process.join()
    except KeyboardInterrupt:
        print("Shutting down servers...")
        for process in processes:
            process.terminate()
