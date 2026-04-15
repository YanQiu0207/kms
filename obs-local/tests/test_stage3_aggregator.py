from __future__ import annotations

import importlib
import json
import sys
from functools import lru_cache
from pathlib import Path
from collections.abc import Mapping

import pytest

OBS_LOCAL_ROOT = Path(__file__).resolve().parents[1]
if str(OBS_LOCAL_ROOT) not in sys.path:
    sys.path.insert(0, str(OBS_LOCAL_ROOT))

from app.aggregator import AggregatedEvent, _is_error_event, _request_status
from app.parser import LogSourceContext, parse_log_line


SOURCE = LogSourceContext(
    project_id="sample-project",
    source_id="main",
    log_path="sample.log",
    timezone="Asia/Shanghai",
    service_hint="demo-api",
)

_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "requests": ("requests", "request_summaries", "request_items", "request_view", "request_list"),
    "errors": ("errors", "error_events", "error_summaries", "error_items", "error_view", "error_list"),
    "stages": ("stages", "stage_stats", "stage_items", "stage_view", "stage_list"),
}
_AGGREGATION_OPTIONS = {
    "top_n": 20,
    "request_stage_limit": 5,
}


def _payload(timestamp: str, event: str, **fields: object) -> dict[str, object]:
    payload: dict[str, object] = {"timestamp": timestamp, "event": event}
    payload.update(fields)
    return payload


def _record(payload: dict[str, object]):
    return parse_log_line(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), source=SOURCE)


def _records(payloads: list[dict[str, object]]):
    return [_record(payload) for payload in payloads]


@lru_cache(maxsize=1)
def _resolve_aggregate_callable():
    try:
        module = importlib.import_module("app.aggregator")
    except ModuleNotFoundError as exc:
        if exc.name == "app.aggregator":
            pytest.skip("app.aggregator is not available yet")
        raise

    for candidate_name in (
        "aggregate_records",
        "aggregate",
        "build_aggregation",
        "aggregate_log_records",
    ):
        candidate = getattr(module, candidate_name, None)
        if callable(candidate):
            return candidate

    for class_name in ("Aggregator", "LogAggregator", "RecordAggregator"):
        cls = getattr(module, class_name, None)
        if cls is None:
            continue
        try:
            instance = cls()
        except TypeError:
            continue
        for method_name in ("aggregate_records", "aggregate", "run", "process", "build"):
            method = getattr(instance, method_name, None)
            if callable(method):
                return method

    pytest.fail("app.aggregator does not expose a supported aggregate entry point")


def _aggregate(records):
    return _aggregate_with_options(records)


def _aggregate_with_options(records, **overrides):
    aggregate = _resolve_aggregate_callable()
    options = dict(_AGGREGATION_OPTIONS)
    options.update(overrides)
    attempts = (
        lambda: aggregate(records, **options),
        lambda: aggregate(records=records, **options),
        lambda: aggregate(tuple(records), **options),
        lambda: aggregate(records=tuple(records), **options),
    )
    last_error: Exception | None = None
    for attempt in attempts:
        try:
            return attempt()
        except TypeError as exc:
            last_error = exc
    raise AssertionError("failed to call aggregator with a reasonable records input") from last_error


def _section(result, section: str):
    aliases = _SECTION_ALIASES[section]

    if isinstance(result, tuple) and len(result) >= 3:
        index_map = {"requests": 0, "errors": 1, "stages": 2}
        return result[index_map[section]]

    if isinstance(result, Mapping):
        for alias in aliases:
            if alias in result:
                return result[alias]

    for alias in aliases:
        if hasattr(result, alias):
            return getattr(result, alias)

    raise AssertionError(f"could not find {section!r} in aggregator result")


def _entries(collection):
    if isinstance(collection, Mapping):
        return tuple(collection.items())
    if collection is None:
        return ()
    if isinstance(collection, (list, tuple)):
        return tuple((None, item) for item in collection)
    return ((None, collection),)


def _field(item, *names: str):
    if isinstance(item, Mapping):
        for name in names:
            if name in item and item[name] is not None:
                return item[name]
        return None

    for name in names:
        if hasattr(item, name):
            value = getattr(item, name)
            if value is not None:
                return value
    return None


def _entry_request_id(entry) -> object | None:
    key, item = entry
    value = _field(item, "request_id", "id")
    if value is None and key is not None:
        return key
    return value


def _entry_stage_name(entry) -> object | None:
    key, item = entry
    value = _field(item, "stage", "name", "span_name")
    if value is None and key is not None:
        return key
    return value


def _request_entries(result):
    return _entries(_section(result, "requests"))


