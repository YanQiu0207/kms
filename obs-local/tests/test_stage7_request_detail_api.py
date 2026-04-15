from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

OBS_LOCAL_ROOT = Path(__file__).resolve().parents[1]
if str(OBS_LOCAL_ROOT) not in sys.path:
    sys.path.insert(0, str(OBS_LOCAL_ROOT))

from app.aggregator import aggregate_records
from app.api_requests import router as requests_router
from app.parser import LogSourceContext, parse_log_line

AGGREGATION_OPTIONS = {
    "top_n": 20,
    "request_stage_limit": 5,
}


def _source(project_id: str, source_id: str) -> LogSourceContext:
    return LogSourceContext(
        project_id=project_id,
        source_id=source_id,
        log_path=f"{project_id}.log",
        timezone="Asia/Shanghai",
        service_hint="demo-api",
    )


def _record(source: LogSourceContext, timestamp: str, event: str, **fields: object):
    payload: dict[str, object] = {
        "timestamp": timestamp,
        "event": event,
        "request_id": "req-shared",
    }
    payload.update(fields)
    return parse_log_line(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), source=source)


def _sample_result():
    records = [
        _record(
            _source("project-a", "main"),
            "2026-04-15T18:20:01.000+08:00",
            "http.request.start",
            method="POST",
            path="/ask",
        ),
        _record(
            _source("project-a", "main"),
            "2026-04-15T18:20:01.120+08:00",
            "http.request.end",
            status_code=200,
            duration_ms=120,
        ),
        _record(
            _source("project-b", "main"),
            "2026-04-15T18:20:02.000+08:00",
            "http.request.start",
            method="GET",
            path="/search",
        ),
        _record(
            _source("project-b", "main"),
            "2026-04-15T18:20:02.210+08:00",
            "http.request.error",
            status="error",
            level="ERROR",
            error_type="TimeoutError",
            duration_ms=210,
        ),
    ]
    return aggregate_records(records, **AGGREGATION_OPTIONS)


def _client():
    app = FastAPI()
    result = _sample_result()
    app.state.aggregation_provider = lambda *, project_id=None, window=None: result
    app.include_router(requests_router)
    return TestClient(app)


def test_request_detail_requires_project_filter_when_request_id_is_ambiguous():
    with _client() as client:
        response = client.get("/api/requests/req-shared")
    assert response.status_code == 409


def test_request_detail_returns_scoped_payload_with_project_filter():
    with _client() as client:
        response = client.get("/api/requests/req-shared", params={"project": "project-a"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["project_id"] == "project-a"
    assert payload["summary"]["request_id"] == "req-shared"


def test_request_detail_returns_404_for_unknown_request():
    with _client() as client:
        response = client.get("/api/requests/req-not-found", params={"project": "project-a"})
    assert response.status_code == 404
