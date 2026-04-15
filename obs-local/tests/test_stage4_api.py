from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

OBS_LOCAL_ROOT = Path(__file__).resolve().parents[1]
if str(OBS_LOCAL_ROOT) not in sys.path:
    sys.path.insert(0, str(OBS_LOCAL_ROOT))

from app.aggregator import aggregate_records
from app.api_errors import build_errors_payload, router as errors_router
from app.api_projects import (
    build_overview_payload,
    build_project_payload,
    build_projects_payload,
    build_reload_payload,
    register_project_from_config,
    router as projects_router,
)
from app.main import create_app
from app.api_requests import build_request_detail_payload, build_requests_payload, router as requests_router
from app.api_stages import build_stages_payload, router as stages_router
from app.parser import LogSourceContext, parse_log_line
from app.registry import ProjectSpec, SourceRegistry, SourceSpec
from app.schemas import AppConfig, ProjectConfig, SourceConfig, StorageConfig, UiConfig
from app.state_store import SQLiteStateStore, SourceHealthState

AGGREGATION_OPTIONS = {
    "top_n": 20,
    "request_stage_limit": 5,
}


SOURCE = LogSourceContext(
    project_id="sample-project",
    source_id="main",
    log_path="sample.log",
    timezone="Asia/Shanghai",
    service_hint="demo-api",
)


def _payload(timestamp: str, event: str, **fields: object) -> dict[str, object]:
    payload: dict[str, object] = {"timestamp": timestamp, "event": event}
    payload.update(fields)
    return payload


def _record(payload: dict[str, object]):
    return parse_log_line(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), source=SOURCE)


def _records(payloads: list[dict[str, object]]):
    return [_record(payload) for payload in payloads]


def _sample_result():
    return aggregate_records(
        _records(
            [
                _payload(
                    "2026-04-15T11:52:01.000+08:00",
                    "http.request.start",
                    request_id="req-ok",
                    method="POST",
                    path="/ask",
                    summary="direct summary",
                ),
                _payload(
                    "2026-04-15T11:52:01.010+08:00",
                    "query.plan.end",
                    request_id="req-ok",
                    span_id="span-root",
                    duration_ms=30,
                ),
                _payload(
                    "2026-04-15T11:52:01.020+08:00",
                    "query.plan.fetch.end",
                    request_id="req-ok",
                    span_id="span-child",
                    parent_span_id="span-root",
                    duration_ms=20,
                ),
                _payload(
                    "2026-04-15T11:52:01.045+08:00",
                    "http.request.end",
                    request_id="req-ok",
                    status_code=200,
                    duration_ms=45,
                ),
                _payload(
                    "2026-04-15T11:52:02.000+08:00",
                    "http.request.start",
                    request_id="req-failed",
                    method="GET",
                    path="/search",
                    attributes={"display_summary": "summary from attributes"},
                ),
                _payload(
                    "2026-04-15T11:52:02.020+08:00",
                    "http.request.end",
                    request_id="req-failed",
                    status_code=503,
                    duration_ms=20,
                ),
                _payload(
                    "2026-04-15T11:52:03.000+08:00",
                    "http.request.start",
                    request_id="req-error",
                    method="POST",
                    path="/index",
                    summary="error summary",
                ),
                _payload(
                    "2026-04-15T11:52:03.030+08:00",
                    "http.request.error",
                    request_id="req-error",
                    status="error",
                    level="ERROR",
                    error_type="TimeoutError",
                    exception="request timed out",
                    duration_ms=30,
                ),
                _payload(
                    "2026-04-15T11:52:03.100+08:00",
                    "semantic.client_load.error",
                    level="ERROR",
                    error_type="RetrievalError",
                    exception="dependency missing",
                ),
            ]
        ),
        **AGGREGATION_OPTIONS,
    )


def _registry(tmp_path: Path) -> SourceRegistry:
    store = SQLiteStateStore(tmp_path / "state.db")
    registry = SourceRegistry(store)
    registry.register_project(
        ProjectSpec(
            project_id="sample-project",
            name="Sample Project",
            enabled=True,
            metadata={},
            sources=(
                SourceSpec(
                    project_id="sample-project",
                    source_id="main",
                    log_path="sample.log",
                    name="main",
                    enabled=True,
                ),
            ),
        )
    )
    return registry


