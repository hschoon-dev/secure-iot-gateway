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
import os
from queue import Queue, Full, Empty
from pathlib import Path

import grpc
from concurrent import futures
from google.protobuf import empty_pb2

import jsontransfer_pb2_grpc

from config_loader import GrpcServerConfig, GrpcServerCerts  # only sub-model needed

_logger = logging.getLogger(__name__)
EXPECTED_CLIENT_CN = os.getenv("PSMO_JSON_EXPECTED_CLIENT_CN", "grpc-client-cpc")

def _require_client_identity(context, expected_cn: str) -> None:
    common_names = {
        value.decode("utf-8", errors="strict")
        for value in context.auth_context().get("x509_common_name", ())
    }
    if expected_cn not in common_names:
        _logger.warning("Rejected mTLS client identities: %s", sorted(common_names))
        context.abort(
            grpc.StatusCode.PERMISSION_DENIED,
            "client certificate is valid but not authorized for this service",
        )

def _resolve_grpc_cert_base() -> Path | None:
    secrets_root = Path(os.getenv("SIOT_SECRETS_ROOT", "/run/siot-secrets"))
    runtime_base = Path(
        os.getenv(
            "PSMO_GRPC_CERT_BASE",
            str(secrets_root / "psmo-partition" / "certs"),
        )
    )

    if runtime_base.exists():
        return runtime_base
    if os.getenv("ALLOW_LEGACY_SECRETS", "false").lower() in ("1", "true", "yes", "on"):
        return None
    raise FileNotFoundError(
        f"Runtime gRPC certificate directory not found: {runtime_base}. "
        "Legacy fallback is disabled."
    )
def _load_server_credentials(certs: "GrpcServerCerts") -> grpc.ServerCredentials:
    """
    Build server credentials for mTLS from a GrpcServerCerts config instance:
      - server_key / server_cert: server identity
      - ca_cert: CA trusted for client certificates
    """
    cert_base = _resolve_grpc_cert_base()
    if cert_base is not None:
        server_key = cert_base / "server" / "server.key"
        server_cert = cert_base / "server" / "server.crt"
        ca_cert = cert_base / "ca" / "ca.crt"
    else:
        server_key = Path(certs.server_key)
        server_cert = Path(certs.server_cert)
        ca_cert = Path(certs.ca_cert)
    try:
        private_key = server_key.read_bytes()
        certificate_chain = server_cert.read_bytes()
        root_certificates = ca_cert.read_bytes()
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
        _require_client_identity(context, EXPECTED_CLIENT_CN)
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
    def __init__(
        self,
        opcua_message_queue: Queue | None = None,
        modbustcp_message_queue: Queue | None = None,
        config: GrpcServerConfig | None = None,
    ):
        super().__init__(name="gRPC-Server", daemon=True)
        self._stop_event = Event()
        self._opcua_queue = opcua_message_queue
        self._modbustcp_queue = modbustcp_message_queue
        self._config = config
        self._server: grpc.Server | None = None

    def run(self):
        if self._config is None:
            _logger.error("GrpcServerConfig not provided to JSON_gRPC_Thread.")
            return

        try:
            server_creds = _load_server_credentials(self._config.certs)

            server = grpc.server(futures.ThreadPoolExecutor(max_workers=self._config.max_workers))

            jsontransfer_pb2_grpc.add_JsonSenderServicer_to_server(
                JsonSenderServicer(
                    opcua_message_queue=self._opcua_queue,
                    modbustcp_message_queue=self._modbustcp_queue,
                ),
                server,
            )

            server.add_secure_port(f"[::]:{self._config.port}", server_creds)
            _logger.info("mTLS gRPC-Server started on port %d", self._config.port)

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