def _error_entries(result):
    return _entries(_section(result, "errors"))


def _request_by_id(result, request_id: str):
    for entry in _request_entries(result):
        if _entry_request_id(entry) == request_id:
            return entry[1]
    raise AssertionError(f"request {request_id!r} not found")


def _request_ids(result) -> set[object | None]:
    return {_entry_request_id(entry) for entry in _request_entries(result)}


def _error_request_ids(result) -> set[object | None]:
    request_ids: set[object | None] = set()
    for key, item in _error_entries(result):
        value = _field(item, "request_id", "id")
        if value is None and isinstance(key, str) and key.startswith("req-"):
            value = key
        request_ids.add(value)
    return request_ids


def _top_stage_names(result, request_item=None) -> list[object]:
    top_stages = None
    if request_item is not None:
        top_stages = _field(request_item, "top_stages", "stages", "stage_stats")
    if top_stages is None:
        try:
            top_stages = _section(result, "stages")
        except AssertionError:
            top_stages = None
    return [name for name in (_entry_stage_name(entry) for entry in _entries(top_stages)) if name is not None]


def test_aggregate_separates_normal_failed_and_error_requests():
    records = _records(
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
                "2026-04-15T11:52:01.005+08:00",
                "query.plan.end",
                request_id="req-ok",
                span_id="span-root",
                duration_ms=30,
            ),
            _payload(
                "2026-04-15T11:52:01.010+08:00",
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
    )

    result = _aggregate(records)

    req_ok = _request_by_id(result, "req-ok")
    req_failed = _request_by_id(result, "req-failed")
    req_error = _request_by_id(result, "req-error")

    assert _field(req_ok, "summary") == "direct summary"
    assert _field(req_failed, "summary") == "summary from attributes"
    assert _field(req_error, "summary") == "error summary"

    assert _field(req_ok, "status_code") == 200
    assert _field(req_failed, "status_code") == 503

    status_ok = _field(req_ok, "status")
    status_failed = _field(req_failed, "status")
    status_error = _field(req_error, "status")
    if status_ok is not None:
        assert status_ok in {"ok", "success"}
    if status_failed is not None:
        assert status_failed != "ok"
    if status_error is not None:
        assert status_error != "ok"

    failed_flag_ok = _field(req_ok, "failed_request", "is_failed_request")
    failed_flag_failed = _field(req_failed, "failed_request", "is_failed_request")
    failed_flag_error = _field(req_error, "failed_request", "is_failed_request")
    if isinstance(failed_flag_ok, bool):
        assert failed_flag_ok is False
    if isinstance(failed_flag_failed, bool):
        assert failed_flag_failed is True
    if isinstance(failed_flag_error, bool):
        assert failed_flag_error is True

    request_ids = _request_ids(result)
    assert {"req-ok", "req-failed", "req-error"} <= request_ids

    error_ids = _error_request_ids(result)
    assert "req-failed" not in error_ids
    assert "req-error" not in error_ids
    assert None in error_ids

    error_entries = _error_entries(result)
    orphan_error = None
    for _, item in error_entries:
        if _field(item, "request_id", "id") is None:
            orphan_error = item
            break
    assert orphan_error is not None
    assert _field(orphan_error, "event") == "semantic.client_load.error"

    top_stage_names = _top_stage_names(result, req_ok)
    assert "query.plan.fetch" in top_stage_names
    if "query.plan" in top_stage_names:
        assert top_stage_names.index("query.plan.fetch") < top_stage_names.index("query.plan")


def test_aggregate_marks_error_without_terminal_as_failed_not_partial():
    records = _records(
        [
            _payload(
                "2026-04-15T11:53:01.000+08:00",
                "http.request.start",
                request_id="req-no-terminal-error",
                method="POST",
                path="/ask",
                summary="missing terminal",
            ),
            _payload(
                "2026-04-15T11:53:01.020+08:00",
                "query.ask.error",
                request_id="req-no-terminal-error",
                level="ERROR",
                status="error",
                error_type="RuntimeError",
                exception="query exploded",
            ),
        ]
    )

    result = _aggregate(records)
    request_item = _request_by_id(result, "req-no-terminal-error")

    assert _field(request_item, "status") in {"failed", "error"}
    partial_flag = _field(request_item, "partial")
    if isinstance(partial_flag, bool):
        assert partial_flag is False


