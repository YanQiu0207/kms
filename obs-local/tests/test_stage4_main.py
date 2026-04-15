from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

OBS_LOCAL_ROOT = Path(__file__).resolve().parents[1]
if str(OBS_LOCAL_ROOT) not in sys.path:
    sys.path.insert(0, str(OBS_LOCAL_ROOT))

from app.aggregator import aggregate_records
from app.main import create_app
from app.parser import LogSourceContext, parse_log_line
from app.schemas import AggregationConfig, AppConfig, LoggingConfig, ProjectConfig, RuntimeConfig, SourceConfig, StorageConfig, StreamConfig
from app.web import (
    STREAM_EVENT_ERRORS,
    STREAM_EVENT_HEALTH,
    STREAM_EVENT_OVERVIEW,
    STREAM_EVENT_REQUESTS,
    STREAM_EVENT_STAGES,
)

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


def _payload(timestamp: str | None, event: str, **fields: object) -> dict[str, object]:
    payload: dict[str, object] = {"timestamp": timestamp, "event": event}
    payload.update(fields)
    return payload


def _record(payload: dict[str, object]):
    return parse_log_line(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), source=SOURCE)


def _sample_result():
    return aggregate_records(
        [
            _record(
                _payload(
                    "2026-04-15T11:52:01.000+08:00",
                    "http.request.start",
                    request_id="req-ok",
                    method="POST",
                    path="/ask",
                    summary="direct summary",
                )
            ),
            _record(
                _payload(
                    "2026-04-15T11:52:01.045+08:00",
                    "http.request.end",
                    request_id="req-ok",
                    status_code=200,
                    duration_ms=45,
                )
            ),
            _record(
                _payload(
                    "2026-04-15T11:52:02.000+08:00",
                    "semantic.client_load.error",
                    level="ERROR",
                    error_type="RetrievalError",
                    exception="dependency missing",
                )
            ),
        ],
        **AGGREGATION_OPTIONS,
    )


def _write_log(log_path: Path, payloads: list[dict[str, object]]) -> None:
    lines = [json.dumps(payload, ensure_ascii=False, separators=(",", ":")) for payload in payloads]
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_config(
    log_path: Path,
    state_db_path: Path,
    *,
    logging_config: LoggingConfig | None = None,
    runtime_config: RuntimeConfig | None = None,
    stream_config: StreamConfig | None = None,
    aggregation_config: AggregationConfig | None = None,
) -> AppConfig:
    return AppConfig(
        storage=StorageConfig(state_db_path=str(state_db_path)),
        logging=logging_config or LoggingConfig(),
        runtime=runtime_config or RuntimeConfig(),
        stream=stream_config or StreamConfig(),
        aggregation=aggregation_config or AggregationConfig(),
        projects=[
            ProjectConfig(
                project_id="sample-project",
                display_name="Sample Project",
                sources=[
                    SourceConfig(
                        source_id="main",
                        log_path=str(log_path),
                        format="jsonl",
                        timezone="Asia/Shanghai",
                    )
                ],
            )
        ],
    )


def test_stage4_main_wires_api_and_stream(tmp_path: Path):
    log_path = tmp_path / "sample.log"
    _write_log(
        log_path,
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
                "2026-04-15T11:52:01.045+08:00",
                "http.request.end",
                request_id="req-ok",
                status_code=200,
                duration_ms=45,
            ),
            _payload(
                "2026-04-15T11:52:02.000+08:00",
                "semantic.client_load.error",
                level="ERROR",
                error_type="RetrievalError",
                exception="dependency missing",
            ),
        ],
    )
    config = _build_config(log_path, tmp_path / "state.db")
    app = create_app(config)

    with TestClient(app) as client:
        projects_response = client.get("/api/projects")
        assert projects_response.status_code == 200
        assert projects_response.json()["count"] == 1

        overview_response = client.get("/api/overview", params={"project": "sample-project"})
        assert overview_response.status_code == 200
        assert overview_response.json()["project_id"] == "sample-project"

        requests_response = client.get("/api/requests", params={"project": "sample-project"})
        assert requests_response.status_code == 200
        assert requests_response.json()["count"] == 1
        assert getattr(app.state, "stream_hub", None) is not None
        assert any(getattr(route, "path", None) == "/api/stream" for route in app.routes)

        _write_log(
            log_path,
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
                    "2026-04-15T11:52:01.045+08:00",
                    "http.request.end",
                    request_id="req-ok",
                    status_code=200,
                    duration_ms=45,
                ),
                _payload(
                    "2026-04-15T11:53:01.000+08:00",
                    "http.request.start",
                    request_id="req-new",
                    method="GET",
                    path="/search",
                    summary="reloaded request",
                ),
                _payload(
                    "2026-04-15T11:53:01.025+08:00",
                    "http.request.end",
                    request_id="req-new",
                    status_code=200,
                    duration_ms=25,
                ),
            ],
        )

        reload_response = client.post("/api/reload", params={"project": "sample-project"})
        assert reload_response.status_code == 200
        assert reload_response.json()["reloaded"] is True

        requests_after_reload = client.get("/api/requests", params={"project": "sample-project"})
        assert requests_after_reload.status_code == 200
        assert requests_after_reload.json()["count"] == 2


