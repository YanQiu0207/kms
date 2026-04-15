from __future__ import annotations

import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient

OBS_LOCAL_ROOT = Path(__file__).resolve().parents[1]
if str(OBS_LOCAL_ROOT) not in sys.path:
    sys.path.insert(0, str(OBS_LOCAL_ROOT))

from app.main import create_app
from app.schemas import AppConfig, ProjectConfig, ServerConfig, SourceConfig, StorageConfig
from app.state_store import SourceHealthState


def _write_jsonl(log_path: Path, payloads: list[dict[str, object]]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "\n".join(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) for payload in payloads) + "\n",
        encoding="utf-8",
    )


def _build_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        server=ServerConfig(host="127.0.0.1", port=49154),
        storage=StorageConfig(state_db_path=str(tmp_path / "state" / "state.db")),
        projects=[
            ProjectConfig(
                project_id="mykms",
                display_name="mykms",
                summary_mapping={"api.ask.start": "question"},
                sources=[
                    SourceConfig(
                        source_id="main",
                        log_path=str(tmp_path / "logs" / "kms-api.log"),
                        format="jsonl",
                        timezone="Asia/Shanghai",
                        service_hint="kms-api",
                        redact_fields=["question"],
                        enabled=True,
                    )
                ],
            )
        ],
    )


