# config_loader.py
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict
import json
import os

try:
    import yaml 
except ImportError:
    yaml = None

from pydantic import BaseModel, Field, PositiveInt

# ---------- Shared schema pieces ----------

class EndpointFiles(BaseModel):
    xml_config: Path = Field(..., description="Path to endpoints XML file")
    xsd_schema: Path = Field(..., description="Path to XSD schema")

class SharedMemory(BaseModel):
    name: str
    size: PositiveInt

class Semaphore(BaseModel):
    name: str

class ServiceConfig(BaseModel):
    interval: PositiveInt = Field(..., description="Polling interval in seconds")
    files: EndpointFiles
    shared_memory: SharedMemory
    semaphore: Semaphore

# ---------- App-level schema ----------

class AppConfig(BaseModel):
    opcua: ServiceConfig
    modbustcp: ServiceConfig

# ---------- IO helpers ----------

def _read_raw_config(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    ext = path.suffix.lower()
    if ext in (".yaml", ".yml"):
        if yaml is None:
            raise RuntimeError("pyyaml not installed, cannot load YAML.")
        return yaml.safe_load(text) or {}
    if ext == ".json":
        return json.loads(text)
    raise ValueError(f"Unsupported config extension: {ext}")

def _resolve_service_paths(service_dict: Dict[str, Any], base_dir: Path) -> None:
    """
    Mutates service_dict: resolves files.xml_config and files.xsd_schema relative to base_dir.
    """
    files = service_dict.get("files", {})
    for key in ("xml_config", "xsd_schema"):
        if key in files:
            p = Path(files[key])
            files[key] = str(p if p.is_absolute() else (base_dir / p))

def _resolve_paths(raw: Dict[str, Any], base_dir: Path) -> Dict[str, Any]:
    data = dict(raw)  # shallow copy
    for svc_key in ("opcua", "modbustcp"):
        if svc_key in data and isinstance(data[svc_key], dict):
            _resolve_service_paths(data[svc_key], base_dir)
    return data

def _apply_env_overrides(conf: AppConfig) -> AppConfig:
    """
    Optional env overrides.
    OPC UA  vars: OPCUA_INTERVAL, OPCUA_SHM_NAME, OPCUA_SHM_SIZE, OPCUA_SEMAPHORE_NAME
    Modbus vars: MODBUSTCP_INTERVAL, MODBUSTCP_SHM_NAME, MODBUSTCP_SHM_SIZE, MODBUSTCP_SEMAPHORE_NAME
    """
    env = os.environ
    # deep copies
    opcua = conf.opcua.copy(deep=True) # TODO: pydantic v2: .model_copy()
    modbustcp = conf.modbustcp.copy(deep=True)

    # Helper
    def apply(service, prefix: str):
        iv = env.get(f"{prefix}_INTERVAL")
        shm_n = env.get(f"{prefix}_SHM_NAME")
        shm_s = env.get(f"{prefix}_SHM_SIZE")
        sem_n = env.get(f"{prefix}_SEMAPHORE_NAME")
        if iv:    service.interval = int(iv)
        if shm_n: service.shared_memory.name = shm_n
        if shm_s: service.shared_memory.size = int(shm_s)
        if sem_n: service.semaphore.name = sem_n

    apply(opcua, "OPCUA")
    apply(modbustcp, "MODBUSTCP")

    return AppConfig(opcua=opcua, modbustcp=modbustcp)

def load_config(path: str | Path, base_dir: Path | None = None, allow_env=True) -> AppConfig:
    """
    Load YAML/JSON, resolve relative paths, validate, and apply optional env overrides.
    Also verifies that referenced files exist (fail-fast).
    """
    cfg_path = Path(path)
    base_dir = base_dir or cfg_path.parent

    raw = _read_raw_config(cfg_path)

    # Set sane defaults if user omits sections.
    raw.setdefault("opcua", {})
    raw.setdefault("modbustcp", {})

    # Fill defaults only if missing.
    raw["opcua"] = {
        "interval": 1,
        "files": {
            "xml_config": "config/opcua-endpoints_factory_and_docker.xml",
            "xsd_schema":  "config/opcua-endpoints.xsd",
        },
        "shared_memory": {"name": "opcua_shm", "size": 1024 * 10},
        "semaphore": {"name": "opcua_semaphore"},
        **raw["opcua"],
    }
    raw["modbustcp"] = {
        "interval": 1,
        "files": {
            "xml_config": "config/modbustcp-endpoints_ecotec.xml",
            "xsd_schema":  "config/modbustcp-endpoints.xsd",
        },
        "shared_memory": {"name": "modbus_shm", "size": 1024 * 12},
        "semaphore": {"name": "modbus_semaphore"},
        **raw["modbustcp"],
    }

    # Resolve relative paths
    raw = _resolve_paths(raw, base_dir)

    # Validate
    conf = AppConfig.model_validate(raw) if hasattr(AppConfig, "model_validate") else AppConfig.parse_obj(raw) # TODO: pydantic v2 

    # Ensure files exist (comment out if you prefer lazy checks)
    conf.opcua.files.xml_config.resolve(strict=True)
    conf.opcua.files.xsd_schema.resolve(strict=True)
    conf.modbustcp.files.xml_config.resolve(strict=True)
    conf.modbustcp.files.xsd_schema.resolve(strict=True)

    return _apply_env_overrides(conf) if allow_env else conf
