"""Entrypoint for the opt-in typed processing pipeline."""

import logging
import signal
import threading

from pipeline_server import build_pipeline_server


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    server = build_pipeline_server()
    server.start()
    logging.getLogger(__name__).info(
        "Typed processing gRPC server listening on 50052 (mTLS)"
    )
    stopped = threading.Event()

    def stop(_signum, _frame):
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    stopped.wait()
    server.stop(grace=5).wait()


if __name__ == "__main__":
    main()