def test_health_endpoint_bootstraps_registry_from_config(tmp_path: Path):
    log_path = tmp_path / "logs" / "kms-api.log"
    _write_jsonl(
        log_path,
        [
            {
                "timestamp": "2026-04-15T11:52:01.000+08:00",
                "event": "http.request.start",
                "request_id": "req-1",
                "path": "/ask",
            },
            {
                "timestamp": "2026-04-15T11:52:01.020+08:00",
                "event": "http.request.end",
                "request_id": "req-1",
                "status_code": 200,
                "duration_ms": 20,
            },
        ],
    )
    app = create_app(_build_config(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"]["service"] == "obs-local"
    assert payload["service"]["status"] == "ok"
    assert len(payload["projects"]) == 1
    project = payload["projects"][0]
    assert project["project_id"] == "mykms"
    assert project["display_name"] == "mykms"
    assert len(project["sources"]) == 1
    source = project["sources"][0]
    assert source["source_id"] == "main"
    assert source["log_path"].endswith("kms-api.log")
    assert source["staleness"] in {"idle", "offline", "live", "stale"}


def test_health_endpoint_reports_source_error_from_state_store(tmp_path: Path):
    log_path = tmp_path / "logs" / "kms-api.log"
    _write_jsonl(log_path, [])
    app = create_app(_build_config(tmp_path))
    client = TestClient(app)

    with client:
        app.state.registry.store.upsert_source_health(
            SourceHealthState(
                source_id="main",
                project_id="mykms",
                last_event_at=None,
                last_error_at="2026-04-15T14:00:00+08:00",
                last_error_message="tail failed",
                replaying=False,
                tailer_error="tail failed",
            )
        )
        response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    project = payload["projects"][0]
    assert project["status"] == "error"
    assert project["tailer_error"] == "tail failed"
    assert project["sources"][0]["status"] == "error"
    assert project["sources"][0]["tailer_error"] == "tail failed"


def test_health_endpoint_keeps_sources_isolated_across_projects(tmp_path: Path):
    _write_jsonl(tmp_path / "logs" / "project-a.log", [])
    _write_jsonl(tmp_path / "logs" / "project-b.log", [])
    config = AppConfig(
        server=ServerConfig(host="127.0.0.1", port=49154),
        storage=StorageConfig(state_db_path=str(tmp_path / "state" / "state.db")),
        projects=[
            ProjectConfig(
                project_id="project-a",
                display_name="project-a",
                sources=[
                    SourceConfig(
                        source_id="main",
                        log_path=str(tmp_path / "logs" / "project-a.log"),
                    )
                ],
            ),
            ProjectConfig(
                project_id="project-b",
                display_name="project-b",
                sources=[
                    SourceConfig(
                        source_id="main",
                        log_path=str(tmp_path / "logs" / "project-b.log"),
                    )
                ],
            ),
        ],
    )
    app = create_app(config)

    with TestClient(app) as client:
        app.state.registry.store.upsert_source_health(
            SourceHealthState(
                project_id="project-a",
                source_id="main",
                last_event_at="2026-04-15T14:00:00+08:00",
                tailer_error="project-a error",
            )
        )
        app.state.registry.store.upsert_source_health(
            SourceHealthState(
                project_id="project-b",
                source_id="main",
                last_event_at="2026-04-15T14:01:00+08:00",
                tailer_error=None,
            )
        )
        payload = client.get("/api/health").json()

    assert len(payload["projects"]) == 2
    project_a = next(item for item in payload["projects"] if item["project_id"] == "project-a")
    project_b = next(item for item in payload["projects"] if item["project_id"] == "project-b")
    assert project_a["tailer_error"] == "project-a error"
    assert project_a["sources"][0]["tailer_error"] == "project-a error"
    assert project_b["tailer_error"] is None
    assert project_b["sources"][0]["tailer_error"] is None


def test_health_endpoint_keeps_disabled_source_offline_even_with_persisted_event(tmp_path: Path):
    log_path = tmp_path / "logs" / "kms-api.log"
    _write_jsonl(log_path, [])
    config = AppConfig(
        server=ServerConfig(host="127.0.0.1", port=49154),
        storage=StorageConfig(state_db_path=str(tmp_path / "state" / "state.db")),
        projects=[
            ProjectConfig(
                project_id="mykms",
                display_name="mykms",
                sources=[
                    SourceConfig(
                        source_id="main",
                        log_path=str(log_path),
                        format="jsonl",
                        timezone="Asia/Shanghai",
                        enabled=False,
                    )
                ],
            )
        ],
    )
    app = create_app(config)

    with TestClient(app) as client:
        app.state.registry.store.upsert_source_health(
            SourceHealthState(
                source_id="main",
                project_id="mykms",
                last_event_at="2026-04-15T14:00:00+08:00",
                replaying=False,
                tailer_error=None,
            )
        )
        payload = client.get("/api/health").json()

    project = payload["projects"][0]
    source = project["sources"][0]
    assert project["status"] == "degraded"
    assert source["staleness"] in {"idle", "offline"}
    assert source["status"] != "live"


def test_registry_reload_preserves_declared_project_sources(tmp_path: Path):
    _write_jsonl(tmp_path / "logs" / "kms-api.log", [])
    app = create_app(_build_config(tmp_path))

    with TestClient(app):
        snapshot_before = app.state.registry.snapshot()
        app.state.registry.reload()
        snapshot_after = app.state.registry.snapshot()

    assert len(snapshot_before.projects) == len(snapshot_after.projects) == 1
    assert snapshot_after.projects[0].project_id == "mykms"
    assert len(snapshot_after.projects[0].sources) == 1
    assert snapshot_after.projects[0].sources[0].source_id == "main"


def test_health_endpoint_keeps_disabled_source_offline_even_with_last_event(tmp_path: Path):
    log_path = tmp_path / "logs" / "kms-api.log"
    _write_jsonl(log_path, [])
    config = AppConfig(
        server=ServerConfig(host="127.0.0.1", port=49154),
        storage=StorageConfig(state_db_path=str(tmp_path / "state" / "state.db")),
        projects=[
            ProjectConfig(
                project_id="mykms",
                display_name="mykms",
                sources=[
                    SourceConfig(
                        source_id="main",
                        log_path=str(log_path),
                        enabled=False,
                    )
                ],
            )
        ],
    )
    app = create_app(config)

    with TestClient(app) as client:
        app.state.registry.store.upsert_source_health(
            SourceHealthState(
                project_id="mykms",
                source_id="main",
                last_event_at="2026-04-15T14:00:00+08:00",
                replaying=False,
                tailer_error=None,
            )
        )
        payload = client.get("/api/health").json()

    project = payload["projects"][0]
    assert project["staleness"] in {"idle", "offline"}
    assert project["sources"][0]["staleness"] == "offline"
