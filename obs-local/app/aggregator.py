from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Any, Iterable, Mapping

from .parser import ParsedLogRecord

_REQUEST_START_EVENT = "http.request.start"
_REQUEST_END_EVENT = "http.request.end"
_REQUEST_ERROR_EVENT = "http.request.error"
_REQUEST_TERMINAL_EVENTS = {_REQUEST_END_EVENT, _REQUEST_ERROR_EVENT}
_EVENT_SUFFIXES = (".start", ".end", ".error")
_GENERIC_SUMMARY_FIELDS = (
    "summary",
    "display_summary",
    "message",
    "title",
    "name",
    "operation",
)
_REQUEST_EVENT_TYPES = {"start", "end", "error"}


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    else:
        text = str(value).strip()
    return text or None


def _event_type_marker(value: str | None) -> str | None:
    text = _clean_text(value)
    if text in {"start", "end", "error", "event"}:
        return text
    return None


def _request_span_name(value: str | None) -> bool:
    return _clean_text(value) == "http.request"


def _canonical_event_name(
    *,
    event: str | None,
    span_name: str | None,
    event_type: str | None,
) -> str | None:
    cleaned_event = _clean_text(event)
    cleaned_span_name = _clean_text(span_name)
    cleaned_event_type = _event_type_marker(event_type)

    if cleaned_event and cleaned_event not in {"start", "end", "error", "event"}:
        return cleaned_event
    if cleaned_span_name and cleaned_event_type in _REQUEST_EVENT_TYPES:
        return f"{cleaned_span_name}.{cleaned_event_type}"
    if cleaned_span_name and cleaned_event_type == "event":
        return cleaned_span_name
    return cleaned_event or cleaned_span_name


def _is_request_event(record: ParsedLogRecord) -> bool:
    event = _canonical_event_name(
        event=record.event,
        span_name=record.span_name,
        event_type=record.event_type,
    )
    if event and event.startswith("http.request."):
        return True
    return _request_span_name(record.span_name) and _event_type_marker(record.event_type) in _REQUEST_EVENT_TYPES


def _is_request_start(record: ParsedLogRecord) -> bool:
    if _clean_text(record.event) == _REQUEST_START_EVENT:
        return True
    return _request_span_name(record.span_name) and _event_type_marker(record.event_type) == "start"


def _is_request_terminal(record: ParsedLogRecord) -> bool:
    if _clean_text(record.event) in _REQUEST_TERMINAL_EVENTS:
        return True
    return _request_span_name(record.span_name) and _event_type_marker(record.event_type) in {"end", "error"}


def _is_error_event(record: ParsedLogRecord) -> bool:
    event = _canonical_event_name(
        event=record.event,
        span_name=record.span_name,
        event_type=record.event_type,
    )
    event_type = _clean_text(record.event_type)
    if event == _REQUEST_ERROR_EVENT or (_request_span_name(record.span_name) and event_type == "error"):
        return False
    level = _clean_text(record.level)
    status = _clean_text(record.status)
    if level == "ERROR" or record.exception or record.error_type:
        return True
    if event_type == "error":
        return True
    if status == "error" and event not in {_REQUEST_START_EVENT, _REQUEST_END_EVENT}:
        return True
    return False


def _normalize_stage_name(record: ParsedLogRecord) -> str | None:
    span_name = _clean_text(record.span_name)
    if span_name is not None:
        if _is_request_event(record):
            return None
        return span_name

    event = _clean_text(record.event)
    if event:
        if event.startswith("http.request."):
            return None
        for suffix in _EVENT_SUFFIXES:
            if event.endswith(suffix):
                return event[: -len(suffix)]
        return event
    return _clean_text(record.span_name)


def _format_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone().isoformat(timespec="milliseconds")


def _serialize_value(value: Any) -> Any:
    if is_dataclass(value):
        return {
            field.name: _serialize_value(getattr(value, field.name))
            for field in fields(value)
            if not field.name.startswith("_")
        }
    if isinstance(value, datetime):
        return _format_dt(value)
    if isinstance(value, Mapping):
        return {str(key): _serialize_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_serialize_value(item) for item in value]
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    return value