def test_error_detection_and_request_status_precedence_cover_combined_paths():
    request_error_record = _record(
        _payload(
            "2026-04-15T11:53:02.000+08:00",
            "http.request.error",
            request_id="req-error",
            level="ERROR",
            status="error",
            error_type="TimeoutError",
        )
    )
    request_end_record = _record(
        _payload(
            "2026-04-15T11:53:03.000+08:00",
            "http.request.end",
            request_id="req-end",
            status="error",
        )
    )
    stage_error_record = _record(
        _payload(
            "2026-04-15T11:53:04.000+08:00",
            "query.plan.end",
            request_id="req-stage",
            status="error",
        )
    )

    assert _is_error_event(request_error_record) is False
    assert _is_error_event(request_end_record) is False
    assert _is_error_event(stage_error_record) is True

    error_terminal = AggregatedEvent(
        project_id="sample-project",
        source_id="main",
        request_id="req-error",
        timestamp=None,
        line_number=None,
        event="http.request.error",
        event_type="error",
        stage=None,
        service=None,
        logger=None,
        level="ERROR",
        status="error",
        status_code=500,
        duration_ms=30.0,
        self_duration_ms=None,
        summary=None,
        error_type="TimeoutError",
        exception="boom",
        method="POST",
        path="/ask",
        span_id=None,
        parent_span_id=None,
        is_request_terminal=True,
    )
    status_error_terminal = AggregatedEvent(
        project_id="sample-project",
        source_id="main",
        request_id="req-status-error",
        timestamp=None,
        line_number=None,
        event="http.request.end",
        event_type="end",
        stage=None,
        service=None,
        logger=None,
        level="INFO",
        status="error",
        status_code=200,
        duration_ms=20.0,
        self_duration_ms=None,
        summary=None,
        error_type=None,
        exception=None,
        method="POST",
        path="/ask",
        span_id=None,
        parent_span_id=None,
        is_request_terminal=True,
    )

    assert _request_status(
        terminal_event=error_terminal,
        status_code=500,
        partial=True,
        has_error_event=False,
    ) == "failed"
    assert _request_status(
        terminal_event=None,
        status_code=None,
        partial=True,
        has_error_event=True,
    ) == "failed"
    assert _request_status(
        terminal_event=status_error_terminal,
        status_code=200,
        partial=False,
        has_error_event=False,
    ) == "failed"
    assert _request_status(
        terminal_event=None,
        status_code=None,
        partial=True,
        has_error_event=False,
    ) == "partial"


def test_build_request_detail_targets_single_request():
    aggregator = importlib.import_module("app.aggregator")
    build_detail = getattr(aggregator, "build_request_detail", None)
    if not callable(build_detail):
        pytest.skip("build_request_detail is not available")

    records = _records(
        [
            _payload(
                "2026-04-15T11:54:01.000+08:00",
                "http.request.start",
                request_id="req-a",
                method="POST",
                path="/ask",
                summary="alpha",
            ),
            _payload(
                "2026-04-15T11:54:01.030+08:00",
                "http.request.end",
                request_id="req-a",
                status_code=200,
                duration_ms=30,
            ),
            _payload(
                "2026-04-15T11:54:02.000+08:00",
                "http.request.start",
                request_id="req-b",
                method="POST",
                path="/search",
                summary="beta",
            ),
            _payload(
                "2026-04-15T11:54:02.040+08:00",
                "http.request.end",
                request_id="req-b",
                status_code=200,
                duration_ms=40,
            ),
        ]
    )

    detail = build_detail(records, "req-a", request_stage_limit=_AGGREGATION_OPTIONS["request_stage_limit"])
    assert detail is not None
    detail_summary = _field(detail, "summary")
    assert detail_summary is not None
    assert _field(detail_summary, "request_id") == "req-a"
    timeline = _field(detail, "timeline")
    assert timeline is not None
    timeline_request_ids = {_field(item, "request_id") for _, item in _entries(timeline)}
    assert timeline_request_ids == {"req-a"}


def test_request_type_falls_back_to_semantic_path_segment():
    records = _records(
        [
            _payload(
                "2026-04-15T11:55:01.000+08:00",
                "http.request.start",
                request_id="req-path-type",
                method="POST",
                path="/api/ask?mode=fast",
                summary="gamma",
            ),
            _payload(
                "2026-04-15T11:55:01.030+08:00",
                "http.request.end",
                request_id="req-path-type",
                status_code=200,
                duration_ms=30,
            ),
        ]
    )

    result = _aggregate(records)
    request_item = _request_by_id(result, "req-path-type")
    assert _field(request_item, "request_type") == "ask"


