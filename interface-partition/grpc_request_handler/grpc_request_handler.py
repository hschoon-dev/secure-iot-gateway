import grpc
from typing import Any
import logging
from pathlib import Path

import request_pb2, request_pb2_grpc

from config_loader import GrpcClientConfig  # only sub-model needed

_logger = logging.getLogger(__name__)


def send_request_as_grpc(request: dict[str, Any], config: GrpcClientConfig):
    """
    Send a VoR request to the intermediate-vor-partition via mTLS gRPC.

    Args:
        request: The request dictionary to send.
        config:  GrpcClientConfig sub-model from InterfaceConfig,
                 providing target_host, port, timeout_seconds, and cert paths.
    """
    certs = config.certs
    try:
        client_key  = Path(certs.client_key).read_bytes()
        client_cert = Path(certs.client_cert).read_bytes()
        ca_cert     = Path(certs.ca_cert).read_bytes()
    except Exception as e:
        _logger.error(f"Error reading TLS files: {e}")
        return

    grpc_creds = grpc.ssl_channel_credentials(
        root_certificates=ca_cert,
        private_key=client_key,
        certificate_chain=client_cert,
    )

    target = f"{config.target_host}:{config.port}"

    try:
        with grpc.secure_channel(target, grpc_creds) as channel:
            stub = request_pb2_grpc.RequestServiceStub(channel)
            _logger.warning(f"Request-Dict: {request}")

            req = request_pb2.SubmitRequest(
                issuer_id              = request["issuer_id"],
                issuer_characteristics = request["issuer_characteristics"],
                timestamp              = request["timestamp"],
                description            = request["description"],
                impact                 = request["impact"],
                parameters             = request["parameters"],
                modification           = request["modification"],
                priority               = int(request["prio"]),
                request_id             = request["request_id"],
            )

            try:
                _logger.warning("Sending Request via gRPC")
                resp = stub.Submit(req, timeout=config.timeout_seconds)
            except grpc.RpcError as e:
                _logger.error(f"RPC failed: {e.code().name} - {e.details()}")
                return

            _logger.warning(f"ACK: {resp.ack}")
            _logger.warning(f"Server timestamp: {resp.server_timestamp}")
    except Exception as e:
        _logger.error(f"Error: {e}")