def test_api_routing_coverage():
    paths = {
        route.path
        for router in (projects_router, requests_router, errors_router, stages_router)
        for route in router.routes
        if hasattr(route, "path")
    }

    assert "/api/projects" in paths
    assert "/api/overview" in paths
    assert "/api/reload" in paths
    assert "/api/requests" in paths
    assert "/api/requests/{request_id}" in paths
    assert "/api/errors" in paths
    assert "/api/stages" in paths


def test_ui_settings_returns_configured_default_locale(tmp_path: Path):
    app = create_app(
        AppConfig(
            storage=StorageConfig(state_db_path=str(tmp_path / "state.db")),
            ui=UiConfig(default_locale="bilingual"),
            projects=[
                ProjectConfig(
                    project_id="sample-project",
                    display_name="Sample Project",
                    sources=[SourceConfig(source_id="main", log_path=str(tmp_path / "sample.log"))],
                )
            ],
        )
    )
    paths = {route.path for route in app.routes if hasattr(route, "path")}

    with TestClient(app) as client:
        response = client.get("/api/ui-settings")

    assert "/api/ui-settings" in paths
    assert response.status_code == 200
    assert response.json() == {
        "default_locale": "bilingual",
        "available_locales": ["zh", "en", "bilingual"],
    }


def test_project_payload_and_reload(tmp_path: Path):
    registry = _registry(tmp_path)
    registry.store.upsert_source_health(
        SourceHealthState(
            project_id="sample-project",
            source_id="main",
            last_event_at="2026-04-15T11:52:03.030+08:00",
            replaying=False,
            tailer_error=None,
        )
    )

    projects_payload = build_projects_payload(registry)
    assert projects_payload["count"] == 1
    project = projects_payload["projects"][0]
    assert project["project_id"] == "sample-project"
    assert project["sources"][0]["log_path"] == "sample.log"
    assert project["staleness"] == "live"

    project_payload = build_project_payload(registry, "sample-project")
    assert project_payload is not None
    assert project_payload["name"] == "Sample Project"

    reload_payload = build_reload_payload(registry)
    assert reload_payload["count"] == 1
    assert reload_payload["projects"][0]["project_id"] == "sample-project"


def test_register_project_from_config(tmp_path: Path):
    registry = _registry(tmp_path)
    payload = ProjectConfig(
        project_id="new-project",
        display_name="New Project",
        enabled=True,
        summary_mapping={"api.ask.start": "question"},
        sources=[
            SourceConfig(
                source_id="main",
                log_path="new.log",
                format="jsonl",
                timezone="Asia/Shanghai",
                service_hint="demo",
                redact_fields=["question"],
                enabled=True,
            )
        ],
    )

    project = register_project_from_config(registry, payload)
    assert project["project_id"] == "new-project"
    assert project["display_name"] == "New Project"
    assert project["sources"][0]["redact_fields"] == ["question"]


def test_post_project_rejects_log_path_outside_allowed_roots(tmp_path: Path):
    allowed_log_path = tmp_path / "sample.log"
    allowed_log_path.write_text("", encoding="utf-8")
    app = create_app(
        AppConfig(
            storage=StorageConfig(state_db_path=str(tmp_path / "state.db")),
            projects=[
                ProjectConfig(
                    project_id="sample-project",
                    display_name="Sample Project",
                    sources=[SourceConfig(source_id="main", log_path=str(allowed_log_path))],
                )
            ],
        )
    )
    outside_log_path = tmp_path.parent / "outside.log"

    with TestClient(app) as client:
        response = client.post(
            "/api/projects",
            json={
                "project_id": "outside-project",
                "display_name": "Outside Project",
                "sources": [
                    {
                        "source_id": "main",
                        "log_path": str(outside_log_path),
                    }
                ],
            },
        )

    assert response.status_code == 400
    assert "outside allowed roots" in response.json()["detail"]["message"]


