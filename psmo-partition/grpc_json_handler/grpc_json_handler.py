"""
------------------------------------------------------------
 Modul:    psmo-partition/grpc_json_handler.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    Plant-specific M+O handler module for gRPC receiving and
    forwarding payloads into bounded queues (drop-oldest).

 Autor(en):
    - Heiko Schoon

 Maintainer:
    - heiko.schoon@hs-emden-leer.de

 Hinweis:
    Ongoing development.
------------------------------------------------------------
"""

from threading import Thread, Event
import json
import logging
from queue import Queue, Full, Empty
from pathlib import Path

import grpc
from concurrent import futures
from google.protobuf import empty_pb2

import jsontransfer_pb2_grpc

_logger = logging.getLogger(__name__)

project_root = Path(__file__).resolve().parents[1]
rel_base = project_root / "certs"
abs_base = Path("/certs")
cert_base = rel_base if rel_base.exists() else abs_base

SERVER_CERT = cert_base / "server" / "server.crt"
SERVER_KEY  = cert_base / "server" / "server.key"
CA_CERT     = cert_base / "ca"     / "ca.crt"   # CA that signs CLIENT certs


def _load_server_credentials() -> grpc.ServerCredentials:
    """
    Build server credentials for mTLS:
      - SERVER_KEY / SERVER_CERT: server identity
      - CA_CERT: CA trusted for client certificates
    """
    try:
        private_key = SERVER_KEY.read_bytes()
        certificate_chain = SERVER_CERT.read_bytes()
        root_certificates = CA_CERT.read_bytes()
    except FileNotFoundError as e:
        _logger.error("TLS file not found: %s", e)
        raise
    except Exception as e:
        _logger.error("Error loading TLS certificates: %s", e)
        raise

    return grpc.ssl_server_credentials(
        private_key_certificate_chain_pairs=[(private_key, certificate_chain)],
        root_certificates=root_certificates,
        require_client_auth=True,
    )


_SERVER_CREDS = _load_server_credentials()


class JsonSenderServicer(jsontransfer_pb2_grpc.JsonSenderServicer):
    def __init__(self, opcua_message_queue: Queue | None = None, modbustcp_message_queue: Queue | None = None):
        self._opcua_queue = opcua_message_queue
        self._modbustcp_queue = modbustcp_message_queue

    @staticmethod
    def _put_latest(queue: Queue, item) -> None:
        """
        Drop-oldest queue strategy:
        - never blocks producer
        - bounded queue stays bounded
        - latest value wins
        """
        try:
            queue.put_nowait(item)
        except Full:
            try:
                queue.get_nowait()  # drop oldest
            except Empty:
                pass
            queue.put_nowait(item)

    def SendJson(self, request, context):
        _logger.debug("Received JSON message: source=%s ts=%s", getattr(request, "source", None), getattr(request, "id", None))

        try:
            data = json.loads(request.json_payload)
        except json.JSONDecodeError:
            _logger.error("Failed to parse JSON (invalid JSON). source=%s ts=%s", request.source, request.id)
            return empty_pb2.Empty()
        except Exception as e:
            _logger.error("Failed to parse JSON: %s. source=%s ts=%s", e, request.source, request.id)
            return empty_pb2.Empty()

        msg = {
            "timestamp": request.id,
            "source": request.source,
            "data": data,
        }

        if request.source == "OPCUA":
            # Hot path -> debug (not warning)
            _logger.debug("OPCUA payload received: size=%d ts=%s", len(data) if hasattr(data, "__len__") else -1, request.id)
            if self._opcua_queue is not None:
                self._put_latest(self._opcua_queue, msg)

        elif request.source == "MODBUSTCP":
            _logger.debug("MODBUSTCP payload received: size=%d ts=%s", len(data) if hasattr(data, "__len__") else -1, request.id)
            if self._modbustcp_queue is not None:
                self._put_latest(self._modbustcp_queue, msg)

        else:
            _logger.error("Received call from unknown source '%s'.", request.source)

        return empty_pb2.Empty()


class JSON_gRPC_Thread(Thread):
    def __init__(self, opcua_message_queue: Queue | None = None, modbustcp_message_queue: Queue | None = None):
        super().__init__(name="gRPC-Server", daemon=True)
        self._stop_event = Event()
        self._opcua_queue = opcua_message_queue
        self._modbustcp_queue = modbustcp_message_queue
        self._server: grpc.Server | None = None

    def run(self):
        try:
            server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))

            jsontransfer_pb2_grpc.add_JsonSenderServicer_to_server(
                JsonSenderServicer(
                    opcua_message_queue=self._opcua_queue,
                    modbustcp_message_queue=self._modbustcp_queue,
                ),
                server,
            )

            server.add_secure_port("[::]:50051", _SERVER_CREDS)
            _logger.info("mTLS gRPC-Server started on port 50051")

            self._server = server
        except Exception as e:
            _logger.error("Error starting gRPC-Server: %s", e)
            return

        self._server.start()
        self._server.wait_for_termination()

    def stop(self):
        self._stop_event.set()
        if self._server is not None:
            _logger.info("Stopping gRPC-Server...")
            self._server.stop(grace=None)
