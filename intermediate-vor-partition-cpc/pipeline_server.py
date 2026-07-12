"""Optional typed mTLS processing path between mapping and the CPC.

The existing MariaDB polling path remains the production default in main.py.
This server is selected explicitly with PIPELINE_MODE=grpc (used by the E2E
acceptance test) and acknowledges only after CPC write/readback succeeds.
"""

from __future__ import annotations

import logging
import operator
import os
import re
from concurrent import futures
from pathlib import Path

import grpc

import pipeline_pb2
import pipeline_pb2_grpc

_logger = logging.getLogger(__name__)
EXPECTED_CLIENT_CN = os.getenv(
    "VOR_CPC_EXPECTED_CLIENT_CN", "grpc-client-intermediate-vor"
)
_FIXED_REQUIREMENTS = {
    "TestObject:KeyPersonnelPresent": "True",
    "TestObject:SystemAvailable": "True",
    "TestObject:OperationMode": "Idle",
    "TestObject:Warning": "none",
}
_CONDITION = re.compile(r"^\s*(==|<=|>=|<|>)\s*(-?(?:\d+(?:\.\d*)?|\.\d+))\s*$")
_OPERATORS = {
    "==": operator.eq,
    "<=": operator.le,
    ">=": operator.ge,
    "<": operator.lt,
    ">": operator.gt,
}


def _require_client_identity(context, expected_cn: str) -> None:
    common_names = {
        value.decode("utf-8", errors="strict")
        for value in context.auth_context().get("x509_common_name", ())
    }
    if expected_cn not in common_names:
        context.abort(
            grpc.StatusCode.PERMISSION_DENIED,
            "client certificate is valid but not authorized for this service",
        )


def _cert_base() -> Path:
    root = Path(os.getenv("SIOT_SECRETS_ROOT", "/run/siot-secrets"))
    return Path(
        os.getenv(
            "VOR_CPC_CERT_BASE",
            root / "intermediate-vor-partition-cpc" / "certificates" / "pipeline",
        )
    )


class CpcClient:
    def __init__(self, cert_base: Path):
        self._base = cert_base
        self._target = os.getenv("CPC_PIPELINE_TARGET", "cpc-partition:50053")
        self._server_name = os.getenv("CPC_PIPELINE_SERVER_NAME", "cpc-partition")

    def _channel(self):
        credentials = grpc.ssl_channel_credentials(
            root_certificates=(self._base / "ca" / "ca.crt").read_bytes(),
            private_key=(self._base / "client" / "client.key").read_bytes(),
            certificate_chain=(self._base / "client" / "client.crt").read_bytes(),
        )
        return grpc.secure_channel(
            self._target,
            credentials,
            options=(("grpc.ssl_target_name_override", self._server_name),),
        )

    def read_values(self, names: list[str]) -> dict[str, str]:
        with self._channel() as channel:
            response = pipeline_pb2_grpc.CpcServiceStub(channel).ReadValues(
                pipeline_pb2.ReadValuesRequest(names=names), timeout=5.0
            )
        if not response.success:
            raise RuntimeError(f"CPC read rejected: {response.message}")
        return {item.name: item.value for item in response.values}

    def apply(self, request_id: str, values: dict[str, float]) -> None:
        with self._channel() as channel:
            response = pipeline_pb2_grpc.CpcServiceStub(channel).Apply(
                pipeline_pb2.ApplyRequest(
                    request_id=request_id,
                    values=[
                        pipeline_pb2.EndpointValue(name=name, value=str(value))
                        for name, value in values.items()
                    ],
                ),
                timeout=5.0,
            )
        if not response.success:
            raise RuntimeError(f"CPC apply rejected: {response.message}")


def _effective_value(current: float, change_type: str) -> float:
    kind, separator, raw = change_type.partition(",")
    if not separator:
        raise ValueError(f"invalid change type: {change_type!r}")
    if kind.strip() == "relative":
        return current * (1 + float(raw.strip().removesuffix("%")) / 100)
    if kind.strip() == "absolute":
        return float(raw.strip())
    raise ValueError(f"unsupported change type: {change_type!r}")


class ProcessingService(pipeline_pb2_grpc.ProcessingServiceServicer):
    def __init__(self, cpc: CpcClient):
        self._cpc = cpc

    def Process(self, request, context):
        _require_client_identity(context, EXPECTED_CLIENT_CN)
        try:
            endpoint_names = sorted({item.name for item in request.endpoints})
            if not endpoint_names:
                raise ValueError("mapped request contains no endpoints")
            values = self._cpc.read_values(list(_FIXED_REQUIREMENTS) + endpoint_names)
            for name, required in _FIXED_REQUIREMENTS.items():
                if values.get(name) != required:
                    raise ValueError(f"acceptance requirement failed for {name}")

            applied: dict[str, float] = {}
            for endpoint in request.endpoints:
                if endpoint.name not in values:
                    raise ValueError(f"CPC returned no value for {endpoint.name}")
                effective = _effective_value(float(values[endpoint.name]), endpoint.change_type)
                match = _CONDITION.fullmatch(endpoint.condition)
                if match is None or not _OPERATORS[match.group(1)](
                    effective, float(match.group(2))
                ):
                    raise ValueError(f"mapping constraint failed for {endpoint.name}")
                if endpoint.name in applied and applied[endpoint.name] != effective:
                    raise ValueError(f"conflicting mapped values for {endpoint.name}")
                applied[endpoint.name] = effective

            self._cpc.apply(request.request_id, applied)
            return pipeline_pb2.ProcessResponse(
                success=True,
                message="request accepted, verified, and applied",
                applied_values=[
                    pipeline_pb2.EndpointValue(name=name, value=str(value))
                    for name, value in applied.items()
                ],
            )
        except Exception as exc:
            _logger.error("Processing failed for %s: %s", request.request_id, exc)
            return pipeline_pb2.ProcessResponse(success=False, message=str(exc))


def build_pipeline_server():
    base = _cert_base()
    credentials = grpc.ssl_server_credentials(
        [((base / "server" / "server.key").read_bytes(),
          (base / "server" / "server.crt").read_bytes())],
        root_certificates=(base / "ca" / "ca.crt").read_bytes(),
        require_client_auth=True,
    )
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pipeline_pb2_grpc.add_ProcessingServiceServicer_to_server(
        ProcessingService(CpcClient(base)), server
    )
    if server.add_secure_port("[::]:50052", credentials) == 0:
        raise RuntimeError("failed to bind processing gRPC server")
    return server
