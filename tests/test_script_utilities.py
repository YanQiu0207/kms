from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace


class _FakeResponse:
    def __init__(self, status: int, payload: dict[str, object]):
        self.status = status
        self._raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _fake_config(host: str = "127.0.0.1", port: int = 49153) -> SimpleNamespace:
    return SimpleNamespace(server=SimpleNamespace(host=host, port=port))


def test_probe_kms_script_reports_health(monkeypatch, capsys, tmp_path: Path):
    module = importlib.import_module("scripts.probe_kms")

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: SimpleNamespace(config=None, host=None, port=None, timeout=3.0),
    )
    monkeypatch.setattr(module, "resolve_config_path", lambda path: tmp_path / "config.yaml")
    monkeypatch.setattr(module, "load_config", lambda path: _fake_config())
    monkeypatch.setattr(
        module,
        "urlopen",
        lambda url, timeout: _FakeResponse(
            200,
            {
                "status": "ok",
                "service": "kms-api",
                "version": "0.1.0",
                "timestamp": "2026-04-16 10:00:00.000",
            },
        ),
    )

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["url"] == "http://127.0.0.1:49153/health"
    assert payload["service"] == "kms-api"


def test_update_index_script_posts_expected_payload(monkeypatch, capsys, tmp_path: Path):
    module = importlib.import_module("scripts.update_index")

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: SimpleNamespace(config=None, host=None, port=None, mode="full", timeout=30.0),
    )
    monkeypatch.setattr(module, "resolve_config_path", lambda path: tmp_path / "config.yaml")
    monkeypatch.setattr(module, "load_config", lambda path: _fake_config())

    def _fake_urlopen(request, timeout):
        assert request.full_url == "http://127.0.0.1:49153/index"
        assert request.get_method() == "POST"
        assert request.data == b'{"mode": "full"}'
        return _FakeResponse(
            200,
            {
                "mode": "full",
                "indexed_documents": 3,
                "indexed_chunks": 12,
                "skipped_documents": 1,
                "deleted_documents": 0,
                "message": "完成全量索引",
            },
        )

    monkeypatch.setattr(module, "urlopen", _fake_urlopen)

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["mode"] == "full"
    assert payload["indexed_documents"] == 3
