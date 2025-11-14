"""
------------------------------------------------------------
 Modul:    psmo-partition/grpc_json_handler.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    This plant-specific M+O handler module manages the
    inter-process communication via Remote Procedure Calls
    and Queues. It includes a thread to receive data from
    the gRPC-Client (cpc-partition) as a gRPC-Server.
    The content of the messages are defined by the .proto-
    file and contain:
        - id: str = Timestamp
        - source: str = {"default", "OPCUA", "MODBUSTCP"}
        - data: str = JSON-Payload
    For further processing the content of the queues can
    be extracted by another process.

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

from threading import Thread, Event
import json
import logging
from queue import Queue
from pathlib import Path

import grpc
from concurrent import futures
from google.protobuf import empty_pb2
import jsontransfer_pb2_grpc

_logger = logging.getLogger(__name__)

project_root = Path(__file__).resolve().parents[1]
rel_base = project_root / "certificates" / "grpc"
abs_base = Path("/certificates/grpc")

cert_base = rel_base if rel_base.exists() else abs_base

SERVER_CERT = cert_base / "server" / "server.crt"
SERVER_KEY  = cert_base / "server" / "server.key"
CA_CERT     = cert_base / "ca"     / "ca.crt"   # CA, die die CLIENT-Zertifikate signiert

def _load_server_credentials() -> grpc.ServerCredentials:
    """
    Baut die Server-Credentials für mTLS:
      - SERVER_KEY / SERVER_CERT: Identität dieses gRPC-Servers
      - CA_CERT: CA, der die Client-Zertifikate vertrauen müssen
    """
    try:
        private_key = SERVER_KEY.read_bytes()
        certificate_chain = SERVER_CERT.read_bytes()
        root_certificates = CA_CERT.read_bytes()
    except FileNotFoundError as e:
        _logger.error(f"TLS file not found: {e}")
        raise
    except Exception as e:
        _logger.error(f"Error loading TLS certificates: {e}")
        raise

    # require_client_auth=True erzwingt mTLS (Client muss Zertifikat vorweisen)
    return grpc.ssl_server_credentials(
        private_key_certificate_chain_pairs=[(private_key, certificate_chain)],
        root_certificates=root_certificates,
        require_client_auth=True,
    )

_SERVER_CREDS = _load_server_credentials()


class JsonSenderServicer(jsontransfer_pb2_grpc.JsonSenderServicer):
    def __init__(self, opcua_message_queue: Queue = None, modbustcp_message_queue: Queue = None):
        self._opcua_queue = opcua_message_queue
        self._modbustcp_queue = modbustcp_message_queue

    def SendJson(self, request, context):
        _logger.debug("Received JSON message")

        try:
            data = json.loads(request.json_payload)
            if request.source == "OPCUA":
                _logger.warning(
                    "Received data with length %d from OPC UA source on timestamp %s.",
                    len(data),
                    request.id,
                )
                _logger.debug("Parsed data: %s", data)

                if self._opcua_queue is not None:
                    self._opcua_queue.put(
                        {
                            "timestamp": request.id,
                            "source": request.source,
                            "data": data,
                        }
                    )
                    _logger.warning("Added payload to OPCUA queue.")

            elif request.source == "MODBUSTCP":
                _logger.warning(
                    "Received data with length %d from ModbusTCP source on timestamp %s.",
                    len(data),
                    request.id,
                )
                _logger.debug("Parsed data: %s", data)

                if self._modbustcp_queue is not None:
                    self._modbustcp_queue.put(
                        {
                            "timestamp": request.id,
                            "source": request.source,
                            "data": data,
                        }
                    )
                    _logger.warning("Added payload to ModbusTCP queue.")

            else:
                _logger.error("Received call from unknown source '%s'.", request.source)
                _logger.debug("Parsed data: %s", data)

        except Exception as e:
            _logger.error("Failed to parse JSON: %s", e)

        return empty_pb2.Empty()


class JSON_gRPC_Thread(Thread):
    def __init__(self, opcua_message_queue: Queue = None, modbustcp_message_queue: Queue = None):
        super().__init__(name="gRPC-Server", daemon=True)
        self._stop_event = Event()
        self._opcua_queue = opcua_message_queue
        self._modbustcp_queue = modbustcp_message_queue
        self._server = None

    def run(self):
        try:
            server = grpc.server(
                futures.ThreadPoolExecutor(max_workers=2)
            )  # TODO: ggf. max_workers reduzieren

            jsontransfer_pb2_grpc.add_JsonSenderServicer_to_server(
                JsonSenderServicer(
                    opcua_message_queue=self._opcua_queue,
                    modbustcp_message_queue=self._modbustcp_queue,
                ),
                server,
            )

            # >>> mTLS: secure statt insecure
            server.add_secure_port("[::]:50051", _SERVER_CREDS)
            _logger.info("mTLS gRPC-Server started on port 50051")

            self._server = server
        except Exception as e:
            _logger.error(f"Error starting gRPC-Server: {e}")
            return

        if self._server is not None:
            self._server.start()
            self._server.wait_for_termination()

    def stop(self):
        self._stop_event.set()
        if self._server is not None:
            _logger.info("Stopping gRPC-Server...")
            self._server.stop(grace=None)
