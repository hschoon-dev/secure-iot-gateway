"""
------------------------------------------------------------
 Modul:    mapped_request_server/mapped_request_server.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    mTLS gRPC server run inside intermediate-vor-partition-cpc that
    receives mapped requests forwarded by intermediate-vor-partition and
    stores them in the local-only SQLite database for the existing
    pull/process loop (see main.py: pull_request_and_process) to consume.

    MIGRATION: Replaces the previous shared-database read/write (first
    MariaDB, then a shared SQLite file) with this inbound gRPC service.
    intermediate-vor-partition no longer has any database access at all;
    it only ever talks to this server. The SQLite database used here is
    private to this partition/container (no shared volume).

 Autor(en):
    - Heiko Schoon (migration from shared database to gRPC forwarding)

 Maintainer:
    - tbd
------------------------------------------------------------
"""

import json
import logging
from concurrent import futures
from pathlib import Path

import grpc

import mapped_request_pb2
import mapped_request_pb2_grpc
from db_manager import DatabaseManager
from config_loader import MappedRequestServerConfig

_logger = logging.getLogger(__name__)


class MappedRequestService(mapped_request_pb2_grpc.MappedRequestServiceServicer):
    """
    Implements the MappedRequestService.Submit RPC: decode the incoming
    message and upsert it into the local SQLite database via the existing
    DatabaseManager, unchanged from when it was fed by the shared database
    layer.
    """

    def __init__(self, db_manager: DatabaseManager):
        self._db_manager = db_manager

    @staticmethod
    def _from_json_string(value: str, default_type: type):
        """Inverse of MappedRequestClient._to_json_string: '' -> None."""
        if not value:
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            _logger.warning(f"Could not parse JSON field: {value!r}")
            return default_type()

    def Submit(self, request, context):
        _logger.debug(
            f"Mapped request received via gRPC: request_id={request.request_id}, "
            f"priority={request.priority}, impact={request.impact}"
        )

        try:
            description = self._from_json_string(request.description, dict)
            tags = self._from_json_string(request.tags, dict)
            affected_endpoint_list = self._from_json_string(
                request.affected_endpoint_list, list
            ) or []

            success = self._db_manager.insert_or_update_request(
                request_id=request.request_id,
                generation_timestamp=request.generation_timestamp,
                description=description,
                impact=request.impact,
                priority=request.priority,
                tags=tags,
                affected_endpoint_list=affected_endpoint_list,
            )
        except Exception as e:
            _logger.error(
                f"Error storing mapped request {request.request_id}: {e}", exc_info=True
            )
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Failed to store mapped request: {e}")
            return mapped_request_pb2.MappedRequestAck(accepted=False, detail=str(e))

        if success:
            _logger.info(f"Mapped request stored locally: {request.request_id}")
            return mapped_request_pb2.MappedRequestAck(accepted=True, detail="stored")

        context.set_code(grpc.StatusCode.INTERNAL)
        context.set_details("Local database upsert failed")
        return mapped_request_pb2.MappedRequestAck(accepted=False, detail="db upsert failed")


def _read_bytes(p: Path) -> bytes:
    return p.read_bytes()


def build_grpc_server(db_manager: DatabaseManager, config: MappedRequestServerConfig):
    """
    Build and return the mTLS gRPC server that receives mapped requests
    from intermediate-vor-partition.

    Args:
        db_manager: DatabaseManager instance for the local-only SQLite DB.
        config:     MappedRequestServerConfig sub-model from VoRCPCConfig,
                    providing port, max_workers, and cert paths.

    Returns:
        (server, bind_addr) tuple — call server.start() to run.
    """
    certs = config.certs

    ca  = _read_bytes(Path(certs.ca_cert))
    key = _read_bytes(Path(certs.server_key))
    crt = _read_bytes(Path(certs.server_cert))

    grpc_creds = grpc.ssl_server_credentials(
        [(key, crt)],
        root_certificates=ca,
        require_client_auth=True,
    )

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=config.max_workers))
    mapped_request_pb2_grpc.add_MappedRequestServiceServicer_to_server(
        MappedRequestService(db_manager), server
    )

    bind_addr = f"[::]:{config.port}"
    server.add_secure_port(bind_addr, grpc_creds)
    return server, bind_addr