def test_stage4_main_applies_window_filter(tmp_path: Path):
    log_path = tmp_path / "window.log"
    now = datetime.now(timezone.utc)
    old_timestamp = (now - timedelta(days=2)).isoformat(timespec="milliseconds")
    recent_timestamp = now.isoformat(timespec="milliseconds")
    recent_end_timestamp = (now + timedelta(seconds=1)).isoformat(timespec="milliseconds")

    _write_log(
        log_path,
        [
            _payload(
                old_timestamp,
                "http.request.start",
                request_id="req-old",
                method="GET",
                path="/search",
                summary="old request",
            ),
            _payload(
                old_timestamp,
                "http.request.end",
                request_id="req-old",
                status_code=200,
                duration_ms=10,
            ),
            _payload(
                recent_timestamp,
                "http.request.start",
                request_id="req-new",
                method="POST",
                path="/ask",
                summary="recent request",
            ),
            _payload(
                recent_end_timestamp,
                "http.request.end",
                request_id="req-new",
                status_code=200,
                duration_ms=20,
            ),
        ],
    )
    config = _build_config(log_path, tmp_path / "state.db")

    with TestClient(create_app(config)) as client:
        requests_response = client.get("/api/requests", params={"project": "sample-project", "window": "1h"})
        assert requests_response.status_code == 200
        assert requests_response.json()["count"] == 1
        assert requests_response.json()["items"][0]["request_id"] == "req-new"


def test_stage4_main_supports_collection_filters(tmp_path: Path):
    log_path = tmp_path / "filters.log"
    _write_log(
        log_path,
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
                "2026-04-15T11:52:01.015+08:00",
                "query.plan.fetch.end",
                request_id="req-ok",
                span_id="span-fetch",
                duration_ms=15,
            ),
            _payload(
                "2026-04-15T11:52:01.045+08:00",
                "http.request.end",
                request_id="req-ok",
                status_code=200,
                duration_ms=45,
            ),
            _payload(
                "2026-04-15T11:53:01.000+08:00",
                "http.request.start",
                request_id="req-failed",
                method="GET",
                path="/search",
                summary="failed summary",
            ),
            _payload(
                "2026-04-15T11:53:01.020+08:00",
                "semantic.retrieve.error",
                request_id="req-failed",
                path="/search",
                level="ERROR",
                error_type="RetrievalError",
                status_code=503,
                exception="upstream timeout",
            ),
            _payload(
                "2026-04-15T11:53:01.030+08:00",
                "query.plan.rank.end",
                request_id="req-failed",
                span_id="span-rank",
                duration_ms=22,
            ),
            _payload(
                "2026-04-15T11:53:01.040+08:00",
                "http.request.end",
                request_id="req-failed",
                status_code=503,
                duration_ms=40,
            ),
        ],
    )
    config = _build_config(log_path, tmp_path / "filters-state.db")

    with TestClient(create_app(config)) as client:
        requests_response = client.get(
            "/api/requests",
            params={
                "project": "sample-project",
                "path": "/search",
                "status": "failed",
                "method": "GET",
            },
        )
        assert requests_response.status_code == 200
        assert requests_response.json()["count"] == 1
        assert requests_response.json()["items"][0]["request_id"] == "req-failed"

        errors_response = client.get(
            "/api/errors",
            params={
                "project": "sample-project",
                "path": "/search",
                "error_type": "RetrievalError",
                "status_code": 503,
            },
        )
        assert errors_response.status_code == 200
        assert errors_response.json()["count"] == 1
        assert errors_response.json()["items"][0]["request_id"] == "req-failed"

        stages_response = client.get(
            "/api/stages",
            params={
                "project": "sample-project",
                "stage": "query.plan.rank",
            },
        )
        assert stages_response.status_code == 200
        assert stages_response.json()["count"] == 1
        assert stages_response.json()["items"][0]["stage"] == "query.plan.rank"