def test_aggregate_marks_partial_requests_in_request_view():
    records = _records(
        [
            _payload(
                "2026-04-15T11:52:04.000+08:00",
                "http.request.start",
                request_id="req-partial",
                method="POST",
                path="/verify",
                summary="partial summary",
            ),
            _payload(
                "2026-04-15T11:52:04.005+08:00",
                "pipeline.partial.end",
                request_id="req-partial",
                span_id="partial-span",
                duration_ms=5,
            ),
        ]
    )

    result = _aggregate(records)
    req_partial = _request_by_id(result, "req-partial")

    partial_flag = _field(req_partial, "partial")
    if isinstance(partial_flag, bool):
        assert partial_flag is True
    else:
        assert partial_flag in {True, 1, "true", "True"}

    assert _field(req_partial, "summary") == "partial summary"
    assert "req-partial" in _request_ids(result)


def test_aggregate_uses_leaf_or_self_duration_for_top_stage_ranking():
    records = _records(
        [
            _payload(
                "2026-04-15T11:52:05.000+08:00",
                "http.request.start",
                request_id="req-stages",
                method="POST",
                path="/ask",
                summary="stage summary",
            ),
            _payload(
                "2026-04-15T11:52:05.010+08:00",
                "pipeline.parent.end",
                request_id="req-stages",
                span_id="span-parent",
                duration_ms=30,
            ),
            _payload(
                "2026-04-15T11:52:05.020+08:00",
                "pipeline.parent.child.end",
                request_id="req-stages",
                span_id="span-child",
                parent_span_id="span-parent",
                duration_ms=20,
            ),
            _payload(
                "2026-04-15T11:52:05.040+08:00",
                "http.request.end",
                request_id="req-stages",
                status_code=200,
                duration_ms=40,
            ),
        ]
    )

    result = _aggregate(records)
    req_stages = _request_by_id(result, "req-stages")
    top_stage_names = _top_stage_names(result, req_stages)

    assert "pipeline.parent.child" in top_stage_names
    if "pipeline.parent" in top_stage_names:
        assert top_stage_names.index("pipeline.parent.child") < top_stage_names.index("pipeline.parent")


def test_aggregate_supports_canonical_span_protocol_and_trace_id_fallback():
    records = _records(
        [
            _payload(
                "2026-04-15T11:56:01.000+08:00",
                "start",
                span_name="http.request",
                trace_id="trace-canonical",
                span_id="span-root",
                kind="server",
                method="POST",
                path="/api/ask",
            ),
            _payload(
                "2026-04-15T11:56:01.005+08:00",
                "start",
                span_name="api.ask",
                trace_id="trace-canonical",
                span_id="span-ask",
                parent_span_id="span-root",
                question="canonical summary",
            ),
            _payload(
                "2026-04-15T11:56:01.025+08:00",
                "end",
                span_name="api.ask",
                trace_id="trace-canonical",
                span_id="span-ask",
                parent_span_id="span-root",
                duration_ms=20,
                status="ok",
            ),
            _payload(
                "2026-04-15T11:56:01.040+08:00",
                "end",
                span_name="http.request",
                trace_id="trace-canonical",
                span_id="span-root",
                kind="server",
                status="ok",
                status_code=200,
                duration_ms=40,
            ),
        ]
    )

    result = _aggregate_with_options(
        records,
        summary_mapping_by_project={"sample-project": {"api.ask.start": "question"}},
    )

    request_item = _request_by_id(result, "trace-canonical")

    assert _field(request_item, "summary") == "canonical summary"
    assert _field(request_item, "request_type") == "ask"
    assert _field(request_item, "status") == "ok"
    assert _field(request_item, "status_code") == 200
    assert _field(request_item, "duration_ms") == 40

    top_stage_names = _top_stage_names(result, request_item)
    assert "api.ask" in top_stage_names
    assert "http.request" not in top_stage_names


def test_aggregate_treats_canonical_request_error_as_terminal_failed_request():
    records = _records(
        [
            _payload(
                "2026-04-15T11:57:01.000+08:00",
                "start",
                span_name="http.request",
                trace_id="trace-error",
                span_id="span-root",
                kind="server",
                method="POST",
                path="/api/ask",
                summary="canonical error",
            ),
            _payload(
                "2026-04-15T11:57:01.030+08:00",
                "error",
                span_name="http.request",
                trace_id="trace-error",
                span_id="span-root",
                kind="server",
                status="error",
                error_type="TimeoutError",
                exception="request timed out",
                duration_ms=30,
            ),
        ]
    )

    result = _aggregate(records)
    request_item = _request_by_id(result, "trace-error")

    assert _field(request_item, "status") in {"failed", "error"}
    partial_flag = _field(request_item, "partial")
    if isinstance(partial_flag, bool):
        assert partial_flag is False
