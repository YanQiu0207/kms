from __future__ import annotations

import io
import json
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import AppConfig, ChunkerConfig, DataConfig, ModelConfig, SourceConfig
from app.main import create_app
from app.observability import (
    LOG_SCHEMA_VERSION,
    JsonLogFormatter,
    bind_request_id,
    bind_span,
    configure_logging,
    reset_request_id,
    reset_span,
    timed_operation,
)


def _build_config(tmp_path: Path, source_dir: Path) -> AppConfig:
    return AppConfig(
        sources=[SourceConfig(path=str(source_dir), excludes=[])],
        data=DataConfig(
            sqlite=str(tmp_path / "data" / "meta.db"),
            chroma=str(tmp_path / "data" / "chroma"),
            hf_cache=str(tmp_path / "data" / "hf-cache"),
        ),
        models=ModelConfig(
            embedding="debug-hash",
            reranker="debug-reranker",
            device="cpu",
            dtype="float32",
        ),
        chunker=ChunkerConfig(
            version="test-v1",
            chunk_size=120,
            chunk_overlap=20,
        ),
    )


def _parse_jsonl(stream: io.StringIO) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in stream.getvalue().splitlines()
        if line.strip()
    ]


def test_timed_operation_emits_span_metadata_and_duration_ms_for_obs_local_contract():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())

    logger = logging.getLogger("tests.observability")
    original_handlers = list(logger.handlers)
    original_propagate = logger.propagate
    original_level = logger.level
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    token = bind_request_id("req-observability")
    span_frame, span_token = bind_span("http.request", kind="server", span_id="root-span")
    try:
        with timed_operation(logger, "query.search", query_count=2):
            pass
    finally:
        reset_span(span_token)
        reset_request_id(token)
        handler.flush()
        logger.handlers = original_handlers
        logger.propagate = original_propagate
        logger.setLevel(original_level)

    payloads = _parse_jsonl(stream)

    assert [payload["event"] for payload in payloads] == [
        "start",
        "end",
    ]
    assert [payload["message"] for payload in payloads] == [
        "query.search.start",
        "query.search.end",
    ]

    end_payload = payloads[-1]
    assert end_payload["schema_version"] == LOG_SCHEMA_VERSION
    assert end_payload["request_id"] == "req-observability"
    assert end_payload["trace_id"] == "req-observability"
    assert end_payload["status"] == "ok"
    assert end_payload["event_type"] == "end"
    assert end_payload["span_name"] == "query.search"
    assert end_payload["kind"] == "internal"
    assert end_payload["parent_span_id"] == "root-span"
    assert end_payload["span_id"] != "root-span"
    assert end_payload["duration_ms"] >= 0
    assert end_payload["elapsed_ms"] == end_payload["duration_ms"]
    assert end_payload["attributes"]["query_count"] == 2


def test_configure_logging_uses_daily_rotating_file_handler(tmp_path: Path):
    log_dir = tmp_path / "logs"

    configure_logging(log_dir=log_dir, level="INFO")

    handlers = [
        handler
        for handler in logging.getLogger().handlers
        if getattr(handler, "_kms_managed", False)
    ]

    file_handlers = [handler for handler in handlers if isinstance(handler, TimedRotatingFileHandler)]
    assert len(file_handlers) == 1
    assert Path(file_handlers[0].baseFilename) == log_dir.resolve() / "kms-api.log"


def test_http_request_logs_emit_duration_ms_for_obs_local(tmp_path: Path):
    source_dir = tmp_path / "notes"
    source_dir.mkdir()
    (source_dir / "sample.md").write_text("# 标题\n\n接口测试内容。", encoding="utf-8")

    app = create_app(_build_config(tmp_path, source_dir))

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    try:
        with TestClient(app) as client:
            response = client.get("/stats")
        assert response.status_code == 200
    finally:
        handler.flush()
        root_logger.removeHandler(handler)
        handler.close()

    payloads = _parse_jsonl(stream)
    request_events = [
        payload
        for payload in payloads
        if payload.get("span_name") == "http.request" and payload.get("event") in {"start", "end"}
    ]
    stats_events = [
        payload
        for payload in payloads
        if payload.get("span_name") == "api.stats" and payload.get("event") in {"start", "end"}
    ]

    assert len(request_events) >= 2
    assert len(stats_events) >= 2

    start_payload = next(payload for payload in request_events if payload["event"] == "start")
    end_payload = next(payload for payload in request_events if payload["event"] == "end")
    stats_start_payload = next(payload for payload in stats_events if payload["event"] == "start")

    assert end_payload["schema_version"] == LOG_SCHEMA_VERSION
    assert start_payload["message"] == "http.request.start"
    assert end_payload["message"] == "http.request.end"
    assert end_payload["path"] == "/stats"
    assert end_payload["method"] == "GET"
    assert end_payload["status_code"] == 200
    assert end_payload["status"] == "ok"
    assert end_payload["trace_id"] == end_payload["request_id"]
    assert end_payload["event_type"] == "end"
    assert end_payload["span_name"] == "http.request"
    assert end_payload["kind"] == "server"
    assert end_payload["span_id"] == start_payload["span_id"]
    assert end_payload["duration_ms"] >= 0
    assert end_payload["elapsed_ms"] == end_payload["duration_ms"]
    assert end_payload["attributes"]["http.path"] == "/stats"
    assert stats_start_payload["parent_span_id"] == start_payload["span_id"]
    assert stats_start_payload["trace_id"] == start_payload["request_id"]


def test_http_request_exception_logs_error_and_terminal_end(tmp_path: Path):
    source_dir = tmp_path / "notes"
    source_dir.mkdir()
    (source_dir / "sample.md").write_text("# 标题\n\n接口测试内容。", encoding="utf-8")

    app = create_app(_build_config(tmp_path, source_dir))

    @app.get("/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError("boom")

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/boom")
        assert response.status_code == 500
    finally:
        handler.flush()
        root_logger.removeHandler(handler)
        handler.close()

    payloads = _parse_jsonl(stream)
    error_payload = next(
        payload
        for payload in payloads
        if payload.get("span_name") == "http.request" and payload.get("event") == "error"
    )
    end_payload = next(
        payload
        for payload in payloads
        if payload.get("span_name") == "http.request" and payload.get("event") == "end"
    )

    assert error_payload["message"] == "http.request.error"
    assert end_payload["message"] == "http.request.end"
    assert error_payload["status"] == "error"
    assert error_payload["error_type"] == "RuntimeError"
    assert error_payload["span_id"] == end_payload["span_id"]
    assert end_payload["status"] == "error"
    assert end_payload["status_code"] == 500
    assert end_payload["error_type"] == "RuntimeError"
