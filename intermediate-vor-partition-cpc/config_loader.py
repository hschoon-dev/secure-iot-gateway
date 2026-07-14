"""
------------------------------------------------------------
 Config:   intermediate-vor-partition-cpc/config_loader.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    Pydantic configuration model for the Intermediate VoR-CPC
    partition. Covers acceptance ruleset paths, the MariaDB
    database connection, legacy bridge compatibility, and logging.

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
    ruleset_with_affected_endpoints: Path = Field(
        Path("config/Acceptance_Ruleset_with_affected_endpoints.xml"),
        description="Path for the ruleset fixture containing affected endpoints",
    )


# ---------------------------------------------------------------------------
# MariaDB connection
# ---------------------------------------------------------------------------

class MariaDBConfig(BaseModel):
    """MariaDB connection parameters for the VoR-CPC partition."""
    host:      str = Field("192.168.178.117",    description="MariaDB host address")
    port:      int = Field(3306,                 description="MariaDB port")
    user:      str = Field("vor-2",              description="Database user")
    password:  str = Field("VoR-2-Password",     description="Database password")
    database:  str = Field("secure_iot_gateway", description="Database name")
    pool_name: str = Field("iot_gateway_pool",   description="Connection pool name")
    pool_size: int = Field(5,                    description="Connection pool size")


# ---------------------------------------------------------------------------
# Flask bridge HTTP client (explicit legacy compatibility only)
# ---------------------------------------------------------------------------

class FlaskBridgeClientConfig(BaseModel):
    """
    Legacy HTTP bridge settings retained for explicit compatibility mode.

    The standard synchronous and MariaDB-backed deployment paths use the
    typed gRPC/mTLS CPC service and do not consume these values.
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
    acceptance_rulesets: AcceptanceRulesetConfig = Field(default_factory=AcceptanceRulesetConfig)
    mariadb:             MariaDBConfig            = Field(default_factory=MariaDBConfig)
    flask_bridge:        FlaskBridgeClientConfig  = Field(default_factory=FlaskBridgeClientConfig)
    processing:          ProcessingConfig         = Field(default_factory=ProcessingConfig)
    logging:             LoggingConfig            = Field(default_factory=LoggingConfig)


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
    """Resolve relative ruleset file paths against base_dir."""
    rulesets = raw.get("acceptance_rulesets", {})
    for field in ("ruleset", "ruleset_with_affected_endpoints"):
        if field in rulesets:
            p = Path(rulesets[field])
            rulesets[field] = str(p if p.is_absolute() else base_dir / p)
    return raw


def _apply_env_overrides(config: VoRCPCConfig) -> VoRCPCConfig:
    """
    Optional environment-variable overrides.

    Rulesets     : ACCEPTANCE_RULESET_PATH, ACCEPTANCE_RULESET_MODIFIED_PATH
    MariaDB      : DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, DB_POOL_SIZE
    Flask bridge : FLASK_HOST, FLASK_PORT, FLASK_TIMEOUT
    Logging      : LOG_LEVEL, LOG_FILE
    """
    env = os.environ

    ruleset_data = config.acceptance_rulesets.model_dump()
    if v := env.get("ACCEPTANCE_RULESET_PATH"):
        ruleset_data["ruleset"] = v
    if v := env.get("ACCEPTANCE_RULESET_MODIFIED_PATH"):
        ruleset_data["ruleset_with_affected_endpoints"] = v

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
        mariadb=MariaDBConfig.model_validate(db_data),
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
    raw.setdefault("mariadb", {})
    raw.setdefault("flask_bridge", {})
    raw.setdefault("processing", {})
    raw.setdefault("logging", {})

    raw = _resolve_paths(raw, base_dir)
    config = VoRCPCConfig.model_validate(raw)

    return _apply_env_overrides(config) if allow_env else config
