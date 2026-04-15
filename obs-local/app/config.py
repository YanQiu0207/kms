from __future__ import annotations

from pathlib import Path
import os
from typing import Any

import yaml

from .schemas import AppConfig, ServerConfig

DEFAULT_CONFIG_PATH = Path("config.yaml")
PROJECT_ROOT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
CONFIG_ENV_VAR = "OBS_LOCAL_CONFIG_PATH"
LEGACY_CONFIG_ENV_VAR = "OBS_LOCAL_CONFIG"
SERVER_HOST_ENV_VAR = "OBS_LOCAL_HOST"
SERVER_PORT_ENV_VAR = "OBS_LOCAL_PORT"


def resolve_config_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser()

    env_path = os.getenv(CONFIG_ENV_VAR) or os.getenv(LEGACY_CONFIG_ENV_VAR)
    if env_path:
        return Path(env_path).expanduser()

    if PROJECT_ROOT_CONFIG_PATH.exists():
        return PROJECT_ROOT_CONFIG_PATH

    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH

    return DEFAULT_CONFIG_PATH


def _load_raw_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"config file {path} must contain a YAML mapping at the top level")

    return raw


def _apply_server_env_overrides(config: AppConfig) -> None:
    overrides = config.server.model_dump()

    host = os.getenv(SERVER_HOST_ENV_VAR)
    if host is not None:
        overrides["host"] = host.strip()

    port = os.getenv(SERVER_PORT_ENV_VAR)
    if port is not None:
        text = port.strip()
        if text:
            try:
                overrides["port"] = int(text)
            except ValueError as exc:
                raise ValueError(f"{SERVER_PORT_ENV_VAR} must be an integer") from exc

    config.server = ServerConfig.model_validate(overrides)


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = resolve_config_path(path)
    raw_config = _load_raw_config(config_path)
    config = AppConfig.model_validate(raw_config)
    _apply_server_env_overrides(config)
    return config
