"""
------------------------------------------------------------
 Config:   intermediate-vor-partition/config_loader.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    Pydantic configuration model for the Intermediate VoR
    partition. Covers ruleset file paths, the inbound gRPC
    server (mTLS) that receives requests from the Interface
    partition, the outbound gRPC client (mTLS) that forwards
    mapped requests to intermediate-vor-partition-cpc, and
    logging.

 Usage:
    from config_loader import load_config, VoRConfig

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
# Ruleset file paths
# ---------------------------------------------------------------------------

class RulesetConfig(BaseModel):
    """XML rulesets consumed by the verification and mapping steps."""
    verification_ruleset: Path = Field(
        Path("config/Request_Verification_Ruleset.xml"),
        description="Path to the request verification ruleset XML",
    )
    mapping_ruleset: Path = Field(
        Path("config/Mapping_Rulesets.xml"),
        description="Path to the mapping ruleset XML",
    )


# ---------------------------------------------------------------------------
# Inbound gRPC server (Interface partition -> this partition)
# ---------------------------------------------------------------------------

class GrpcServerCerts(BaseModel):
    """mTLS certificate paths for the inbound gRPC request server."""
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
    """gRPC server that receives VoR requests from the Interface partition."""
    port: int = Field(50051, description="Port the gRPC server listens on")
    max_workers: int = Field(10, description="Thread pool size for the gRPC server")
    grace_period_seconds: int = Field(5, description="Seconds to wait during graceful shutdown")
    certs: GrpcServerCerts = Field(default_factory=GrpcServerCerts)


# ---------------------------------------------------------------------------
# Outbound gRPC client (this partition -> intermediate-vor-partition-cpc)
# ---------------------------------------------------------------------------

class GrpcClientCerts(BaseModel):
    """mTLS certificate paths for the outbound mapped-request gRPC client."""
    ca_cert: Path = Field(
        Path("certificates/grpc/mapped_request_ca/ca.crt"),
        description="CA certificate used to verify the CPC partition's server cert",
    )
    client_cert: Path = Field(
        Path("certificates/grpc/mapped_request_client/client.crt"),
        description="Client certificate for mTLS",
    )
    client_key: Path = Field(
        Path("certificates/grpc/mapped_request_client/client.key"),
        description="Client private key for mTLS",
    )


class MappedRequestClientConfig(BaseModel):
    """
    gRPC client used to forward mapped requests directly to
    intermediate-vor-partition-cpc, replacing the previous shared-database
    write (MariaDB, then a shared SQLite file). This partition no longer
    stores anything itself; intermediate-vor-partition-cpc owns storage
    (its own local-only SQLite database) and is reached only via this stub.
    """
    host: str = Field(
        "192.168.178.116",
        description="Hostname/IP of intermediate-vor-partition-cpc's mapped-request gRPC server",
    )
    port: int = Field(50052, description="Port of the mapped-request gRPC server")
    timeout_seconds: float = Field(5.0, description="RPC timeout in seconds")
    certs: GrpcClientCerts = Field(default_factory=GrpcClientCerts)


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

class VoRConfig(BaseModel):
    """Root configuration for the Intermediate VoR partition."""
    rulesets:              RulesetConfig             = Field(default_factory=RulesetConfig)
    grpc_server:           GrpcServerConfig           = Field(default_factory=GrpcServerConfig)
    mapped_request_client: MappedRequestClientConfig  = Field(default_factory=MappedRequestClientConfig)
    logging:               LoggingConfig              = Field(default_factory=LoggingConfig)


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
    """Resolve relative paths in rulesets, grpc_server.certs, and
    mapped_request_client.certs."""
    rulesets = raw.get("rulesets", {})
    for field in ("verification_ruleset", "mapping_ruleset"):
        if field in rulesets:
            p = Path(rulesets[field])
            rulesets[field] = str(p if p.is_absolute() else base_dir / p)

    server_certs = raw.get("grpc_server", {}).get("certs", {})
    for field in ("ca_cert", "server_cert", "server_key"):
        if field in server_certs:
            p = Path(server_certs[field])
            server_certs[field] = str(p if p.is_absolute() else base_dir / p)

    client_certs = raw.get("mapped_request_client", {}).get("certs", {})
    for field in ("ca_cert", "client_cert", "client_key"):
        if field in client_certs:
            p = Path(client_certs[field])
            client_certs[field] = str(p if p.is_absolute() else base_dir / p)

    return raw


def _apply_env_overrides(config: VoRConfig) -> VoRConfig:
    """
    Optional environment-variable overrides.

    Rulesets       : VERIFICATION_RULESET_PATH, MAPPING_RULESET_PATH
    gRPC (inbound) : GRPC_PORT, GRPC_MAX_WORKERS
    Mapped-request client (outbound) : MAPPED_REQUEST_HOST, MAPPED_REQUEST_PORT,
                                        MAPPED_REQUEST_TIMEOUT
    Logging        : LOG_LEVEL, LOG_FILE
    """
    env = os.environ

    ruleset_data = config.rulesets.model_dump()
    if v := env.get("VERIFICATION_RULESET_PATH"):
        ruleset_data["verification_ruleset"] = v
    if v := env.get("MAPPING_RULESET_PATH"):
        ruleset_data["mapping_ruleset"] = v

    grpc_data = config.grpc_server.model_dump()
    if v := env.get("GRPC_PORT"):
        grpc_data["port"] = int(v)
    if v := env.get("GRPC_MAX_WORKERS"):
        grpc_data["max_workers"] = int(v)

    client_data = config.mapped_request_client.model_dump()
    if v := env.get("MAPPED_REQUEST_HOST"):
        client_data["host"] = v
    if v := env.get("MAPPED_REQUEST_PORT"):
        client_data["port"] = int(v)
    if v := env.get("MAPPED_REQUEST_TIMEOUT"):
        client_data["timeout_seconds"] = float(v)

    log_data = config.logging.model_dump()
    if v := env.get("LOG_LEVEL"):
        log_data["log_level"] = v.upper()
    if v := env.get("LOG_FILE"):
        log_data["log_file"] = v

    return VoRConfig(
        rulesets=RulesetConfig.model_validate(ruleset_data),
        grpc_server=GrpcServerConfig.model_validate(grpc_data),
        mapped_request_client=MappedRequestClientConfig.model_validate(client_data),
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
) -> VoRConfig:
    """
    Load, validate, and return the Intermediate VoR partition configuration.

    Args:
        path:      Path to a YAML or JSON settings file.
        base_dir:  Base directory for resolving relative paths.
                   Defaults to the directory containing *path*.
        allow_env: If True, environment variables override file values.

    Returns:
        A fully validated VoRConfig instance.
    """
    cfg_path = Path(path)
    base_dir = base_dir or cfg_path.parent

    raw = _read_raw(cfg_path) if cfg_path.exists() else {}
    raw.setdefault("rulesets", {})
    raw.setdefault("grpc_server", {})
    raw.setdefault("mapped_request_client", {})
    raw.setdefault("logging", {})

    raw = _resolve_paths(raw, base_dir)
    config = VoRConfig.model_validate(raw)

    return _apply_env_overrides(config) if allow_env else config
