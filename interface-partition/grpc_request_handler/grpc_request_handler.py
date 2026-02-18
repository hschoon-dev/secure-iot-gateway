import grpc
from typing import Any
import logging
from pathlib import Path

import request_pb2, request_pb2_grpc

_logger = logging.getLogger(__name__)

# Target set via docker-compose (service DNS name on the default network)
#TARGET_HOST = "intermediate-vor-partition"
TARGET_HOST = "192.168.156.15"
TARGET_PORT = 50051
SERVER_NAME = "grpc-server"  # must match server cert SAN/CN # TODO: Change!

# Prefer project-relative certs; fallback to an absolute mount location.
project_root = Path(__file__).resolve().parents[1]
rel_base = project_root / "certificates" / "grpc"
abs_base = Path("/certificates/grpc")

cert_base = rel_base if rel_base.exists() else abs_base

CLIENT_CERT = cert_base / "client" / "client.crt"
CLIENT_KEY  = cert_base / "client" / "client.key"
CA_CERT     = cert_base / "ca"     / "ca.crt"

def send_request_as_grpc(request: dict[str, Any]):
    try:
        with open(CLIENT_KEY,"rb") as f: client_key = f.read()
        with open(CLIENT_CERT,"rb") as f: client_cert = f.read()
        with open(CA_CERT,"rb") as f: ca_cert = f.read()
    except Exception as e:
        _logger.error(f"Error reading file: {e}")

    creds = grpc.ssl_channel_credentials(
        root_certificates=ca_cert,
        private_key=client_key,
        certificate_chain=client_cert
    )

    target = f"{TARGET_HOST}:{TARGET_PORT}"

    try:
        with grpc.secure_channel(target, creds) as channel:
            stub = request_pb2_grpc.RequestServiceStub(channel)
            _logger.warning(f"Request-Dict: {request}")

            req = request_pb2.SubmitRequest(
                issuer_id               =   request["issuer_id"],
                issuer_characteristics  =   request["issuer_characteristics"],
                timestamp               =   request["timestamp"],
                description             =   request["description"],
                impact                  =   request["impact"],
                parameters              =   request["parameters"],
                modification            =   request["modification"],
                priority                =   int(request["prio"]), #TODO: Namen checken!
                request_id              =   request["request_id"]
            )

            try:
                _logger.warning(f"Sending Request via gRPC")
                resp = stub.Submit(req, timeout=2.0)
            except grpc.RpcError as e:
                _logger.error(f"RPC failed: {e.code().name} - {e.details()}")
                return

            _logger.warning(f"ACK: {resp.ack}")
            _logger.warning(f"Server timestamp: {resp.server_timestamp}")
    except Exception as e:
        _logger.error(f"Error: {e}")