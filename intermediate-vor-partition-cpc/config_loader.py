"""
------------------------------------------------------------
 Config:   intermediate-vor-partition-cpc/config_loader.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    Pydantic configuration model for the Intermediate VoR-CPC
    partition. Covers acceptance ruleset paths, the inbound
    mapped-request gRPC server (mTLS) that receives mapped
    requests from intermediate-vor-partition, the local-only
    SQLite database those requests are stored in, the Flask
    bridge HTTP client, and logging.

 Usage:
    from config_loader import load_config, VoRCPCConfig

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
# Acceptance ruleset files
# ---------------------------------------------------------------------------

class AcceptanceRulesetConfig(BaseModel):
    """XML acceptance rulesets consumed during acceptance and mapping verification."""
    ruleset: Path = Field(
        Path("config/Acceptance_Ruleset.xml"),
        description="Path to the primary acceptance ruleset XML",
    )
    ruleset_modified: Path = Field(
        Path("config/Acceptance_Ruleset_modified.xml"),
        description="Path where the modified ruleset (with injected endpoints) is written",
    )


# ---------------------------------------------------------------------------
# Inbound gRPC server (intermediate-vor-partition -> this partition)
# ---------------------------------------------------------------------------

class MappedRequestServerCerts(BaseModel):
    """mTLS certificate paths for the inbound mapped-request gRPC server."""
    ca_cert: Path = Field(
        Path("certificates/grpc/mapped_request_ca/ca.crt"),
        description="CA certificate used to verify intermediate-vor-partition's client cert",
    )
    server_cert: Path = Field(
        Path("certificates/grpc/mapped_request_server/server.crt"),
        description="Server certificate for mTLS",
    )
    server_key: Path = Field(
        Path("certificates/grpc/mapped_request_server/server.key"),
        description="Server private key for mTLS",
    )


class MappedRequestServerConfig(BaseModel):
    """
    gRPC server that receives mapped requests forwarded directly by
    intermediate-vor-partition. Replaces the previous shared-database read
    (MariaDB, then a shared SQLite file): intermediate-vor-partition no
    longer touches any database and only ever talks to this server.
    """
    port: int = Field(50052, description="Port the mapped-request gRPC server listens on")
    max_workers: int = Field(10, description="Thread pool size for the gRPC server")
    grace_period_seconds: int = Field(5, description="Seconds to wait during graceful shutdown")
    certs: MappedRequestServerCerts = Field(default_factory=MappedRequestServerCerts)


# ---------------------------------------------------------------------------
# SQLite (local-only)
# ---------------------------------------------------------------------------

class SQLiteConfig(BaseModel):
    """
    SQLite connection parameters for the VoR-CPC partition.

    This database is local and private to this partition: no other
    process or container ever opens it, and there is no dedicated Docker
    volume for it. Mapped requests arrive over gRPC (see
    MappedRequestServerConfig above) and are stored here as a plain file
    on disk, relative to the application directory (the same "python code
    + data file side by side" layout this runs with directly on a Linux
    VM). The existing pull/process loop in main.py reads and deletes them.
    """
    database: str = Field(
        "data/mapped_requests.db",
        description="Path to the local-only SQLite database file, relative to the app directory",
    )
    busy_timeout_ms: int = Field(
        10000,
        description="Milliseconds to wait for a lock held by another thread in this process before raising an error",
    )


# ---------------------------------------------------------------------------
# Flask bridge HTTP client (temporary)
# ---------------------------------------------------------------------------

class FlaskBridgeClientConfig(BaseModel):
    """
    HTTP client settings for the temporary Flask server bridge on the CPC side.
    Will be replaced by a gRPC/mTLS channel in a future iteration.
    """
    host: str = Field("192.168.156.14", description="IP address of the Flask bridge server")
    port: int = Field(5000, description="Port of the Flask bridge server")
    read_values_path: str = Field("/read_values_xml", description="Endpoint path for reading current values")
    update_endpoints_path: str = Field("/update_endpoints", description="Endpoint path for writing updated values")
    timeout_seconds: float = Field(5.0, description="HTTP request timeout in seconds")

    @property
    def read_values_url(self) -> str:
        return f"http://{self.host}:{self.port}{self.read_values_path}"

    @property
    def update_endpoints_url(self) -> str:
        return f"http://{self.host}:{self.port}{self.update_endpoints_path}"


# ---------------------------------------------------------------------------
# Processing loop
# ---------------------------------------------------------------------------

class ProcessingConfig(BaseModel):
    """Tuning parameters for the request-pull-and-process loop."""
    idle_sleep_seconds: float = Field(
        0.5,
        description="Sleep duration when no requests are in the database (avoids busy-wait)",
    )
    startup_delay_seconds: float = Field(
        2.0,
        description="Initial sleep before the processing loop starts",
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

class VoRCPCConfig(BaseModel):
    """Root configuration for the Intermediate VoR-CPC partition."""
    acceptance_rulesets:  AcceptanceRulesetConfig  = Field(default_factory=AcceptanceRulesetConfig)
    mapped_request_server: MappedRequestServerConfig = Field(default_factory=MappedRequestServerConfig)
    sqlite:               SQLiteConfig              = Field(default_factory=SQLiteConfig)
    flask_bridge:         FlaskBridgeClientConfig   = Field(default_factory=FlaskBridgeClientConfig)
    processing:           ProcessingConfig          = Field(default_factory=ProcessingConfig)
    logging:              LoggingConfig             = Field(default_factory=LoggingConfig)


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
    """Resolve relative ruleset, mapped_request_server.certs, and sqlite.database paths against base_dir."""
    rulesets = raw.get("acceptance_rulesets", {})
    for field in ("ruleset", "ruleset_modified"):
        if field in rulesets:
            p = Path(rulesets[field])
            rulesets[field] = str(p if p.is_absolute() else base_dir / p)

    server_certs = raw.get("mapped_request_server", {}).get("certs", {})
    for field in ("ca_cert", "server_cert", "server_key"):
        if field in server_certs:
            p = Path(server_certs[field])
            server_certs[field] = str(p if p.is_absolute() else base_dir / p)

    sqlite_data = raw.get("sqlite", {})
    if "database" in sqlite_data:
        p = Path(sqlite_data["database"])
        sqlite_data["database"] = str(p if p.is_absolute() else base_dir / p)

    return raw


def _apply_env_overrides(config: VoRCPCConfig) -> VoRCPCConfig:
    """
    Optional environment-variable overrides.

    Rulesets              : ACCEPTANCE_RULESET_PATH, ACCEPTANCE_RULESET_MODIFIED_PATH
    Mapped-request server : MAPPED_REQUEST_SERVER_PORT, MAPPED_REQUEST_SERVER_MAX_WORKERS
    SQLite (local-only)   : DB_PATH, DB_BUSY_TIMEOUT_MS
    Flask bridge          : FLASK_HOST, FLASK_PORT, FLASK_TIMEOUT
    Logging               : LOG_LEVEL, LOG_FILE
    """
    env = os.environ

    ruleset_data = config.acceptance_rulesets.model_dump()
    if v := env.get("ACCEPTANCE_RULESET_PATH"):
        ruleset_data["ruleset"] = v
    if v := env.get("ACCEPTANCE_RULESET_MODIFIED_PATH"):
        ruleset_data["ruleset_modified"] = v

    server_data = config.mapped_request_server.model_dump()
    if v := env.get("MAPPED_REQUEST_SERVER_PORT"):
        server_data["port"] = int(v)
    if v := env.get("MAPPED_REQUEST_SERVER_MAX_WORKERS"):
        server_data["max_workers"] = int(v)

    db_data = config.sqlite.model_dump()
    if v := env.get("DB_PATH"):
        db_data["database"] = v
    if v := env.get("DB_BUSY_TIMEOUT_MS"):
        db_data["busy_timeout_ms"] = int(v)

    flask_data = config.flask_bridge.model_dump()
    if v := env.get("FLASK_HOST"):
        flask_data["host"] = v
    if v := env.get("FLASK_PORT"):
        flask_data["port"] = int(v)
    if v := env.get("FLASK_TIMEOUT"):
        flask_data["timeout_seconds"] = float(v)

    log_data = config.logging.model_dump()
    if v := env.get("LOG_LEVEL"):
        log_data["log_level"] = v.upper()
    if v := env.get("LOG_FILE"):
        log_data["log_file"] = v

    return VoRCPCConfig(
        acceptance_rulesets=AcceptanceRulesetConfig.model_validate(ruleset_data),
        mapped_request_server=MappedRequestServerConfig.model_validate(server_data),
        sqlite=SQLiteConfig.model_validate(db_data),
        flask_bridge=FlaskBridgeClientConfig.model_validate(flask_data),
        processing=config.processing,
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
) -> VoRCPCConfig:
    """
    Load, validate, and return the Intermediate VoR-CPC partition configuration.

    Args:
        path:      Path to a YAML or JSON settings file.
        base_dir:  Base directory for resolving relative paths.
                   Defaults to the directory containing *path*.
        allow_env: If True, environment variables override file values.

    Returns:
        A fully validated VoRCPCConfig instance.
    """
    cfg_path = Path(path)
    base_dir = base_dir or cfg_path.parent

    raw = _read_raw(cfg_path) if cfg_path.exists() else {}
    raw.setdefault("acceptance_rulesets", {})
    raw.setdefault("mapped_request_server", {})
    raw.setdefault("sqlite", {})
    raw.setdefault("flask_bridge", {})
    raw.setdefault("processing", {})
    raw.setdefault("logging", {})

    raw = _resolve_paths(raw, base_dir)
    config = VoRCPCConfig.model_validate(raw)

    return _apply_env_overrides(config) if allow_env else config
