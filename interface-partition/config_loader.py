"""
------------------------------------------------------------
 Config:   interface-partition/interface_config.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    Pydantic configuration model for the Interface partition.
    Covers the OPC UA server endpoint, mTLS certificate paths,
    transport limits, gRPC JSON handler, and logging.

 Usage:
    from interface_config import load_config, InterfaceConfig

    config = load_config()               # reads settings.yaml
    config = load_config("custom.yaml")  # custom path
------------------------------------------------------------
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

try:
    import yaml
except ImportError:
    yaml = None

from pydantic import BaseModel, Field, PositiveInt


# ---------------------------------------------------------------------------
# OPC UA server
# ---------------------------------------------------------------------------

class OpcUaServerCerts(BaseModel):
    """Certificate paths for the OPC UA server (asyncua)."""
    server_cert: Path = Field(
        Path("certificates/python-server/interface_server_cert.der"),
        description="DER-encoded server certificate",
    )
    server_key: Path = Field(
        Path("certificates/python-server/interface_server_key.pem"),
        description="PEM-encoded server private key",
    )
    trusted_certs_dir: Path = Field(
        Path("certificates/trusted/certs"),
        description="Directory containing trusted client certificates",
    )


class OpcUaTransportLimits(BaseModel):
    """asyncua TransportLimits parameters."""
    recv_buffer_bytes: PositiveInt = Field(16 * 1024, description="Max receive buffer size in bytes")
    send_buffer_bytes: PositiveInt = Field(16 * 1024, description="Max send buffer size in bytes")
    max_message_bytes: PositiveInt = Field(10 * 1024, description="Max message size in bytes")


class OpcUaServerConfig(BaseModel):
    """Full configuration for the OPC UA server exposed to M+O clients."""
    endpoint: str = Field(
        "opc.tcp://0.0.0.0:4840/freeopcua/server/",
        description="OPC UA endpoint URL",
    )
    application_uri: str = Field(
        "urn:freeopcua:interface_server",
        description="Application URI (must match certificate subjectAltName)",
    )
    namespace_uri: str = Field(
        "idx.request-handler.ua",
        description="Namespace URI registered on the server",
    )
    certs: OpcUaServerCerts = Field(default_factory=OpcUaServerCerts)
    transport_limits: OpcUaTransportLimits = Field(default_factory=OpcUaTransportLimits)


# ---------------------------------------------------------------------------
# gRPC JSON handler (receives data from cpc-partition)
# ---------------------------------------------------------------------------

class GrpcServerCerts(BaseModel):
    """mTLS certificates for the gRPC JSON receiver server."""
    ca_cert: Path = Field(
        Path("certificates/grpc/ca/ca.crt"),
        description="CA certificate used to verify client certs",
    )
    server_cert: Path = Field(
        Path("certificates/grpc/server/server.crt"),
        description="Server certificate for mTLS",
    )
    server_key: Path = Field(
        Path("certificates/grpc/server/server.key"),
        description="Server private key for mTLS",
    )


class GrpcServerConfig(BaseModel):
    """gRPC server that receives JSON data from the CPC partition."""
    port: int = Field(50051, description="Port the gRPC server listens on")
    max_workers: int = Field(4, description="Thread pool size for the gRPC server")
    certs: GrpcServerCerts = Field(default_factory=GrpcServerCerts)


class GrpcClientCerts(BaseModel):
    """mTLS certificates used by the gRPC client towards intermediate-vor-partition."""
    ca_cert:     Path = Field(Path("certificates/grpc/ca/ca.crt"))
    client_cert: Path = Field(Path("certificates/grpc/client/client.crt"))
    client_key:  Path = Field(Path("certificates/grpc/client/client.key"))


class GrpcClientConfig(BaseModel):
    target_host:     str   = Field("intermediate-vor-partition")
    port:            int   = Field(50051)
    timeout_seconds: float = Field(2.0)
    certs: GrpcClientCerts = Field(default_factory=GrpcClientCerts)


# ---------------------------------------------------------------------------
# Queue sizes
# ---------------------------------------------------------------------------

class QueueConfig(BaseModel):
    """In-process Queue sizes between gRPC handler and data manager."""
    opcua_maxsize: int = Field(2, description="Max items in the OPC UA message queue")
    modbustcp_maxsize: int = Field(2, description="Max items in the ModbusTCP message queue")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class LoggingConfig(BaseModel):
    """Rotating-file + console logging configuration."""
    log_file: Path = Field(Path("logs/app.log"), description="Path to the log file")
    log_level: str = Field("WARNING", description="Logging level (DEBUG/INFO/WARNING/ERROR)")
    max_bytes: PositiveInt = Field(1 * 1024 * 1024, description="Max log file size in bytes before rotation")
    backup_count: PositiveInt = Field(3, description="Number of rotated backup files to keep")


# ---------------------------------------------------------------------------
# Top-level model
# ---------------------------------------------------------------------------

class InterfaceConfig(BaseModel):
    """Root configuration for the Interface partition."""
    opcua_server: OpcUaServerConfig = Field(default_factory=OpcUaServerConfig)
    grpc_server: GrpcServerConfig = Field(default_factory=GrpcServerConfig)
    grpc_client: GrpcClientConfig = Field(default_factory=GrpcClientConfig)
    queues: QueueConfig = Field(default_factory=QueueConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def _read_raw(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    ext = path.suffix.lower()
    if ext in (".yaml", ".yml"):
        if yaml is None:
            raise RuntimeError("pyyaml is not installed; cannot load YAML config.")
        return yaml.safe_load(text) or {}
    if ext == ".json":
        return json.loads(text)
    raise ValueError(f"Unsupported config file extension: {ext!r}")


def _resolve_cert_paths(raw: Dict[str, Any], base_dir: Path) -> Dict[str, Any]:
    """
    Resolve all relative Path fields under opcua_server.certs,
    grpc_server.certs and grpc_client.certs against base_dir.

    Importantly, this resolves a field even when it's absent from
    settings.yaml and would otherwise fall back to its Pydantic default:
    a bare relative default (e.g. "certificates/grpc/client/client.crt")
    must still end up anchored to the config volume, not silently left
    relative to whatever the process's cwd happens to be at the time the
    cert file is actually opened.
    """
    cert_sections = [
        ("opcua_server", "certs", OpcUaServerCerts),
        ("grpc_server",  "certs", GrpcServerCerts),
        ("grpc_client",  "certs", GrpcClientCerts),
    ]
    for top_key, sub_key, cert_model in cert_sections:
        raw.setdefault(top_key, {})
        section = raw[top_key].setdefault(sub_key, {})
        for field, field_info in cert_model.model_fields.items():
            value = section.get(field, field_info.default)
            p = Path(value)
            section[field] = str(p if p.is_absolute() else base_dir / p)
    return raw


def _apply_env_overrides(config: InterfaceConfig) -> InterfaceConfig:
    """
    Optional environment-variable overrides.

    OPC UA server : OPCUA_ENDPOINT, OPCUA_APP_URI
    gRPC server   : GRPC_PORT, GRPC_MAX_WORKERS
    Logging       : LOG_LEVEL, LOG_FILE
    """
    env = os.environ

    opcua_data = config.opcua_server.model_dump()
    if v := env.get("OPCUA_ENDPOINT"):
        opcua_data["endpoint"] = v
    if v := env.get("OPCUA_APP_URI"):
        opcua_data["application_uri"] = v

    grpc_data = config.grpc_server.model_dump()
    if v := env.get("GRPC_PORT"):
        grpc_data["port"] = int(v)
    if v := env.get("GRPC_MAX_WORKERS"):
        grpc_data["max_workers"] = int(v)

    grpc_client_data = config.grpc_client.model_dump()
    if v := env.get("GRPC_CLIENT_HOST"):
        grpc_client_data["target_host"] = v
    if v := env.get("GRPC_CLIENT_PORT"):
        grpc_client_data["port"] = int(v)
    if v := env.get("GRPC_CLIENT_TIMEOUT"):
        grpc_client_data["timeout_seconds"] = float(v)

    log_data = config.logging.model_dump()
    if v := env.get("LOG_LEVEL"):
        log_data["log_level"] = v.upper()
    if v := env.get("LOG_FILE"):
        log_data["log_file"] = v

    return InterfaceConfig(
        opcua_server=OpcUaServerConfig.model_validate(opcua_data),
        grpc_server=GrpcServerConfig.model_validate(grpc_data),
        grpc_client=GrpcClientConfig.model_validate(grpc_client_data),
        queues=config.queues,
        logging=LoggingConfig.model_validate(log_data),
    )


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------

# CONFIG_ROOT is where the read-only static config volume is mounted. On the
# Linux VMs this is the actual mount point (e.g. /mnt/config/interface-partition,
# with the "interface-partition" subfolder distinguishing this partition's
# files from siblings like /mnt/config/psmo-partition under the same
# volume). In Docker (local testing) it's the same path, bind-mounted
# read-only from ./config-volume/interface-partition (see docker-compose.yaml).
# Overridable via the CONFIG_ROOT env var for ad-hoc/non-standard layouts.
_DEFAULT_CONFIG_ROOT = Path(os.environ.get("CONFIG_ROOT", "/mnt/config/interface-partition"))
_DEFAULT_SETTINGS = _DEFAULT_CONFIG_ROOT / "settings.yaml"


def load_config(
    path: str | Path = _DEFAULT_SETTINGS,
    base_dir: Path | None = None,
    allow_env: bool = True,
) -> InterfaceConfig:
    """
    Load, validate, and return the Interface partition configuration.

    Args:
        path:      Path to a YAML or JSON settings file. Defaults to
                   settings.yaml under the read-only config volume
                   (CONFIG_ROOT / "settings.yaml").
        base_dir:  Base directory for resolving relative certificate paths.
                   Defaults to the directory containing *path* — i.e. the
                   read-only config volume.
        allow_env: If True, environment variables override file values.

    Returns:
        A fully validated InterfaceConfig instance.
    """
    cfg_path = Path(path)
    base_dir = base_dir or cfg_path.parent

    raw = _read_raw(cfg_path) if cfg_path.exists() else {}
    raw.setdefault("opcua_server", {})
    raw.setdefault("grpc_server", {})
    raw.setdefault("grpc_client", {})
    raw.setdefault("queues", {})
    raw.setdefault("logging", {})

    raw = _resolve_cert_paths(raw, base_dir)
    config = InterfaceConfig.model_validate(raw)

    return _apply_env_overrides(config) if allow_env else config