def test_requests_errors_stages_and_overview(tmp_path: Path):
    registry = _registry(tmp_path)
    registry.store.upsert_source_health(
        SourceHealthState(
            project_id="sample-project",
            source_id="main",
            last_event_at="2026-04-15T11:52:03.030+08:00",
            replaying=False,
            tailer_error=None,
        )
    )
    result = _sample_result()

    requests_payload = build_requests_payload(result, project_id="sample-project", status="failed")
    assert requests_payload["count"] == 2
    assert all(item["status"] == "failed" for item in requests_payload["items"])

    detail_payload = build_request_detail_payload(result, "req-ok", project_id="sample-project")
    assert detail_payload is not None
    assert detail_payload["summary"]["request_id"] == "req-ok"
    assert detail_payload["stages"][0]["stage"] == "query.plan.fetch"

    errors_payload = build_errors_payload(result, project_id="sample-project", error_type="RetrievalError")
    assert errors_payload["count"] == 1
    assert errors_payload["items"][0]["error_type"] == "RetrievalError"

    stages_payload = build_stages_payload(result, project_id="sample-project", stage="query.plan.fetch")
    assert stages_payload["count"] == 1
    assert stages_payload["items"][0]["stage"] == "query.plan.fetch"

    overview_payload = build_overview_payload(registry, result, project_id="sample-project", limit=2)
    assert overview_payload["project_id"] == "sample-project"
    assert overview_payload["staleness"] == "live"
    assert overview_payload["request_p95_ms"] is not None
    assert overview_payload["slowest_stage"]["stage"] == "query.plan.fetch"
    assert len(overview_payload["top_requests"]) == 2


def test_build_errors_payload_status_code_filter_excludes_none_status_code():
    payload = {
        "errors": [
            {
                "project_id": "sample-project",
                "request_id": "req-a",
                "status_code": None,
                "error_type": "TimeoutError",
            },
            {
                "project_id": "sample-project",
                "request_id": "req-b",
                "status_code": 503,
                "error_type": "UpstreamError",
            },
        ]
    }

    errors_payload = build_errors_payload(payload, project_id="sample-project", status_code=503)
    assert errors_payload["count"] == 1
    assert errors_payload["items"][0]["request_id"] == "req-b"


def test_build_overview_payload_aggregates_global_staleness(tmp_path: Path):
    registry = _registry(tmp_path)
    registry.register_project(
        ProjectSpec(
            project_id="idle-project",
            name="Idle Project",
            enabled=True,
            metadata={},
            sources=(
                SourceSpec(
                    project_id="idle-project",
                    source_id="main",
                    log_path="idle.log",
                    name="main",
                    enabled=True,
                ),
            ),
        )
    )
    registry.store.upsert_source_health(
        SourceHealthState(
            project_id="sample-project",
            source_id="main",
            last_event_at="2026-04-15T11:52:03.030+08:00",
            replaying=False,
            tailer_error=None,
        )
    )

    overview_payload = build_overview_payload(registry, _sample_result(), limit=5)
    assert overview_payload["project_id"] is None
    assert overview_payload["staleness"] == "live"
    assert overview_payload["last_event_at"] == "2026-04-15T11:52:03.030+08:00"


def test_build_projects_payload_keeps_disabled_source_offline_even_with_history(tmp_path: Path):
    registry = _registry(tmp_path)
    registry.register_project(
        ProjectSpec(
            project_id="disabled-project",
            name="Disabled Project",
            enabled=True,
            metadata={},
            sources=(
                SourceSpec(
                    project_id="disabled-project",
                    source_id="main",
                    log_path="disabled.log",
                    name="main",
                    enabled=False,
                ),
            ),
        )
    )
    registry.store.upsert_source_health(
        SourceHealthState(
            project_id="disabled-project",
            source_id="main",
            last_event_at="2026-04-15T11:52:03.030+08:00",
            replaying=False,
            tailer_error=None,
        )
    )

    projects_payload = build_projects_payload(registry)
    disabled_project = next(item for item in projects_payload["projects"] if item["project_id"] == "disabled-project")
    assert disabled_project["staleness"] == "offline"
    assert disabled_project["sources"][0]["staleness"] == "offline"
