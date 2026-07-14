"""
------------------------------------------------------------
 Config:   intermediate-vor-partition/config_loader.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    Pydantic configuration model for the Intermediate VoR
    partition. Covers ruleset file paths, the MariaDB
    database connection, the inbound gRPC server (mTLS), and
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
# MariaDB connection
# ---------------------------------------------------------------------------

class MariaDBConfig(BaseModel):
    """MariaDB connection parameters for the VoR partition."""
    host:      str = Field("192.168.178.117",    description="MariaDB host address")
    port:      int = Field(3306,                 description="MariaDB port")
    user:      str = Field("vor-1",              description="Database user")
    password:  str = Field("VoR-1-Password",     description="Database password")
    database:  str = Field("secure_iot_gateway", description="Database name")
    pool_name: str = Field("iot_gateway_pool",   description="Connection pool name")
    pool_size: int = Field(5,                    description="Connection pool size")


# ---------------------------------------------------------------------------
# Inbound gRPC server
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
    rulesets:   RulesetConfig   = Field(default_factory=RulesetConfig)
    mariadb:    MariaDBConfig   = Field(default_factory=MariaDBConfig)
    grpc_server: GrpcServerConfig = Field(default_factory=GrpcServerConfig)
    logging:    LoggingConfig   = Field(default_factory=LoggingConfig)


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
    """Resolve relative paths in rulesets and grpc_server.certs."""
    rulesets = raw.get("rulesets", {})
    for field in ("verification_ruleset", "mapping_ruleset"):
        if field in rulesets:
            p = Path(rulesets[field])
            rulesets[field] = str(p if p.is_absolute() else base_dir / p)

    certs = raw.get("grpc_server", {}).get("certs", {})
    for field in ("ca_cert", "server_cert", "server_key"):
        if field in certs:
            p = Path(certs[field])
            certs[field] = str(p if p.is_absolute() else base_dir / p)

    return raw


def _apply_env_overrides(config: VoRConfig) -> VoRConfig:
    """
    Optional environment-variable overrides.

    Rulesets : VERIFICATION_RULESET_PATH, MAPPING_RULESET_PATH
    MariaDB  : DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, DB_POOL_SIZE
    gRPC     : GRPC_PORT, GRPC_MAX_WORKERS
    Logging  : LOG_LEVEL, LOG_FILE
    """
    env = os.environ

    ruleset_data = config.rulesets.model_dump()
    if v := env.get("VERIFICATION_RULESET_PATH"):
        ruleset_data["verification_ruleset"] = v
    if v := env.get("MAPPING_RULESET_PATH"):
        ruleset_data["mapping_ruleset"] = v

    db_data = config.mariadb.model_dump()
    if v := env.get("DB_HOST"):
        db_data["host"] = v
    if v := env.get("DB_PORT"):
        db_data["port"] = int(v)
    if v := env.get("DB_USER"):
        db_data["user"] = v
    if v := env.get("DB_PASSWORD"):
        db_data["password"] = v
    if v := env.get("DB_NAME"):
        db_data["database"] = v
    if v := env.get("DB_POOL_SIZE"):
        db_data["pool_size"] = int(v)

    grpc_data = config.grpc_server.model_dump()
    if v := env.get("GRPC_PORT"):
        grpc_data["port"] = int(v)
    if v := env.get("GRPC_MAX_WORKERS"):
        grpc_data["max_workers"] = int(v)
    if v := env.get("INTERMEDIATE_VOR_GRPC_CERT_BASE"):
        cert_base = Path(v)
        grpc_data["certs"] = {
            "ca_cert": cert_base / "ca" / "ca.crt",
            "server_cert": cert_base / "server" / "server.crt",
            "server_key": cert_base / "server" / "server.key",
        }

    log_data = config.logging.model_dump()
    if v := env.get("LOG_LEVEL"):
        log_data["log_level"] = v.upper()
    if v := env.get("LOG_FILE"):
        log_data["log_file"] = v

    return VoRConfig(
        rulesets=RulesetConfig.model_validate(ruleset_data),
        mariadb=MariaDBConfig.model_validate(db_data),
        grpc_server=GrpcServerConfig.model_validate(grpc_data),
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
    raw.setdefault("mariadb", {})
    raw.setdefault("grpc_server", {})
    raw.setdefault("logging", {})

    raw = _resolve_paths(raw, base_dir)
    config = VoRConfig.model_validate(raw)

    return _apply_env_overrides(config) if allow_env else config
