"""
------------------------------------------------------------
 Modul:    mapped_request_client/mapped_request_client.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    mTLS gRPC client used by the Intermediate VoR partition to forward
    mapped requests directly to intermediate-vor-partition-cpc.

    MIGRATION: Replaces the previous shared-database write (first
    MariaDB, then a shared SQLite file) with a direct gRPC call. The
    Intermediate VoR partition no longer touches any database itself;
    intermediate-vor-partition-cpc now owns storage entirely (in its
    own local-only SQLite database) and is reached only via this stub.

 Autor(en):
    - Heiko Schoon (migration from shared database to gRPC forwarding)

 Maintainer:
    - tbd
------------------------------------------------------------
"""

import json
import logging
from pathlib import Path
from typing import Any, List, Optional

import grpc

import mapped_request_pb2
import mapped_request_pb2_grpc
from config_loader import MappedRequestClientConfig

_logger = logging.getLogger(__name__)


class MappedRequestClient:
    """
    Sends mapped requests to the intermediate-vor-partition-cpc gRPC server.

    Duck-type compatible with the previous DatabaseManager: exposes
    `submit_mapped_request(...)` with the same field set that
    `insert_or_update_request(...)` used to accept, so the calling code in
    mapping_verification.py only needed to change what it calls, not how
    it builds its data.
    """

    def __init__(self, config: MappedRequestClientConfig):
        self._config = config
        self._channel = self._build_channel(config)
        self._stub = mapped_request_pb2_grpc.MappedRequestServiceStub(self._channel)
        _logger.info(
            f"Mapped-request gRPC client ready, target={config.host}:{config.port} (mTLS)"
        )

    @staticmethod
    def _build_channel(config: MappedRequestClientConfig) -> grpc.Channel:
        certs = config.certs
        ca_bytes         = Path(certs.ca_cert).read_bytes()
        client_key_bytes = Path(certs.client_key).read_bytes()
        client_crt_bytes = Path(certs.client_cert).read_bytes()

        creds = grpc.ssl_channel_credentials(
            root_certificates=ca_bytes,
            private_key=client_key_bytes,
            certificate_chain=client_crt_bytes,
        )
        target = f"{config.host}:{config.port}"
        return grpc.secure_channel(target, creds)

    @staticmethod
    def _to_json_string(value: Any) -> str:
        """Same convention the old DatabaseManager used: '' stands for None."""
        if value is None:
            return ""
        try:
            return json.dumps(value, default=str)
        except (TypeError, ValueError) as e:
            _logger.warning(f"Could not JSON-serialize {type(value)}: {e}, using str()")
            return json.dumps(str(value))

    def submit_mapped_request(
        self,
        request_id: str,
        generation_timestamp: Any,
        description: Any,
        impact: str,
        priority: int,
        tags: Any,
        affected_endpoint_list: List,
    ) -> bool:
        """
        Forward a mapped request to intermediate-vor-partition-cpc.

        Args mirror the previous DatabaseManager.insert_or_update_request(...)
        signature. Complex fields are JSON-encoded exactly as they were for
        database storage, so intermediate-vor-partition-cpc's own SQLite
        DatabaseManager.insert_or_update_request(...) can be called
        unchanged on receipt.

        Returns:
            True if intermediate-vor-partition-cpc acknowledged and stored
            the request, False otherwise (network/RPC error or rejection).
        """
        ts_str = (
            generation_timestamp.isoformat()
            if hasattr(generation_timestamp, "isoformat")
            else str(generation_timestamp)
        )

        message = mapped_request_pb2.MappedRequestMessage(
            request_id=request_id,
            generation_timestamp=ts_str,
            description=self._to_json_string(description),
            impact=impact or "",
            priority=int(priority),
            tags=self._to_json_string(tags),
            affected_endpoint_list=self._to_json_string(affected_endpoint_list),
        )

        try:
            ack = self._stub.Submit(message, timeout=self._config.timeout_seconds)
        except grpc.RpcError as e:
            code = e.code() if hasattr(e, "code") else None
            _logger.error(
                f"gRPC error submitting mapped request {request_id} to "
                f"intermediate-vor-partition-cpc: {code}: {e}"
            )
            return False

        if ack.accepted:
            _logger.debug(f"Mapped request acknowledged by CPC partition: {request_id}")
        else:
            _logger.error(
                f"intermediate-vor-partition-cpc rejected mapped request {request_id}: {ack.detail}"
            )

        return ack.accepted

    def close(self) -> None:
        """Close the underlying gRPC channel (call on shutdown)."""
        try:
            self._channel.close()
        except Exception as e:
            _logger.warning(f"Error closing mapped-request gRPC channel: {e}")
