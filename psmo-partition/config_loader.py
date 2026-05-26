"""
------------------------------------------------------------
 Config:   psmo-partition/psmo_config.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    Pydantic configuration model for the plant-specific M+O
    (psM+O) partition. Covers the inbound gRPC JSON handler
    (mTLS), in-process queue sizes, startup timing, and
    logging.

 Usage:
    from psmo_config import load_config, PSMOConfig

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
# gRPC JSON handler (receives data pushed by the Interface partition)
# ---------------------------------------------------------------------------

class GrpcServerCerts(BaseModel):
    """mTLS certificate paths for the gRPC JSON receiver."""
    ca_cert: Path = Field(
        Path("certs/ca/ca.crt"),
        description="CA certificate used to verify connecting client certs",
    )
    server_cert: Path = Field(
        Path("certs/server/server.crt"),
        description="Server certificate presented during the TLS handshake",
    )
    server_key: Path = Field(
        Path("certs/server/server.key"),
        description="Private key for the server certificate",
    )


class GrpcServerConfig(BaseModel):
    """gRPC server that receives JSON payloads from the Interface partition."""
    port: int = Field(50051, description="Port the gRPC server listens on")
    max_workers: int = Field(4, description="Thread pool size for the gRPC server")
    certs: GrpcServerCerts = Field(default_factory=GrpcServerCerts)


# ---------------------------------------------------------------------------
# In-process queue sizes
# ---------------------------------------------------------------------------

class QueueConfig(BaseModel):
    """Bounded queue sizes between the gRPC handler thread and main loop."""
    opcua_maxsize: int = Field(2, description="Max items in the OPC UA data queue")
    modbustcp_maxsize: int = Field(2, description="Max items in the ModbusTCP data queue")


# ---------------------------------------------------------------------------
# Startup / lifecycle
# ---------------------------------------------------------------------------

class LifecycleConfig(BaseModel):
    """Startup and lifecycle timing parameters."""
    startup_delay_seconds: float = Field(
        7.0,
        description="Seconds to wait after process start before entering the main loop",
    )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class LoggingConfig(BaseModel):
    """Rotating-file + console logging configuration."""
    log_file: Path = Field(Path("logs/app.log"), description="Path to the log file")
    log_level: str = Field("INFO", description="Logging level (DEBUG/INFO/WARNING/ERROR)")
    max_bytes: PositiveInt = Field(1 * 1024 * 1024, description="Max log file size in bytes before rotation")
    backup_count: PositiveInt = Field(3, description="Number of rotated backup files to keep")


# ---------------------------------------------------------------------------
# Top-level model
# ---------------------------------------------------------------------------

class PSMOConfig(BaseModel):
    """Root configuration for the psM+O (plant-specific M+O) partition."""
    grpc_server: GrpcServerConfig = Field(default_factory=GrpcServerConfig)
    queues: QueueConfig = Field(default_factory=QueueConfig)
    lifecycle: LifecycleConfig = Field(default_factory=LifecycleConfig)
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
    """Resolve relative cert paths in grpc_server.certs against base_dir."""
    certs = raw.get("grpc_server", {}).get("certs", {})
    for field in ("ca_cert", "server_cert", "server_key"):
        if field in certs:
            p = Path(certs[field])
            certs[field] = str(p if p.is_absolute() else base_dir / p)
    return raw


def _apply_env_overrides(config: PSMOConfig) -> PSMOConfig:
    """
    Optional environment-variable overrides.

    gRPC    : GRPC_PORT, GRPC_MAX_WORKERS
    Queues  : OPCUA_QUEUE_SIZE, MODBUSTCP_QUEUE_SIZE
    Logging : LOG_LEVEL, LOG_FILE
    """
    env = os.environ

    grpc_data = config.grpc_server.model_dump()
    if v := env.get("GRPC_PORT"):
        grpc_data["port"] = int(v)
    if v := env.get("GRPC_MAX_WORKERS"):
        grpc_data["max_workers"] = int(v)

    queue_data = config.queues.model_dump()
    if v := env.get("OPCUA_QUEUE_SIZE"):
        queue_data["opcua_maxsize"] = int(v)
    if v := env.get("MODBUSTCP_QUEUE_SIZE"):
        queue_data["modbustcp_maxsize"] = int(v)

    log_data = config.logging.model_dump()
    if v := env.get("LOG_LEVEL"):
        log_data["log_level"] = v.upper()
    if v := env.get("LOG_FILE"):
        log_data["log_file"] = v

    return PSMOConfig(
        grpc_server=GrpcServerConfig.model_validate(grpc_data),
        queues=QueueConfig.model_validate(queue_data),
        lifecycle=config.lifecycle,
        logging=LoggingConfig.model_validate(log_data),
    )


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------

_DEFAULT_SETTINGS = Path(__file__).parent / "config/settings.yaml"


def load_config(
    path: str | Path = _DEFAULT_SETTINGS,
    base_dir: Path | None = None,
    allow_env: bool = True,
) -> PSMOConfig:
    """
    Load, validate, and return the psM+O partition configuration.

    Args:
        path:      Path to a YAML or JSON settings file.
        base_dir:  Base directory for resolving relative certificate paths.
                   Defaults to the directory containing *path*.
        allow_env: If True, environment variables override file values.

    Returns:
        A fully validated PSMOConfig instance.
    """
    cfg_path = Path(path)
    base_dir = base_dir or cfg_path.parent

    raw = _read_raw(cfg_path) if cfg_path.exists() else {}
    raw.setdefault("grpc_server", {})
    raw.setdefault("queues", {})
    raw.setdefault("lifecycle", {})
    raw.setdefault("logging", {})

    raw = _resolve_cert_paths(raw, base_dir)
    config = PSMOConfig.model_validate(raw)

    return _apply_env_overrides(config) if allow_env else config