def test_stage4_main_uses_configured_aggregation_limits(tmp_path: Path):
    log_path = tmp_path / "aggregation.log"
    _write_log(
        log_path,
        [
            _payload(
                "2026-04-15T11:52:01.000+08:00",
                "http.request.start",
                request_id="req-a",
                method="POST",
                path="/ask",
                summary="request a",
            ),
            _payload(
                "2026-04-15T11:52:01.010+08:00",
                "query.plan.fetch.end",
                request_id="req-a",
                span_id="span-a-fetch",
                duration_ms=10,
            ),
            _payload(
                "2026-04-15T11:52:01.020+08:00",
                "query.plan.rank.end",
                request_id="req-a",
                span_id="span-a-rank",
                duration_ms=8,
            ),
            _payload(
                "2026-04-15T11:52:01.030+08:00",
                "http.request.end",
                request_id="req-a",
                status_code=200,
                duration_ms=30,
            ),
            _payload(
                "2026-04-15T11:53:01.000+08:00",
                "http.request.start",
                request_id="req-b",
                method="GET",
                path="/search",
                summary="request b",
            ),
            _payload(
                "2026-04-15T11:53:01.015+08:00",
                "query.plan.fetch.end",
                request_id="req-b",
                span_id="span-b-fetch",
                duration_ms=15,
            ),
            _payload(
                "2026-04-15T11:53:01.030+08:00",
                "http.request.end",
                request_id="req-b",
                status_code=200,
                duration_ms=30,
            ),
        ],
    )
    config = _build_config(
        log_path,
        tmp_path / "aggregation-state.db",
        aggregation_config=AggregationConfig(top_n=1, request_stage_limit=1),
    )
    app = create_app(config)

    with TestClient(app) as client:
        response = client.get("/api/requests", params={"project": "sample-project"})
        assert response.status_code == 200
        assert len(response.json()["items"][0]["top_stages"]) == 1

    assert len(app.state.aggregation_result.overview.top_requests) == 1
    assert len(app.state.aggregation_result.overview.top_stages) == 1


def test_stage4_main_emits_structured_request_logs_and_writes_log_file(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    log_path = tmp_path / "logging.log"
    _write_log(
        log_path,
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
                "2026-04-15T11:52:01.045+08:00",
                "http.request.end",
                request_id="req-ok",
                status_code=200,
                duration_ms=45,
            ),
        ],
    )
    log_dir = tmp_path / "service-logs"
    config = _build_config(
        log_path,
        tmp_path / "logging-state.db",
        logging_config=LoggingConfig(level="INFO", log_dir=str(log_dir)),
        stream_config=StreamConfig(max_queue_size=3),
    )
    app = create_app(config)

    with caplog.at_level(logging.INFO):
        with TestClient(app) as client:
            response = client.get("/api/health")
            assert response.status_code == 200

    event_names = [
        record.context.get("event")
        for record in caplog.records
        if isinstance(getattr(record, "context", None), dict)
    ]
    assert "app.startup.start" in event_names
    assert "http.request.start" in event_names
    assert "http.request.end" in event_names
    assert "app.shutdown.end" in event_names
    assert app.state.stream_hub._max_queue_size == 3
    assert (log_dir / "obs-local.log").exists()


