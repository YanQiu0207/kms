from __future__ import annotations

import sys
from pathlib import Path

import pytest

OBS_LOCAL_ROOT = Path(__file__).resolve().parents[1]
if str(OBS_LOCAL_ROOT) not in sys.path:
    sys.path.insert(0, str(OBS_LOCAL_ROOT))

from app.config import CONFIG_ENV_VAR, LEGACY_CONFIG_ENV_VAR, SERVER_PORT_ENV_VAR, load_config, resolve_config_path


def test_resolve_config_path_prefers_explicit_then_env_then_legacy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("{}", encoding="utf-8")
    assert resolve_config_path(explicit) == explicit

    env_config = tmp_path / "env.yaml"
    env_config.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(env_config))
    assert resolve_config_path() == env_config

    monkeypatch.delenv(CONFIG_ENV_VAR)
    legacy_config = tmp_path / "legacy.yaml"
    legacy_config.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(LEGACY_CONFIG_ENV_VAR, str(legacy_config))
    assert resolve_config_path() == legacy_config


def test_load_config_rejects_invalid_port_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(config_path))
    monkeypatch.setenv(SERVER_PORT_ENV_VAR, "abc")

    with pytest.raises(ValueError, match="OBS_LOCAL_PORT must be an integer"):
        load_config()
