"""Default MariaDB consumer using the typed CPC gRPC/mTLS service."""

from __future__ import annotations

import logging
import signal
import threading
from pathlib import Path

from config_loader import load_config
from db_manager import DatabaseManager
from pipeline_server import CpcClient, _cert_base, process_endpoint_rules


_logger = logging.getLogger(__name__)


def _database(config) -> DatabaseManager:
    db = config.mariadb
    return DatabaseManager(
        host=db.host,
        port=db.port,
        user=db.user,
        password=db.password,
        database=db.database,
        pool_name=db.pool_name,
        pool_size=db.pool_size,
    )


def main() -> None:
    config = load_config(
        path=Path(__file__).parent / "config" / "settings.yaml",
        base_dir=Path(__file__).parent,
    )
    logging.basicConfig(
        level=getattr(logging, config.logging.log_level.upper(), logging.INFO),
        format="[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d] - %(message)s",
    )
    database = _database(config)
    cpc = CpcClient(_cert_base())
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_args: stopped.set())
    signal.signal(signal.SIGINT, lambda *_args: stopped.set())
    _logger.info("MariaDB consumer started with CPC gRPC/mTLS transport")

    while not stopped.is_set():
        request = database.pull_next_request()
        if request is None:
            stopped.wait(config.processing.idle_sleep_seconds)
            continue
        try:
            applied = process_endpoint_rules(
                cpc,
                request["request_id"],
                request["affected_endpoint_list"],
            )
            _logger.info(
                "Applied persisted request %s with CPC readback: %s",
                request["request_id"],
                applied,
            )
        except Exception:
            # The historic stored procedure is at-most-once and deletes during
            # dequeue. Never hide this failure; production retry/dead-letter
            # semantics remain a separate persistence-hardening task.
            _logger.exception(
                "Persisted request %s failed after atomic dequeue",
                request.get("request_id", "unknown"),
            )


if __name__ == "__main__":
    main()