def _lookup_text(record: ParsedLogRecord, field_name: str) -> str | None:
    value = getattr(record, field_name, None)
    text = _clean_text(value)
    if text is not None:
        return text

    if field_name in record.raw:
        text = _clean_text(record.raw[field_name])
        if text is not None:
            return text

    attributes = record.raw.get("attributes")
    if isinstance(attributes, Mapping) and field_name in attributes:
        text = _clean_text(attributes[field_name])
        if text is not None:
            return text

    if field_name in record.attributes:
        text = _clean_text(record.attributes[field_name])
        if text is not None:
            return text

    return None


def _resolve_summary(
    record: ParsedLogRecord,
    *,
    event_summary_mapping: Mapping[str, str] | None = None,
) -> str | None:
    event = _clean_text(record.event)
    span_name = _clean_text(record.span_name)
    canonical_event = _canonical_event_name(
        event=record.event,
        span_name=record.span_name,
        event_type=record.event_type,
    )
    if event_summary_mapping:
        for mapping_key in (event, canonical_event, span_name):
            if mapping_key is None:
                continue
            mapped_field = _clean_text(event_summary_mapping.get(mapping_key))
            if mapped_field:
                mapped_value = _lookup_text(record, mapped_field)
                if mapped_value is not None:
                    return mapped_value

    for field_name in _GENERIC_SUMMARY_FIELDS:
        value = _lookup_text(record, field_name)
        if value is not None:
            return value
    return None


def _resolve_error_message(record: ParsedLogRecord) -> str | None:
    for field_name in ("summary", "display_summary", "message", "exception", "error_type", "name", "operation"):
        value = _lookup_text(record, field_name)
        if value is not None:
            return value
    event = _canonical_event_name(
        event=record.event,
        span_name=record.span_name,
        event_type=record.event_type,
    )
    if event is not None:
        return event
    return None


def _resolve_error_detail(record: ParsedLogRecord) -> str | None:
    for field_name in ("exception", "summary", "display_summary", "message", "error_type"):
        value = _lookup_text(record, field_name)
        if value is not None:
            return value
    event = _canonical_event_name(
        event=record.event,
        span_name=record.span_name,
        event_type=record.event_type,
    )
    if event is not None:
        return event
    return None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = percentile * (len(ordered) - 1)
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    if lower_index == upper_index:
        return ordered[lower_index]
    fraction = rank - lower_index
    return ordered[lower_index] * (1.0 - fraction) + ordered[upper_index] * fraction


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _record_sort_key(item: tuple[int, ParsedLogRecord]) -> tuple[bool, datetime, int, int]:
    index, record = item
    timestamp = record.timestamp or datetime.max.replace(tzinfo=timezone.utc)
    line_number = record.line_number if record.line_number is not None else 10**9
    return (record.timestamp is None, timestamp, line_number, index)


def _request_key(record: ParsedLogRecord) -> tuple[str | None, str] | None:
    request_id = _clean_text(record.request_id)
    if request_id is None:
        return None
    return _clean_text(record.project_id), request_id


def _project_summary_mapping(
    summary_mapping_by_project: Mapping[str, Mapping[str, str]] | None,
    project_id: str | None,
) -> Mapping[str, str]:
    if not summary_mapping_by_project:
        return {}
    if project_id is not None:
        mapping = summary_mapping_by_project.get(project_id)
        if mapping is not None:
            return mapping
    for fallback_key in ("*", "default"):
        mapping = summary_mapping_by_project.get(fallback_key)
        if mapping is not None:
            return mapping
    return {}


@dataclass(slots=True)
class AggregatedEvent:
    project_id: str | None
    source_id: str | None
    request_id: str | None
    timestamp: datetime | None
    line_number: int | None
    event: str | None
    event_type: str | None
    stage: str | None
    service: str | None
    logger: str | None
    level: str | None
    status: str | None
    status_code: int | None
    duration_ms: float | None
    self_duration_ms: float | None
    summary: str | None
    error_type: str | None
    exception: str | None
    method: str | None
    path: str | None
    span_id: str | None
    parent_span_id: str | None
    is_request_start: bool = False
    is_request_terminal: bool = False
    is_error_event: bool = False
    is_leaf: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(self)


