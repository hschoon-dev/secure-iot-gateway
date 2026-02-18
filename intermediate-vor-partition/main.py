"""
------------------------------------------------------------
 Modul:    interface-partition/main.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    The main function initializes and runs the Intermediate VoR
    partition of the Secure IoT Gateway. It sets up logging,
    shared memory, semaphores, and message queues for inter-process
    communication with other VoR components. The partition listens
    for incoming requests via a message queue, verifies and maps
    them according to predefined rules, and provides feedback
    to the interface partition. The logging configuration supports
    both console and rotating file logging with adjustable log levels.

 Autor(en):
    - Yuanchen Zhao (developer for the VoR framework)
    - Heiko Schoon (edited monolithic code into this module,
      added logging, message queue handling, and controlled shutdown)

 Maintainer:
    - tbd

 Hinweis:
    Ongoing development.
------------------------------------------------------------
"""

import logging
from logging.handlers import RotatingFileHandler
import sys
import time
import signal
import os

from request_verification import RuleSet
from mapping_verification import Mapping_RuleSets
from feedback_system import FeedbackSystem
from grpc_request_handler import build_grpc_server
from request_message_handler import RequestMessageHandler

path = os.path.dirname(os.path.abspath(__file__))
verfication_ruleset_path = os.path.join(path, "config/Request_Verification_Ruleset.xml")
mapping_ruleset_path = os.path.join(path, "config/Mapping_Rulesets.xml")
#mapped_rq_db_path = os.path.join(path, "config/mapped_requests.db")

#mapped_rq_db_path = os.path.join(path, "mnt/mapped_requests.json")
mapped_rq_db_path = "/mnt/mapped_requests.json"
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

# Global flag for controlled shutdown
_running = True
_grpc_server = None

def signal_handler(sig, frame):
    global _running, _grpc_server
    _logger.info("Shutdown signal received, exiting gracefully...")
    _running = False
    if _grpc_server is not None:
        try:
            _logger.info("Stopping gRPC server...")
            _grpc_server.stop(grace=5)
        except Exception as e:
            _logger.error(f"Error stopping gRPC server: {e}")

def main() -> None:
    global _grpc_server

    # (1) Init rules & systems
    verification_ruleset = RuleSet(verfication_ruleset_path)
    feedback_system = FeedbackSystem()
    mapping_ruleset = Mapping_RuleSets(mapping_ruleset_path)

    # (2) Build the unified handler
    handler = RequestMessageHandler(
        verification_ruleset=verification_ruleset,
        mapping_ruleset=mapping_ruleset,
        feedback_system=feedback_system,
        db_path=mapped_rq_db_path,
    )

    # (3) Start the gRPC server that invokes the handler synchronously
    try:
        srv, addr = build_grpc_server(handler=handler, port=50051)  # pass cert_base=Path(path)/"certificates"/"grpc" if needed
        srv.start()
        _grpc_server = srv
        _logger.info(f"gRPC server started on {addr} (mTLS).")
    except Exception as e:
        _logger.error(f"Failed to start gRPC server: {e}")
        return

    # (4) Your existing lifecycle (no MQ receive loop needed)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    _logger.info("Intermediate VoR Partition running. Press Ctrl+C to exit.")
    try:
        while _running:
            time.sleep(5)
    finally:
        if _grpc_server is not None:
            _logger.info("Finalizing gRPC server shutdown...")
            _grpc_server.stop(grace=2)
        _logger.info("Intermediate VoR Partition shutdown complete.")

if __name__ == "__main__":
    main()