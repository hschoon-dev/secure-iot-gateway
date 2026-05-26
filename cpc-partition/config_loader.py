"""
------------------------------------------------------------
 Config:   cpc-partition/cpc_config.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    Pydantic configuration model for the CPC partition.
    Covers OPC UA client, Modbus TCP client, shared memory /
    semaphore IPC, and the Flask server bridge.

 Usage:
    from cpc_config import load_config, CPCConfig

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
# Shared sub-models
# ---------------------------------------------------------------------------

class EndpointFiles(BaseModel):
    """Paths to the XML endpoint config and its XSD schema."""
    xml_config: Path = Field(..., description="Path to endpoints XML file")
    xsd_schema: Path = Field(..., description="Path to XSD schema file")


class SharedMemory(BaseModel):
    """POSIX shared-memory segment used for IPC between partitions."""
    name: str = Field(..., description="Name of the shared-memory segment")
    size: PositiveInt = Field(..., description="Size of the segment in bytes")


class Semaphore(BaseModel):
    """Named semaphore used for synchronising shared-memory access."""
    name: str = Field(..., description="Name of the POSIX semaphore")


class ServiceConfig(BaseModel):
    """Full configuration for one protocol client (OPC UA or Modbus TCP)."""
    interval: PositiveInt = Field(1, description="Polling interval in seconds")
    files: EndpointFiles
    shared_memory: SharedMemory
    semaphore: Semaphore


# ---------------------------------------------------------------------------
# Flask bridge sub-model
# ---------------------------------------------------------------------------

class FlaskBridgeConfig(BaseModel):
    """Temporary Flask server bridge (to be replaced by gRPC/mTLS)."""
    host: str = Field("0.0.0.0", description="Bind address for the Flask server")
    port: int = Field(5000, description="Port for the Flask server")
    debug: bool = Field(False, description="Enable Flask debug mode")
    threaded: bool = Field(True, description="Enable threaded request handling")


# ---------------------------------------------------------------------------
# TLS certificates for the gRPC sender
# ---------------------------------------------------------------------------

class GrpcClientCerts(BaseModel):
    """mTLS certificates used by the gRPC sender towards the interface partition."""
    ca_cert: Path = Field(
        Path("certs/ca/ca.crt"),
        description="CA certificate that signed the server cert",
    )
    client_cert: Path = Field(
        Path("certs/client/client.crt"),
        description="Client certificate for mutual TLS",
    )
    client_key: Path = Field(
        Path("certs/client/client.key"),
        description="Private key for the client certificate",
    )


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

class CPCConfig(BaseModel):
    """Root configuration for the CPC partition."""
    opcua: ServiceConfig
    modbustcp: ServiceConfig
    flask_bridge: FlaskBridgeConfig = Field(default_factory=FlaskBridgeConfig)
    grpc_certs: GrpcClientCerts = Field(default_factory=GrpcClientCerts)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_OPCUA_DEFAULTS: Dict[str, Any] = {
    "interval": 1,
    "files": {
        "xml_config": "config/opcua-endpoints_demonstrator.xml",
        "xsd_schema": "config/opcua-endpoints.xsd",
    },
    "shared_memory": {"name": "opcua_shm", "size": 1024 * 10},
    "semaphore": {"name": "opcua_semaphore"},
}

_MODBUSTCP_DEFAULTS: Dict[str, Any] = {
    "interval": 1,
    "files": {
        "xml_config": "config/modbustcp-endpoints_demonstrator.xml",
        "xsd_schema": "config/modbustcp-endpoints.xsd",
    },
    "shared_memory": {"name": "modbus_shm", "size": 1024 * 12},
    "semaphore": {"name": "modbus_semaphore"},
}


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


def _resolve_paths(raw: Dict[str, Any], base_dir: Path) -> Dict[str, Any]:
    """Resolve relative file paths inside service configs against base_dir."""
    raw = dict(raw)
    for svc_key in ("opcua", "modbustcp"):
        svc = raw.get(svc_key)
        if not isinstance(svc, dict):
            continue
        files = svc.get("files", {})
        for key in ("xml_config", "xsd_schema"):
            if key in files:
                p = Path(files[key])
                files[key] = str(p if p.is_absolute() else base_dir / p)
    return raw


def _apply_env_overrides(config: CPCConfig) -> CPCConfig:
    """
    Optional environment-variable overrides.

    OPC UA  : OPCUA_INTERVAL, OPCUA_SHM_NAME, OPCUA_SHM_SIZE, OPCUA_SEMAPHORE_NAME
    Modbus  : MODBUSTCP_INTERVAL, MODBUSTCP_SHM_NAME, MODBUSTCP_SHM_SIZE, MODBUSTCP_SEMAPHORE_NAME
    Flask   : FLASK_HOST, FLASK_PORT, FLASK_DEBUG
    Logging : LOG_LEVEL, LOG_FILE
    """
    env = os.environ

    def _patch_service(svc: ServiceConfig, prefix: str) -> ServiceConfig:
        data = svc.model_dump()
        if v := env.get(f"{prefix}_INTERVAL"):
            data["interval"] = int(v)
        if v := env.get(f"{prefix}_SHM_NAME"):
            data["shared_memory"]["name"] = v
        if v := env.get(f"{prefix}_SHM_SIZE"):
            data["shared_memory"]["size"] = int(v)
        if v := env.get(f"{prefix}_SEMAPHORE_NAME"):
            data["semaphore"]["name"] = v
        return ServiceConfig.model_validate(data)

    flask_data = config.flask_bridge.model_dump()
    if v := env.get("FLASK_HOST"):
        flask_data["host"] = v
    if v := env.get("FLASK_PORT"):
        flask_data["port"] = int(v)
    if v := env.get("FLASK_DEBUG"):
        flask_data["debug"] = v.lower() in ("1", "true", "yes")

    log_data = config.logging.model_dump()
    if v := env.get("LOG_LEVEL"):
        log_data["log_level"] = v.upper()
    if v := env.get("LOG_FILE"):
        log_data["log_file"] = v

    return CPCConfig(
        opcua=_patch_service(config.opcua, "OPCUA"),
        modbustcp=_patch_service(config.modbustcp, "MODBUSTCP"),
        flask_bridge=FlaskBridgeConfig.model_validate(flask_data),
        grpc_certs=config.grpc_certs,
        logging=LoggingConfig.model_validate(log_data),
    )


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------

def load_config(
    path: str | Path = Path(__file__).parent / "config/settings.yaml",
    base_dir: Path | None = None,
    allow_env: bool = True,
) -> CPCConfig:
    """
    Load, validate, and return the CPC partition configuration.

    Args:
        path:      Path to a YAML or JSON settings file.
        base_dir:  Base directory for resolving relative file paths.
                   Defaults to the directory containing *path*.
        allow_env: If True, environment variables override file values.

    Returns:
        A fully validated CPCConfig instance.
    """
    cfg_path = Path(path)
    base_dir = base_dir or cfg_path.parent

    raw = _read_raw(cfg_path)

    # Merge user values on top of defaults
    raw["opcua"] = {**_OPCUA_DEFAULTS, **raw.get("opcua", {})}
    raw["modbustcp"] = {**_MODBUSTCP_DEFAULTS, **raw.get("modbustcp", {})}
    raw.setdefault("flask_bridge", {})
    raw.setdefault("grpc_certs", {})
    raw.setdefault("logging", {})

    raw = _resolve_paths(raw, base_dir)
    config = CPCConfig.model_validate(raw)

    return _apply_env_overrides(config) if allow_env else config