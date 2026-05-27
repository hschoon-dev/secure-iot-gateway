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
import sys
from pathlib import Path
from queue import Queue
from grpc_json_handler import JSON_gRPC_Thread

# Own modules
from interface_setup import setup_opcua_server
from data_manager import DataManager
from config_loader import load_config, InterfaceConfig

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



async def await_soft_timeout(task: asyncio.Task, label: str, timeout: float):
    """
    Wait up to `timeout` seconds.
    - On success: return result
    - On timeout: cancel the task and return None
    """
    try:
        return await asyncio.wait_for(task, timeout=timeout)  # NOTE: no shield => timeout cancels task
    except asyncio.TimeoutError:
        _logger.error(f"Timed out waiting {timeout:.0f}s for {label}; cancelling task.")
        task.cancel()
        # ensure cancellation is processed (avoid "Task exception was never retrieved")
        await asyncio.gather(task, return_exceptions=True)
        return None

    

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

    #opcua_queue = Queue(maxsize=2)
    #modbustcp_queue = Queue(maxsize=2)
    opcua_queue = Queue(maxsize=CONFIG.queues.opcua_maxsize)
    modbustcp_queue = Queue(maxsize=CONFIG.queues.modbustcp_maxsize)

    #grpc_server_thread = JSON_gRPC_Thread(opcua_message_queue=opcua_queue, modbustcp_message_queue=modbustcp_queue)
    grpc_server_thread = JSON_gRPC_Thread(
    opcua_message_queue=opcua_queue,
    modbustcp_message_queue=modbustcp_queue,
    config=CONFIG.grpc_server,
    )
    grpc_server_thread.start()

    #server = await setup_opcua_server(config=CONFIG.opcua_server)
    server = await setup_opcua_server(
        config=CONFIG.opcua_server,
        grpc_client=CONFIG.grpc_client,
    )
    await asyncio.sleep(5)


    # Initial shared memory reading for OPC UA Server setup
    opcua_variables = []
    modbustcp_variables = []
    #data_manager = DataManager(server, opcua_shm_name, opcua_sem_name, modbus_shm_name, modbus_sem_name)
    data_manager = DataManager(server, opcua_queue, modbustcp_queue)

    _logger.info("OPC UA Server of the interface partition is running.")
    async with server:
        # Initialise update_tasks before the try block so the except handler
        # can safely iterate over it even if an exception is raised before the
        # assignment inside the try body is reached (e.g. TimeoutError from
        # the asyncio.gather call above it).
        update_tasks: list[asyncio.Task] = []
        try:
            _logger.info(f"Start populating...")
            
            # Create initial populations
            """opcua_variables = await data_manager.create_population(opcua_queue, "OPCUA_Endpoints")
            _logger.info("Initial OPC UA values created from OPC UA Queue.")
            modbustcp_variables = await data_manager.create_population(modbustcp_queue, "ModbusTCP_Endpoints")
            _logger.info("Initial OPC UA values created from ModbusTCP Queue.")"""
            # Start both concurrently
            opcua_task = asyncio.create_task(
                data_manager.create_population(opcua_queue, "OPCUA_Endpoints", max_wait_s=20.0)
            )
            modbustcp_task = asyncio.create_task(
                data_manager.create_population(modbustcp_queue, "ModbusTCP_Endpoints", max_wait_s=20.0)
            )
            # Wait for both concurrently
            opcua_variables, modbustcp_variables = await asyncio.gather(opcua_task, modbustcp_task)

            # If both timed out -> raise error
            if opcua_variables is None and modbustcp_variables is None:
                raise asyncio.TimeoutError("Both OPC UA and ModbusTCP initial population timed out (20s).")

            # Start only the successful periodic updates
            update_tasks = []

            if opcua_variables is not None:
                update_tasks.append(asyncio.create_task(
                    data_manager.update_population(opcua_queue, opcua_variables, "OPCUA_Endpoints")
                ))

            if modbustcp_variables is not None:
                update_tasks.append(asyncio.create_task(
                    data_manager.update_population(modbustcp_queue, modbustcp_variables, "ModbusTCP_Endpoints")
                ))

            # Run whatever updates were started
            await asyncio.gather(*update_tasks)


        except (KeyboardInterrupt, asyncio.CancelledError):
            _logger.error("Stopping... cancelling update tasks.")
            # Cancel only tasks that exist and are still running
            for t in update_tasks:
                if not t.done():
                    t.cancel()
            # Wait for cancellation to complete (swallow CancelledError/others)
            await asyncio.gather(*update_tasks, return_exceptions=True)

        except asyncio.TimeoutError as e:
            _logger.error(f"Error: {e}")

        finally:
            _logger.info("Tasks stopped")


if __name__ == "__main__":
    asyncio.run(main())