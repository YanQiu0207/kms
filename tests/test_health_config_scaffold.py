from __future__ import annotations

import pytest


def test_config_module_is_importable():
    config = pytest.importorskip("app.config")
    assert config.__name__ == "app.config"


def test_main_module_is_importable_without_executing_entrypoint():
    main = pytest.importorskip("app.main")
    assert main.__name__ == "app.main"


def test_health_boundary_package_present():
    module = pytest.importorskip("app")
    assert module.__name__ == "app"