@dataclass(slots=True)
class ErrorSummary:
    project_id: str | None
    source_id: str | None
    request_id: str | None
    timestamp: datetime | None
    event: str | None
    summary: str | None
    message: str | None
    detail: str | None
    path: str | None
    method: str | None
    error_type: str | None
    level: str | None
    status: str | None
    status_code: int | None
    line_number: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(self)


@dataclass(slots=True)
class StageStat:
    project_id: str | None
    stage: str
    count: int
    error_count: int
    avg_ms: float | None
    p95_ms: float | None
    max_ms: float | None
    last_seen_at: datetime | None
    leaf_count: int = 0
    self_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(self)


@dataclass(slots=True)
class StageTiming:
    stage: str
    duration_ms: float
    self_duration_ms: float | None = None
    event: str | None = None
    status: str | None = None
    timestamp: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(self)


@dataclass(slots=True)
class RequestSummary:
    project_id: str | None
    request_id: str
    request_type: str | None
    started_at: datetime | None
    ended_at: datetime | None
    method: str | None
    path: str | None
    status_code: int | None
    status: str | None
    duration_ms: float | None
    summary: str | None
    top_stages: tuple[StageTiming, ...] = ()
    error_count: int = 0
    failed_request: bool = False
    last_event_at: datetime | None = None
    partial: bool = False
    source_ids: tuple[str, ...] = ()
    event_count: int = 0
    stage_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(self)