def test_stage4_main_logs_tailer_errors_instead_of_swallowing_them(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    log_path = tmp_path / "tail-error.log"
    _write_log(
        log_path,
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
                "2026-04-15T11:52:01.045+08:00",
                "http.request.end",
                request_id="req-ok",
                status_code=200,
                duration_ms=45,
            ),
        ],
    )
    app = create_app(_build_config(log_path, tmp_path / "tail-error-state.db"), tail_poll_interval_seconds=0.05)

    with caplog.at_level(logging.ERROR):
        with TestClient(app):
            log_path.unlink()
            deadline = time.time() + 1.0
            while time.time() < deadline:
                if any(
                    isinstance(getattr(record, "context", None), dict)
                    and record.context.get("event") == "tail.source.error"
                    for record in caplog.records
                ):
                    break
                time.sleep(0.05)
            else:
                raise AssertionError("tail.source.error log was not emitted")


def test_stage4_main_caps_cached_records_to_runtime_limit(tmp_path: Path):
    log_path = tmp_path / "cache-limit.log"
    _write_log(
        log_path,
        [
            _payload(
                "2026-04-15T11:52:01.000+08:00",
                "http.request.start",
                request_id="req-old",
                method="POST",
                path="/ask",
                summary="old request",
            ),
            _payload(
                "2026-04-15T11:52:01.030+08:00",
                "http.request.end",
                request_id="req-old",
                status_code=200,
                duration_ms=30,
            ),
        ],
    )
    app = create_app(
        _build_config(
            log_path,
            tmp_path / "cache-limit-state.db",
            runtime_config=RuntimeConfig(max_cached_records=4),
        ),
        tail_poll_interval_seconds=0.05,
    )

    with TestClient(app) as client:
        _write_log(
            log_path,
            [
                _payload(
                    "2026-04-15T11:52:01.000+08:00",
                    "http.request.start",
                    request_id="req-old",
                    method="POST",
                    path="/ask",
                    summary="old request",
                ),
                _payload(
                    "2026-04-15T11:52:01.030+08:00",
                    "http.request.end",
                    request_id="req-old",
                    status_code=200,
                    duration_ms=30,
                ),
                _payload(
                    "2026-04-15T11:53:01.000+08:00",
                    "http.request.start",
                    request_id="req-mid",
                    method="GET",
                    path="/search",
                    summary="mid request",
                ),
                _payload(
                    "2026-04-15T11:53:01.020+08:00",
                    "http.request.end",
                    request_id="req-mid",
                    status_code=200,
                    duration_ms=20,
                ),
                _payload(
                    "2026-04-15T11:54:01.000+08:00",
                    "http.request.start",
                    request_id="req-new",
                    method="GET",
                    path="/reload",
                    summary="new request",
                ),
                _payload(
                    "2026-04-15T11:54:01.025+08:00",
                    "http.request.end",
                    request_id="req-new",
                    status_code=200,
                    duration_ms=25,
                ),
            ],
        )

        deadline = time.time() + 2.0
        while time.time() < deadline:
            cached_request_ids = {record.request_id for record in app.state.parsed_records}
            if len(app.state.parsed_records) == 4 and cached_request_ids == {"req-mid", "req-new"}:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("parsed_records cache was not trimmed to the configured limit")

        response = client.get("/api/requests", params={"project": "sample-project"})
        assert response.status_code == 200
        assert response.json()["count"] == 2
        assert {item["request_id"] for item in response.json()["items"]} == {"req-mid", "req-new"}


def test_stage4_main_window_filter_excludes_timestampless_records(tmp_path: Path):
    log_path = tmp_path / "timestampless.log"
    now = datetime.now(timezone.utc)
    old_timestamp = (now - timedelta(days=2)).isoformat(timespec="milliseconds")
    recent_timestamp = now.isoformat(timespec="milliseconds")
    recent_end_timestamp = (now + timedelta(seconds=1)).isoformat(timespec="milliseconds")

    _write_log(
        log_path,
        [
            _payload(
                old_timestamp,
                "http.request.start",
                request_id="req-old",
                method="GET",
                path="/search",
                summary="old request",
            ),
            _payload(
                old_timestamp,
                "http.request.end",
                request_id="req-old",
                status_code=200,
                duration_ms=10,
            ),
            _payload(
                recent_timestamp,
                "http.request.start",
                request_id="req-new",
                method="POST",
                path="/ask",
                summary="recent request",
            ),
            _payload(
                recent_end_timestamp,
                "http.request.end",
                request_id="req-new",
                status_code=200,
                duration_ms=20,
            ),
            _payload(
                None,
                "http.request.start",
                request_id="req-ghost",
                method="POST",
                path="/ghost",
                summary="timestampless request",
            ),
            _payload(
                None,
                "http.request.end",
                request_id="req-ghost",
                status_code=200,
                duration_ms=5,
            ),
        ],
    )
    config = _build_config(log_path, tmp_path / "state.db")

    with TestClient(create_app(config)) as client:
        requests_response = client.get("/api/requests", params={"project": "sample-project", "window": "1h"})
        assert requests_response.status_code == 200
        assert requests_response.json()["count"] == 1
        assert requests_response.json()["items"][0]["request_id"] == "req-new"
        assert all(item["request_id"] != "req-ghost" for item in requests_response.json()["items"])


