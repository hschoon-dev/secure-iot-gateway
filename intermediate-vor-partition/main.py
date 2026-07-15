"""
------------------------------------------------------------
 Modul:    intermediate-vor-partition/main.py
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
from pathlib import Path

from request_verification import RuleSet
from mapping_verification import Mapping_RuleSets
from feedback_system import FeedbackSystem
from grpc_request_handler import build_grpc_server
from request_message_handler import RequestMessageHandler
from mapped_request_client import MappedRequestClient
from config_loader import load_config, VoRConfig

# CONFIG is populated inside main() after logging is set up, so that any
# Pydantic validation errors or YAML parse warnings are routed through the
# configured formatter rather than landing on the bare stderr default handler.
CONFIG = None  # type: ignore[assignment]  # assigned in main() before use

#verfication_ruleset_path = CONFIG.rulesets.verification_ruleset
#mapping_ruleset_path     = CONFIG.rulesets.mapping_ruleset


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


# Module-level logger: handlers are not attached here. Logging is configured
# inside main() so that importing this module in a test or another context
# does not silently create log files or pollute the root logger's handler list.
_logger = logging.getLogger(__name__)

# Global flag for controlled shutdown
_running = True
_grpc_server = None
_mapped_request_client = None


def signal_handler(sig, frame):
    global _running, _grpc_server, _mapped_request_client
    _logger.info("Shutdown signal received, exiting gracefully...")
    _running = False
    if _grpc_server is not None:
        try:
            _logger.info("Stopping gRPC server...")
            _grpc_server.stop(grace=CONFIG.grpc_server.grace_period_seconds)
        except Exception as e:
            _logger.error(f"Error stopping gRPC server: {e}")
    if _mapped_request_client is not None:
        _logger.info("Closing mapped-request gRPC client channel...")
        _mapped_request_client.close()


def initialize_mapped_request_client() -> MappedRequestClient:
    """
    Initialize the mTLS gRPC client used to forward mapped requests to
    intermediate-vor-partition-cpc, from CONFIG.mapped_request_client.

    This partition no longer stores anything in a database itself;
    intermediate-vor-partition-cpc owns storage and is reached only via
    this client.

    Returns:
        MappedRequestClient instance

    Raises:
        Exception if the client (certificate loading, channel setup) fails
        to initialize
    """
    try:
        client = MappedRequestClient(CONFIG.mapped_request_client)
        _logger.info("Mapped-request gRPC client initialized successfully")
        return client
    except Exception as e:
        _logger.critical(f"Failed to initialize mapped-request gRPC client: {e}")
        raise


def main() -> None:
    global CONFIG
    # Load config before setup_logging() so the log file path is available,
    # but after the import block so module-level symbols are resolved.
    # Pydantic validation errors here will go to stderr (acceptable: the
    # process cannot continue without a valid config anyway).
    CONFIG = load_config(
        path=Path(__file__).parent / "config/settings.yaml",
        base_dir=Path(__file__).parent,
    )
    global verfication_ruleset_path, mapping_ruleset_path
    verfication_ruleset_path = CONFIG.rulesets.verification_ruleset
    mapping_ruleset_path     = CONFIG.rulesets.mapping_ruleset

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
    
    global _grpc_server, _mapped_request_client

    # (1) Init the outbound gRPC client to intermediate-vor-partition-cpc
    try:
        mapped_request_client = initialize_mapped_request_client()
        _mapped_request_client = mapped_request_client
    except Exception:
        _logger.critical("Cannot start without a working mapped-request gRPC client.")
        sys.exit(1)

    # (2) Init rules & systems
    verification_ruleset = RuleSet(verfication_ruleset_path)
    feedback_system = FeedbackSystem()
    mapping_ruleset = Mapping_RuleSets(mapping_ruleset_path)

    # (3) Build the unified handler
    handler = RequestMessageHandler(
        verification_ruleset=verification_ruleset,
        mapping_ruleset=mapping_ruleset,
        feedback_system=feedback_system,
        mapped_request_client=mapped_request_client,
    )

    # (4) Start the gRPC server that invokes the handler synchronously
    try:
        srv, addr = build_grpc_server(handler=handler, config=CONFIG.grpc_server)
        srv.start()
        _grpc_server = srv
        _logger.info(f"gRPC server started on {addr} (mTLS).")
    except Exception as e:
        _logger.error(f"Failed to start gRPC server: {e}")
        return

    # (5) Lifecycle
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    _logger.info("Intermediate VoR Partition running. Press Ctrl+C to exit.")
    try:
        while _running:
            time.sleep(5)
    finally:
        if _grpc_server is not None:
            _logger.info("Finalizing gRPC server shutdown...")
            _grpc_server.stop(grace=CONFIG.grpc_server.grace_period_seconds)
        if _mapped_request_client is not None:
            _logger.info("Closing mapped-request gRPC client channel...")
            _mapped_request_client.close()
        _logger.info("Intermediate VoR Partition shutdown complete.")


if __name__ == "__main__":
    main()