@dataclass(slots=True)
class RequestDetail:
    summary: RequestSummary
    timeline: tuple[AggregatedEvent, ...] = ()
    stages: tuple[StageTiming, ...] = ()
    errors: tuple[ErrorSummary, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(self)


@dataclass(slots=True)
class AggregationOverview:
    scope_project_id: str | None
    generated_at: datetime
    first_event_at: datetime | None
    last_event_at: datetime | None
    request_count: int
    failed_request_count: int
    partial_request_count: int
    error_count: int
    stage_count: int
    top_requests: tuple[RequestSummary, ...] = ()
    top_errors: tuple[ErrorSummary, ...] = ()
    top_stages: tuple[StageStat, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(self)


@dataclass(slots=True)
class AggregationResult:
    overview: AggregationOverview
    requests: tuple[RequestSummary, ...]
    errors: tuple[ErrorSummary, ...]
    stages: tuple[StageStat, ...]
    request_details: tuple[RequestDetail, ...]
    _request_index: dict[tuple[str | None, str], RequestDetail] = field(default_factory=dict, repr=False)

    def find_request_detail(self, request_id: str, *, project_id: str | None = None) -> RequestDetail | None:
        key = _normalize_request_lookup_key(project_id, request_id)
        if key is not None:
            detail = self._request_index.get(key)
            if detail is not None:
                return detail

        matches = [detail for detail in self.request_details if detail.summary.request_id == request_id]
        if len(matches) == 1:
            return matches[0]
        return None

    def find_request_summary(self, request_id: str, *, project_id: str | None = None) -> RequestSummary | None:
        detail = self.find_request_detail(request_id, project_id=project_id)
        return detail.summary if detail is not None else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "overview": self.overview.to_dict(),
            "requests": [item.to_dict() for item in self.requests],
            "errors": [item.to_dict() for item in self.errors],
            "stages": [item.to_dict() for item in self.stages],
            "request_details": [item.to_dict() for item in self.request_details],
        }


@dataclass(slots=True)
class _RequestGroup:
    project_id: str | None
    request_id: str
    records: list[tuple[int, ParsedLogRecord]] = field(default_factory=list)


def _normalize_request_lookup_key(project_id: str | None, request_id: str) -> tuple[str | None, str] | None:
    cleaned_request_id = _clean_text(request_id)
    if cleaned_request_id is None:
        return None
    return _clean_text(project_id), cleaned_request_id


def _normalize_request_type_from_path(path: str | None) -> str | None:
    text = _clean_text(path)
    if text is None:
        return None
    parsed = urlparse(text)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        return None
    return segments[-1]


def _build_event_entry(
    record: ParsedLogRecord,
    *,
    self_duration_ms: float | None = None,
    is_leaf: bool = True,
) -> AggregatedEvent:
    normalized_event = _canonical_event_name(
        event=record.event,
        span_name=record.span_name,
        event_type=record.event_type,
    )
    return AggregatedEvent(
        project_id=_clean_text(record.project_id),
        source_id=_clean_text(record.source_id),
        request_id=_clean_text(record.request_id),
        timestamp=record.timestamp,
        line_number=record.line_number,
        event=normalized_event,
        event_type=_clean_text(record.event_type),
        stage=_normalize_stage_name(record),
        service=_clean_text(record.service),
        logger=_clean_text(record.logger),
        level=_clean_text(record.level),
        status=_clean_text(record.status),
        status_code=record.status_code,
        duration_ms=record.duration_ms,
        self_duration_ms=self_duration_ms,
        summary=_clean_text(record.summary),
        error_type=_clean_text(record.error_type),
        exception=_clean_text(record.exception),
        method=_clean_text(record.method),
        path=_clean_text(record.path),
        span_id=_clean_text(record.span_id),
        parent_span_id=_clean_text(record.parent_span_id),
        is_request_start=_is_request_start(record),
        is_request_terminal=_is_request_terminal(record),
        is_error_event=_is_error_event(record),
        is_leaf=is_leaf,
    )


def _build_error_summary(record: ParsedLogRecord) -> ErrorSummary:
    message = _resolve_error_message(record)
    detail = _resolve_error_detail(record)
    summary = _resolve_summary(record)
    normalized_event = _canonical_event_name(
        event=record.event,
        span_name=record.span_name,
        event_type=record.event_type,
    )
    return ErrorSummary(
        project_id=_clean_text(record.project_id),
        source_id=_clean_text(record.source_id),
        request_id=_clean_text(record.request_id),
        timestamp=record.timestamp,
        event=normalized_event,
        summary=summary,
        message=message,
        detail=detail,
        path=_clean_text(record.path),
        method=_clean_text(record.method),
        error_type=_clean_text(record.error_type),
        level=_clean_text(record.level),
        status=_clean_text(record.status),
        status_code=record.status_code,
        line_number=record.line_number,
    )


def _build_invalid_record_error(record: ParsedLogRecord) -> ErrorSummary:
    message = _clean_text(record.parse_error) or "invalid log record"
    return ErrorSummary(
        project_id=_clean_text(record.project_id),
        source_id=_clean_text(record.source_id),
        request_id=_clean_text(record.request_id),
        timestamp=record.timestamp,
        event="parse_error",
        summary=None,
        message=message,
        detail=message,
        path=_clean_text(record.log_path),
        method=None,
        error_type="ParseError",
        level="ERROR",
        status="error",
        status_code=None,
        line_number=record.line_number,
    )


def _request_duration(
    *,
    start_event: AggregatedEvent | None,
    terminal_event: AggregatedEvent | None,
    first_seen: datetime | None,
    last_seen: datetime | None,
) -> float | None:
    if start_event is not None and terminal_event is not None:
        if terminal_event.duration_ms is not None:
            return terminal_event.duration_ms
        if start_event.timestamp is not None and terminal_event.timestamp is not None:
            delta = terminal_event.timestamp - start_event.timestamp
            return max(delta.total_seconds() * 1000.0, 0.0)
    if first_seen is not None and last_seen is not None and last_seen >= first_seen:
        delta = last_seen - first_seen
        return max(delta.total_seconds() * 1000.0, 0.0)
    return None


def _request_status(
    *,
    terminal_event: AggregatedEvent | None,
    status_code: int | None,
    partial: bool,
    has_error_event: bool,
) -> str | None:
    if terminal_event is not None and terminal_event.is_request_terminal and terminal_event.event_type == "error":
        return "failed"
    if status_code is not None and status_code >= 400:
        return "failed"
    if has_error_event:
        return "failed"
    if partial:
        return "partial"
    if terminal_event is not None and terminal_event.status == "error":
        return "failed"
    return "ok"


def _resolve_status_code(events: list[AggregatedEvent]) -> int | None:
    for event in reversed(events):
        if event.status_code is not None:
            return event.status_code
    return None


def _collect_request_stage_events(events: list[AggregatedEvent]) -> list[AggregatedEvent]:
    stage_events = [event for event in events if event.stage is not None and event.duration_ms is not None]
    if not stage_events:
        return []

    span_index: dict[str, AggregatedEvent] = {}
    children_by_span: dict[str, list[AggregatedEvent]] = defaultdict(list)
    for event in stage_events:
        if event.span_id:
            if event.span_id not in span_index:
                span_index[event.span_id] = event
        if event.span_id and event.parent_span_id:
            children_by_span[event.parent_span_id].append(event)

    enriched: list[AggregatedEvent] = []
    for event in stage_events:
        is_leaf = True
        self_duration = event.duration_ms
        if event.span_id and event.span_id in children_by_span:
            children = children_by_span[event.span_id]
            is_leaf = False
            child_total = sum(child.duration_ms or 0.0 for child in children)
            if event.duration_ms is not None:
                self_duration = max(event.duration_ms - child_total, 0.0)
        enriched.append(
            _build_event_entry(
                ParsedLogRecord(
                    project_id=event.project_id,
                    source_id=event.source_id,
                    log_path=None,
                    source_timezone=None,
                    line_number=event.line_number,
                    raw_text=None,
                    raw={},
                    valid=True,
                    parse_error=None,
                    warnings=(),
                    timestamp=event.timestamp,
                    timestamp_raw=None,
                    timestamp_format=None,
                    schema_version=None,
                    service=event.service,
                    logger=event.logger,
                    level=event.level,
                    event=event.event,
                    event_type=event.event_type,
                    span_name=event.stage,
                    span_id=event.span_id,
                    parent_span_id=event.parent_span_id,
                    trace_id=None,
                    request_id=event.request_id,
                    kind=None,
                    status=event.status,
                    status_code=event.status_code,
                    duration_ms=event.duration_ms,
                    error_type=event.error_type,
                    exception=event.exception,
                    method=event.method,
                    path=event.path,
                    summary=event.summary,
                    attributes={},
                ),
                self_duration_ms=self_duration,
                is_leaf=is_leaf,
            )
        )
    enriched.sort(
        key=lambda item: (
            -(item.self_duration_ms or item.duration_ms or 0.0),
            item.timestamp or datetime.max.replace(tzinfo=timezone.utc),
            item.line_number if item.line_number is not None else 10**9,
        )
    )
    return enriched


def _to_stage_timing(event: AggregatedEvent) -> StageTiming:
    return StageTiming(
        stage=event.stage or "unknown",
        duration_ms=event.duration_ms or 0.0,
        self_duration_ms=event.self_duration_ms,
        event=event.event,
        status=event.status,
        timestamp=event.timestamp,
    )


def _build_request_summary(
    group: _RequestGroup,
    *,
    summary_mapping_by_project: Mapping[str, Mapping[str, str]] | None,
    request_stage_limit: int,
) -> tuple[RequestSummary, RequestDetail, list[AggregatedEvent], list[ErrorSummary]]:
    sorted_records = sorted(group.records, key=_record_sort_key)
    project_summary_mapping = _project_summary_mapping(summary_mapping_by_project, group.project_id)

    timeline: list[AggregatedEvent] = []
    errors: list[ErrorSummary] = []
    summary: str | None = None
    start_event: AggregatedEvent | None = None
    terminal_events: list[AggregatedEvent] = []
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    source_ids: set[str] = set()

    for _, record in sorted_records:
        event_entry = _build_event_entry(record)
        timeline.append(event_entry)

        if event_entry.source_id:
            source_ids.add(event_entry.source_id)
        if event_entry.timestamp is not None:
            if first_seen is None or event_entry.timestamp < first_seen:
                first_seen = event_entry.timestamp
            if last_seen is None or event_entry.timestamp > last_seen:
                last_seen = event_entry.timestamp

        if summary is None:
            summary = _resolve_summary(record, event_summary_mapping=project_summary_mapping)

        if event_entry.is_request_start and start_event is None:
            start_event = event_entry
        if event_entry.is_request_terminal:
            terminal_events.append(event_entry)
        if event_entry.is_error_event:
            errors.append(_build_error_summary(record))

    terminal_event = terminal_events[-1] if terminal_events else None
    partial = start_event is None or (terminal_event is None and not errors)

    started_at = start_event.timestamp if start_event and start_event.timestamp is not None else first_seen
    ended_at = terminal_event.timestamp if terminal_event and terminal_event.timestamp is not None else last_seen
    status_code = _resolve_status_code(list(reversed(timeline)))
    status = _request_status(
        terminal_event=terminal_event,
        status_code=status_code,
        partial=partial,
        has_error_event=bool(errors),
    )
    failed_request = status == "failed"
    duration_ms = _request_duration(
        start_event=start_event,
        terminal_event=terminal_event,
        first_seen=first_seen,
        last_seen=last_seen,
    )
    request_type = None
    for event in timeline:
        event_name = _clean_text(event.stage) or _clean_text(event.event)
        if event_name and event_name.startswith("api."):
            parts = event_name.split(".")
            if len(parts) >= 2:
                request_type = parts[1]
                break
    if request_type is None:
        request_path = next((event.path for event in timeline if event.path is not None), None)
        request_type = _normalize_request_type_from_path(request_path)

    stage_events = _collect_request_stage_events(timeline)
    top_stages = tuple(_to_stage_timing(event) for event in stage_events[: max(0, int(request_stage_limit))])

    summary_record = RequestSummary(
        project_id=group.project_id,
        request_id=group.request_id,
        request_type=request_type,
        started_at=started_at,
        ended_at=ended_at,
        method=next((event.method for event in timeline if event.method is not None), None),
        path=next((event.path for event in timeline if event.path is not None), None),
        status_code=status_code,
        status=status,
        duration_ms=duration_ms,
        summary=summary,
        top_stages=top_stages,
        error_count=len(errors),
        failed_request=failed_request,
        last_event_at=last_seen,
        partial=partial,
        source_ids=tuple(sorted(source_ids)),
        event_count=len(timeline),
        stage_count=len(stage_events),
    )
    detail = RequestDetail(
        summary=summary_record,
        timeline=tuple(timeline),
        stages=tuple(_to_stage_timing(event) for event in stage_events),
        errors=tuple(errors),
    )
    return summary_record, detail, stage_events, errors


def _build_stage_stats(
    stage_events: Iterable[AggregatedEvent],
    *,
    project_id: str | None = None,
) -> tuple[StageStat, ...]:
    by_stage: dict[tuple[str | None, str], list[AggregatedEvent]] = defaultdict(list)
    for event in stage_events:
        if event.stage is None or event.duration_ms is None:
            continue
        by_stage[(event.project_id, event.stage)].append(event)

    stats: list[StageStat] = []
    for (event_project_id, stage_name), items in by_stage.items():
        durations = [event.self_duration_ms if event.self_duration_ms is not None else event.duration_ms for event in items]
        durations = [float(value) for value in durations if value is not None]
        if not durations:
            continue
        error_count = sum(1 for event in items if event.is_error_event)
        leaf_count = sum(1 for event in items if event.is_leaf)
        self_count = len(items) - leaf_count
        last_seen = max((event.timestamp for event in items if event.timestamp is not None), default=None)
        stats.append(
            StageStat(
                project_id=project_id if project_id is not None else event_project_id,
                stage=stage_name,
                count=len(items),
                error_count=error_count,
                avg_ms=_average(durations),
                p95_ms=_percentile(durations, 0.95),
                max_ms=max(durations) if durations else None,
                last_seen_at=last_seen,
                leaf_count=leaf_count,
                self_count=self_count,
            )
        )

    stats.sort(
        key=lambda item: (
            -(item.p95_ms or item.avg_ms or 0.0),
            item.stage,
        )
    )
    return tuple(stats)


def aggregate_records(
    records: Iterable[ParsedLogRecord],
    *,
    project_id: str | None = None,
    summary_mapping_by_project: Mapping[str, Mapping[str, str]] | None = None,
    top_n: int,
    request_stage_limit: int,
) -> AggregationResult:
    indexed_records = list(enumerate(records))
    if project_id is not None:
        indexed_records = [
            item
            for item in indexed_records
            if _clean_text(item[1].project_id) == _clean_text(project_id)
        ]

    request_groups: dict[tuple[str | None, str], _RequestGroup] = {}
    request_details: list[RequestDetail] = []
    request_summaries: list[RequestSummary] = []
    request_stage_events: list[AggregatedEvent] = []
    errors: list[ErrorSummary] = []
    system_error_records: list[ErrorSummary] = []
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None

    for index, record in sorted(indexed_records, key=_record_sort_key):
        if record.timestamp is not None:
            if first_event_at is None or record.timestamp < first_event_at:
                first_event_at = record.timestamp
            if last_event_at is None or record.timestamp > last_event_at:
                last_event_at = record.timestamp

        if not record.valid:
            system_error_records.append(_build_invalid_record_error(record))
            continue

        key = _request_key(record)
        if key is None:
            if _is_error_event(record):
                system_error_records.append(_build_error_summary(record))
            continue

        group = request_groups.get(key)
        if group is None:
            group = _RequestGroup(project_id=key[0], request_id=key[1])
            request_groups[key] = group
        group.records.append((index, record))

    for key in sorted(request_groups):
        group = request_groups[key]
        summary, detail, stage_events, request_errors = _build_request_summary(
            group,
            summary_mapping_by_project=summary_mapping_by_project,
            request_stage_limit=request_stage_limit,
        )
        request_summaries.append(summary)
        request_details.append(detail)
        request_stage_events.extend(stage_events)
        errors.extend(request_errors)

    errors.extend(system_error_records)
    stage_stats = _build_stage_stats(request_stage_events, project_id=project_id)
    request_summaries.sort(
        key=lambda item: (
            item.last_event_at or datetime.min.replace(tzinfo=timezone.utc),
            item.started_at or datetime.min.replace(tzinfo=timezone.utc),
            item.request_id,
        ),
        reverse=True,
    )
    request_details.sort(
        key=lambda item: (
            item.summary.last_event_at or datetime.min.replace(tzinfo=timezone.utc),
            item.summary.started_at or datetime.min.replace(tzinfo=timezone.utc),
            item.summary.request_id,
        ),
        reverse=True,
    )
    errors.sort(
        key=lambda item: (
            item.timestamp or datetime.min.replace(tzinfo=timezone.utc),
            item.project_id or "",
            item.request_id or "",
            item.line_number if item.line_number is not None else 10**9,
        ),
        reverse=True,
    )

    overview = AggregationOverview(
        scope_project_id=project_id,
        generated_at=datetime.now(timezone.utc),
        first_event_at=first_event_at,
        last_event_at=last_event_at,
        request_count=len(request_summaries),
        failed_request_count=sum(
            1
            for summary in request_summaries
            if summary.failed_request or summary.status == "failed" or (summary.status_code is not None and summary.status_code >= 400)
        ),
        partial_request_count=sum(1 for summary in request_summaries if summary.partial),
        error_count=len(errors),
        stage_count=len(stage_stats),
        top_requests=tuple(request_summaries[: max(0, int(top_n))]),
        top_errors=tuple(errors[: max(0, int(top_n))]),
        top_stages=stage_stats[: max(0, int(top_n))],
    )

    request_index = {
        _normalize_request_lookup_key(detail.summary.project_id, detail.summary.request_id): detail
        for detail in request_details
        if _normalize_request_lookup_key(detail.summary.project_id, detail.summary.request_id) is not None
    }

    return AggregationResult(
        overview=overview,
        requests=tuple(request_summaries),
        errors=tuple(errors),
        stages=stage_stats,
        request_details=tuple(request_details),
        _request_index=request_index,
    )


def build_request_detail(
    records: Iterable[ParsedLogRecord],
    request_id: str,
    *,
    project_id: str | None = None,
    summary_mapping_by_project: Mapping[str, Mapping[str, str]] | None = None,
    request_stage_limit: int,
) -> RequestDetail | None:
    target_request_id = _clean_text(request_id)
    if target_request_id is None:
        return None
    filtered_records = [
        record
        for record in records
        if _clean_text(record.request_id) == target_request_id
        and (project_id is None or _clean_text(record.project_id) == _clean_text(project_id))
    ]
    if not filtered_records:
        return None
    result = aggregate_records(
        filtered_records,
        project_id=project_id,
        summary_mapping_by_project=summary_mapping_by_project,
        top_n=1,
        request_stage_limit=request_stage_limit,
    )
    return result.find_request_detail(request_id, project_id=project_id)


__all__ = [
    "AggregatedEvent",
    "AggregationOverview",
    "AggregationResult",
    "ErrorSummary",
    "RequestDetail",
    "RequestSummary",
    "StageStat",
    "StageTiming",
    "aggregate_records",
    "build_request_detail",
]