async def _collect_event_names(subscription, expected_count: int, *, timeout_seconds: float = 2.0) -> list[str]:
    events: list[str] = []
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while len(events) < expected_count:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        envelope = await asyncio.wait_for(subscription.get(), timeout=remaining)
        if envelope is None:
            break
        events.append(envelope.event)
    return events


@pytest.mark.anyio
async def test_stage4_main_reload_publishes_sse_updates(tmp_path: Path):
    log_path = tmp_path / "reload.log"
    _write_log(
        log_path,
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
                "2026-04-15T11:52:01.045+08:00",
                "http.request.end",
                request_id="req-ok",
                status_code=200,
                duration_ms=45,
            ),
        ],
    )
    app = create_app(_build_config(log_path, tmp_path / "state.db"), tail_poll_interval_seconds=0.05)

    with TestClient(app) as client:
        subscription = app.state.stream_hub.subscribe(loop=asyncio.get_running_loop(), project_id="sample-project")
        try:
            response = client.post("/api/reload", params={"project": "sample-project"})
            assert response.status_code == 200

            event_names = await _collect_event_names(subscription, 5)
            assert STREAM_EVENT_HEALTH in event_names
            assert STREAM_EVENT_OVERVIEW in event_names
            assert STREAM_EVENT_REQUESTS in event_names
            assert STREAM_EVENT_ERRORS in event_names
            assert STREAM_EVENT_STAGES in event_names
        finally:
            app.state.stream_hub.unsubscribe(subscription)


@pytest.mark.anyio
async def test_stage4_main_tails_new_log_lines_and_publishes_updates(tmp_path: Path):
    log_path = tmp_path / "live.log"
    _write_log(
        log_path,
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
                "2026-04-15T11:52:01.045+08:00",
                "http.request.end",
                request_id="req-ok",
                status_code=200,
                duration_ms=45,
            ),
        ],
    )
    app = create_app(_build_config(log_path, tmp_path / "state.db"), tail_poll_interval_seconds=0.05)

    with TestClient(app) as client:
        subscription = app.state.stream_hub.subscribe(loop=asyncio.get_running_loop(), project_id="sample-project")
        try:
            _write_log(
                log_path,
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
                        "2026-04-15T11:52:01.045+08:00",
                        "http.request.end",
                        request_id="req-ok",
                        status_code=200,
                        duration_ms=45,
                    ),
                    _payload(
                        "2026-04-15T11:53:01.000+08:00",
                        "http.request.start",
                        request_id="req-live",
                        method="GET",
                        path="/search",
                        summary="live request",
                    ),
                    _payload(
                        "2026-04-15T11:53:01.030+08:00",
                        "http.request.end",
                        request_id="req-live",
                        status_code=200,
                        duration_ms=30,
                    ),
                ],
            )

            event_names = await _collect_event_names(subscription, 5, timeout_seconds=3.0)
            assert STREAM_EVENT_REQUESTS in event_names
            assert STREAM_EVENT_OVERVIEW in event_names

            deadline = asyncio.get_running_loop().time() + 3.0
            while True:
                response = client.get("/api/requests", params={"project": "sample-project"})
                assert response.status_code == 200
                if response.json()["count"] == 2:
                    assert any(item["request_id"] == "req-live" for item in response.json()["items"])
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    raise AssertionError("tail watcher did not pick up appended log lines")
                await asyncio.sleep(0.05)
        finally:
            app.state.stream_hub.unsubscribe(subscription)
