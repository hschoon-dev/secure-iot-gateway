"""Typed CPC endpoint service exposed through gRPC with mutual TLS."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from concurrent import futures
from pathlib import Path

import grpc

import pipeline_pb2
import pipeline_pb2_grpc
from flask_server_bridge.flask_server_bridge import FlaskServerBridge


_logger = logging.getLogger(__name__)
EXPECTED_CLIENT_CN = os.getenv(
    "CPC_PIPELINE_EXPECTED_CLIENT_CN", "grpc-client-intermediate-vor-cpc"
)


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


def _decode_wire_value(value: str):
    """Recover scalar types from the protobuf text representation."""
    normalized = value.strip()
    if normalized.lower() in ("true", "false"):
        return normalized.lower() == "true"
    try:
        numeric = float(normalized)
        return int(numeric) if numeric.is_integer() else numeric
    except ValueError:
        return value


def _cert_base() -> Path:
    root = Path(os.getenv("SIOT_SECRETS_ROOT", "/run/siot-secrets"))
    return Path(
        os.getenv(
            "CPC_PIPELINE_CERT_BASE",
            root / "cpc-partition" / "certificates" / "pipeline",
        )
    )


class CpcService(pipeline_pb2_grpc.CpcServiceServicer):
    def __init__(self, bridge: FlaskServerBridge):
        # This object owns the existing OPC UA and Modbus registries. Its Flask
        # routes remain available for legacy tests, but no HTTP server is
        # started in the deployment.
        self._opcua = bridge.opcua_registry
        self._modbus = bridge.modbus_registry
        self._statuses: dict[str, tuple[bool, str, dict[str, str]]] = {}
        self._lock = threading.RLock()

    def _resolve(self, name: str) -> tuple[str, str]:
        opcua = self._opcua.resolve(name)
        if opcua:
            return "opcua", opcua
        modbus = self._modbus.resolve(name)
        if modbus:
            return "modbus", modbus
        raise ValueError(f"unknown or ambiguous endpoint: {name}")

    def ReadValues(self, request, context):
        _require_client_identity(context, EXPECTED_CLIENT_CN)
        try:
            resolved: dict[str, tuple[str, str]] = {
                raw: self._resolve(raw) for raw in request.names
            }
            opcua_names = sorted(
                {name for protocol, name in resolved.values() if protocol == "opcua"}
            )
            modbus_names = sorted(
                {name for protocol, name in resolved.values() if protocol == "modbus"}
            )
            fetched: dict[str, object] = {}
            if opcua_names:
                fetched.update(asyncio.run(self._opcua.fetch(opcua_names, timeout_s=3.0)))
            if modbus_names:
                fetched.update(self._modbus.fetch(modbus_names))

            values = []
            for raw, (_protocol, name) in resolved.items():
                value = fetched.get(name)
                if value is None:
                    raise RuntimeError(f"read returned no value for {raw}")
                values.append(
                    pipeline_pb2.EndpointValue(name=raw, value=str(value))
                )
            return pipeline_pb2.ReadValuesResponse(
                success=True, message="values read", values=values
            )
        except Exception as exc:
            _logger.error("CPC read failed: %s", exc)
            return pipeline_pb2.ReadValuesResponse(
                success=False, message=str(exc)
            )

    def Apply(self, request, context):
        _require_client_identity(context, EXPECTED_CLIENT_CN)
        raw_values = {
            item.name: _decode_wire_value(item.value) for item in request.values
        }
        try:
            opcua_values = {}
            modbus_values = {}
            for raw, value in raw_values.items():
                protocol, resolved = self._resolve(raw)
                if protocol == "opcua":
                    opcua_values[resolved] = value
                else:
                    modbus_values[resolved] = value

            results: dict[str, dict] = {}
            if opcua_values:
                results.update(asyncio.run(self._opcua.write(opcua_values, timeout_s=3.0)))
            if modbus_values:
                results.update(self._modbus.write(modbus_values, verify_readback=True))
            failures = {
                name: result
                for name, result in results.items()
                if result.get("status") != "ok"
            }
            if failures or len(results) != len(raw_values):
                raise RuntimeError(f"CPC write/readback failed: {failures or results}")

            with self._lock:
                self._statuses[request.request_id] = (
                    True,
                    "write and readback verified",
                    raw_values,
                )
            _logger.info(
                "CPC applied request %s with verified readback: %s",
                request.request_id,
                raw_values,
            )
            return pipeline_pb2.ApplyResponse(
                success=True, message="write and readback verified"
            )
        except Exception as exc:
            with self._lock:
                self._statuses[request.request_id] = (False, str(exc), raw_values)
            _logger.error("CPC apply failed for %s: %s", request.request_id, exc)
            return pipeline_pb2.ApplyResponse(success=False, message=str(exc))

    def GetStatus(self, request, context):
        _require_client_identity(context, EXPECTED_CLIENT_CN)
        with self._lock:
            status = self._statuses.get(request.request_id)
        if status is None:
            return pipeline_pb2.StatusResponse(found=False)
        success, message, values = status
        return pipeline_pb2.StatusResponse(
            found=True,
            success=success,
            message=message,
            applied_values=[
                pipeline_pb2.EndpointValue(name=name, value=str(value))
                for name, value in values.items()
            ],
        )


def build_pipeline_server(bridge: FlaskServerBridge):
    base = _cert_base()
    credentials = grpc.ssl_server_credentials(
        [(
            (base / "server" / "server.key").read_bytes(),
            (base / "server" / "server.crt").read_bytes(),
        )],
        root_certificates=(base / "ca" / "ca.crt").read_bytes(),
        require_client_auth=True,
    )
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pipeline_pb2_grpc.add_CpcServiceServicer_to_server(CpcService(bridge), server)
    bound = server.add_secure_port("[::]:50053", credentials)
    if bound == 0:
        raise RuntimeError("failed to bind CPC pipeline gRPC server")
    return server
