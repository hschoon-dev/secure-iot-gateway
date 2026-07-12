"""mTLS client for the mapped-request processing partition."""

from __future__ import annotations

import os
from pathlib import Path

import grpc

import pipeline_pb2
import pipeline_pb2_grpc


def _cert_base() -> Path:
    root = Path(os.getenv("SIOT_SECRETS_ROOT", "/run/siot-secrets"))
    return Path(
        os.getenv(
            "VOR_PIPELINE_CERT_BASE",
            root / "intermediate-vor-partition" / "certificates" / "pipeline",
        )
    )


def process_mapped_request(mapped: dict) -> None:
    base = _cert_base()
    credentials = grpc.ssl_channel_credentials(
        root_certificates=(base / "ca" / "ca.crt").read_bytes(),
        private_key=(base / "client" / "client.key").read_bytes(),
        certificate_chain=(base / "client" / "client.crt").read_bytes(),
    )
    target = os.getenv(
        "VOR_CPC_PROCESSOR_TARGET", "intermediate-vor-partition-cpc:50052"
    )
    server_name = os.getenv(
        "VOR_CPC_PROCESSOR_SERVER_NAME", "intermediate-vor-partition-cpc"
    )
    request = pipeline_pb2.MappedRequest(
        request_id=mapped["request_id"],
        generation_timestamp=mapped["generation_timestamp"],
        description=mapped["description"],
        impact=mapped["impact"],
        priority=mapped["priority"],
        endpoints=[
            pipeline_pb2.EndpointRule(
                name=item[0],
                change_type=item[1],
                unit=item[2],
                condition=item[3],
            )
            for item in mapped["affected_endpoint_list"]
        ],
    )
    try:
        with grpc.secure_channel(
            target,
            credentials,
            options=(("grpc.ssl_target_name_override", server_name),),
        ) as channel:
            response = pipeline_pb2_grpc.ProcessingServiceStub(channel).Process(
                request, timeout=8.0
            )
    except grpc.RpcError as exc:
        raise RuntimeError(
            f"processing RPC failed: {exc.code().name} - {exc.details()}"
        ) from exc
    if not response.success:
        raise RuntimeError(f"processing rejected request: {response.message}")
