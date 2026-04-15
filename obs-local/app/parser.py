from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_EVENT_SUFFIXES = ("start", "end", "error")
_CANONICAL_ROOT_KEYS = {
    "attributes",
    "duration_ms",
    "error_type",
    "event",
    "event_type",
    "exception",
    "id",
    "kind",
    "level",
    "logger",
    "method",
    "operation",
    "parent_span_id",
    "path",
    "request_id",
    "schema_version",
    "service",
    "span_id",
    "span_name",
    "status",
    "status_code",
    "summary",
    "timestamp",
    "trace_id",
}
_CANONICAL_ATTRIBUTE_KEYS = {
    "display_summary",
    "http.method",
    "http.path",
    "http.status_code",
    "message",
    "name",
    "operation",
    "span.kind",
    "span.status",
    "span_name",
    "status_code",
    "summary",
    "trace_id",
    "request_id",
}


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    else:
        text = str(value).strip()
    return text or None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _clean_text(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return None
    text = _clean_text(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            number = float(text)
        except ValueError:
            return None
        if number.is_integer():
            return int(number)
        return None


def _parse_timezone(value: str | None) -> tuple[tzinfo, str | None]:
    text = _clean_text(value) or "Asia/Shanghai"
    if text in {"UTC", "Z"}:
        return timezone.utc, None
    if text.startswith(("+", "-")):
        match = re.fullmatch(r"(?P<sign>[+-])(?P<hours>\d{2}):?(?P<minutes>\d{2})", text)
        if match:
            sign = 1 if match.group("sign") == "+" else -1
            hours = int(match.group("hours"))
            minutes = int(match.group("minutes"))
            offset = timedelta(hours=hours, minutes=minutes) * sign
            return timezone(offset), None
    try:
        return ZoneInfo(text), None
    except ZoneInfoNotFoundError:
        return timezone.utc, f"unknown timezone {text!r}; falling back to UTC"


def _parse_epoch(value: str) -> tuple[datetime | None, str | None]:
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
        return None, None
    try:
        number = float(value)
    except ValueError:
        return None, None
    kind = "epoch_ms" if abs(number) >= 1e11 or len(value.replace("-", "").replace("+", "").split(".", 1)[0]) >= 13 else "epoch_s"
    try:
        if kind == "epoch_ms":
            dt = datetime.fromtimestamp(number / 1000.0, tz=timezone.utc)
        else:
            dt = datetime.fromtimestamp(number, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None, None
    return dt, kind


def _parse_timestamp_details(value: Any, *, timezone_name: str = "Asia/Shanghai") -> tuple[datetime | None, str | None, str | None]:
    if value is None:
        return None, None, None

    tz, tz_warning = _parse_timezone(timezone_name)

    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
            return parsed.astimezone(timezone.utc), "local_datetime", tz_warning
        return parsed.astimezone(timezone.utc), "rfc3339", tz_warning

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        kind = "epoch_ms" if abs(number) >= 1e11 else "epoch_s"
        try:
            parsed = (
                datetime.fromtimestamp(number / 1000.0, tz=timezone.utc)
                if kind == "epoch_ms"
                else datetime.fromtimestamp(number, tz=timezone.utc)
            )
        except (OverflowError, OSError, ValueError):
            return None, None, tz_warning or f"unrecognized timestamp format: {value!r}"
        return parsed, kind, tz_warning

    text = _clean_text(value)
    if text is None:
        return None, None, None

    try:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        parsed = None
    else:
        return parsed.replace(tzinfo=tz).astimezone(timezone.utc), "local_datetime", tz_warning

    epoch_dt, epoch_kind = _parse_epoch(text)
    if epoch_dt is not None:
        return epoch_dt, epoch_kind, tz_warning

    iso_text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_text)
    except ValueError:
        parsed = None
    else:
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=tz).astimezone(timezone.utc), "iso8601_naive", tz_warning
        return parsed.astimezone(timezone.utc), "rfc3339", tz_warning

    return None, None, tz_warning or f"unrecognized timestamp format: {text!r}"


def parse_timestamp(value: Any, *, timezone_name: str = "Asia/Shanghai") -> datetime | None:
    parsed, _, _ = _parse_timestamp_details(value, timezone_name=timezone_name)
    return parsed


def _split_event_name(value: str | None) -> tuple[str | None, str | None]:
    text = _clean_text(value)
    if text is None:
        return None, None
    for suffix in _EVENT_SUFFIXES:
        marker = f".{suffix}"
        if text.endswith(marker):
            return text[: -len(marker)], suffix
    if text in _EVENT_SUFFIXES:
        return None, text
    return text, "event"


def _first_mapping(mapping: Mapping[str, Any], *keys: str) -> Mapping[str, Any] | None:
    for key in keys:
        candidate = mapping.get(key)
        if isinstance(candidate, Mapping):
            return candidate
    return None


def _lookup_value(mapping: Mapping[str, Any], *keys: str) -> Any:
    nested = _first_mapping(mapping, "attributes")
    for key in keys:
        if key in mapping:
            return mapping[key]
        if nested is not None and key in nested:
            return nested[key]
    return None


def _redact_value(key: str, value: Any, redact_fields: set[str]) -> Any:
    if key in redact_fields:
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            nested_key: _redact_value(nested_key, nested_value, redact_fields)
            for nested_key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [
            _redact_value(key, item, redact_fields) if isinstance(item, Mapping) else item
            for item in value
        ]
    return value


def _redact_mapping(mapping: Mapping[str, Any], redact_fields: set[str]) -> dict[str, Any]:
    if not redact_fields:
        return dict(mapping)
    return {
        key: _redact_value(key, value, redact_fields)
        for key, value in mapping.items()
    }


def _extract_attributes(payload: Mapping[str, Any], *, redact_fields: set[str]) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    nested = payload.get("attributes")
    if isinstance(nested, Mapping):
        for key, value in nested.items():
            if key in _CANONICAL_ATTRIBUTE_KEYS:
                continue
            attributes[key] = _redact_value(key, value, redact_fields)
    elif nested is not None and "attributes" not in redact_fields:
        attributes["attributes"] = _redact_value("attributes", nested, redact_fields)

    for key, value in payload.items():
        if key in _CANONICAL_ROOT_KEYS:
            continue
        if key == "attributes":
            continue
        if key in _CANONICAL_ATTRIBUTE_KEYS:
            continue
        attributes[key] = _redact_value(key, value, redact_fields)
    return attributes


@dataclass(slots=True)
class LogSourceContext:
    project_id: str | None = None
    source_id: str | None = None
    log_path: str | None = None
    timezone: str = "Asia/Shanghai"
    service_hint: str | None = None
    redact_fields: tuple[str, ...] = ()


@dataclass(slots=True)
class ParsedLogRecord:
    project_id: str | None = None
    source_id: str | None = None
    log_path: str | None = None
    source_timezone: str | None = None
    line_number: int | None = None
    raw_text: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    valid: bool = True
    parse_error: str | None = None
    warnings: tuple[str, ...] = ()
    timestamp: datetime | None = None
    timestamp_raw: str | None = None
    timestamp_format: str | None = None
    schema_version: int | None = None
    service: str | None = None
    logger: str | None = None
    level: str | None = None
    event: str | None = None
    event_type: str | None = None
    span_name: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    trace_id: str | None = None
    request_id: str | None = None
    kind: str | None = None
    status: str | None = None
    status_code: int | None = None
    duration_ms: float | None = None
    error_type: str | None = None
    exception: str | None = None
    method: str | None = None
    path: str | None = None
    summary: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "project_id": self.project_id,
            "source_id": self.source_id,
            "log_path": self.log_path,
            "source_timezone": self.source_timezone,
            "line_number": self.line_number,
            "raw_text": self.raw_text,
            "raw": dict(self.raw),
            "valid": self.valid,
            "parse_error": self.parse_error,
            "warnings": list(self.warnings),
            "timestamp": self.timestamp.isoformat(timespec="milliseconds") if self.timestamp else None,
            "timestamp_raw": self.timestamp_raw,
            "timestamp_format": self.timestamp_format,
            "schema_version": self.schema_version,
            "service": self.service,
            "logger": self.logger,
            "level": self.level,
            "event": self.event,
            "event_type": self.event_type,
            "span_name": self.span_name,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "kind": self.kind,
            "status": self.status,
            "status_code": self.status_code,
            "duration_ms": self.duration_ms,
            "error_type": self.error_type,
            "exception": self.exception,
            "method": self.method,
            "path": self.path,
            "summary": self.summary,
            "attributes": dict(self.attributes),
        }
        return {key: value for key, value in payload.items() if value is not None}


def _parse_record(
    payload: Mapping[str, Any],
    *,
    source: LogSourceContext,
    raw_text: str | None = None,
    line_number: int | None = None,
) -> ParsedLogRecord:
    redact_fields = {field for field in source.redact_fields if field and field.strip()}
    source_timezone = _clean_text(source.timezone) or "Asia/Shanghai"
    sanitized = _redact_mapping(payload, redact_fields)
    warnings: list[str] = []

    timestamp_raw = _clean_text(_lookup_value(sanitized, "timestamp"))
    timestamp, timestamp_format, timestamp_warning = _parse_timestamp_details(timestamp_raw, timezone_name=source_timezone)
    if timestamp_warning:
        warnings.append(timestamp_warning)

    event_raw = _clean_text(_lookup_value(sanitized, "event", "message"))
    event_base, event_type = _split_event_name(event_raw)
    explicit_span_name = _clean_text(_lookup_value(sanitized, "span_name", "operation", "name"))
    span_name = explicit_span_name or event_base

    service = _clean_text(_lookup_value(sanitized, "service")) or source.service_hint
    logger = _clean_text(_lookup_value(sanitized, "logger"))
    level = _clean_text(_lookup_value(sanitized, "level"))
    span_id = _clean_text(_lookup_value(sanitized, "span_id"))
    parent_span_id = _clean_text(_lookup_value(sanitized, "parent_span_id"))
    trace_id = _clean_text(_lookup_value(sanitized, "trace_id")) or _clean_text(_lookup_value(sanitized, "request_id"))
    request_id = _clean_text(_lookup_value(sanitized, "request_id")) or trace_id
    kind = _clean_text(_lookup_value(sanitized, "kind", "span.kind"))
    status = _clean_text(_lookup_value(sanitized, "status", "span.status"))
    status_code = _as_int(_lookup_value(sanitized, "status_code", "http.status_code"))
    duration_ms = _as_float(_lookup_value(sanitized, "duration_ms", "duration"))
    error_type = _clean_text(_lookup_value(sanitized, "error_type", "exception.type"))
    exception = _clean_text(_lookup_value(sanitized, "exception"))
    method = _clean_text(_lookup_value(sanitized, "method", "http.method"))
    path = _clean_text(_lookup_value(sanitized, "path", "http.path"))
    summary = _clean_text(_lookup_value(sanitized, "summary", "display_summary"))
    schema_version = _as_int(_lookup_value(sanitized, "schema_version"))
    if schema_version is None:
        schema_version = 1

    if status is None:
        if status_code is not None:
            status = "error" if status_code >= 400 else "ok"
        elif event_type == "error" or error_type is not None or exception is not None:
            status = "error"
        elif event_type == "end":
            status = "ok"

    attributes = _extract_attributes(sanitized, redact_fields=redact_fields)
    if summary is None:
        summary = _clean_text(_lookup_value(attributes, "summary", "display_summary"))

    if event_type is None:
        event_type = "event" if event_raw is not None else None
    if span_name is None:
        span_name = _clean_text(_lookup_value(attributes, "span_name", "operation", "name"))

    if timestamp is None and timestamp_raw is not None:
        warnings.append(f"unparsed timestamp value: {timestamp_raw!r}")

    return ParsedLogRecord(
        project_id=source.project_id,
        source_id=source.source_id,
        log_path=source.log_path,
        source_timezone=source_timezone,
        line_number=line_number,
        raw_text=raw_text,
        raw=dict(sanitized),
        valid=True,
        parse_error=None,
        warnings=tuple(warnings),
        timestamp=timestamp,
        timestamp_raw=timestamp_raw,
        timestamp_format=timestamp_format,
        schema_version=schema_version,
        service=service,
        logger=logger,
        level=level,
        event=event_raw,
        event_type=event_type,
        span_name=span_name,
        span_id=span_id,
        parent_span_id=parent_span_id,
        trace_id=trace_id,
        request_id=request_id,
        kind=kind,
        status=status,
        status_code=status_code,
        duration_ms=duration_ms,
        error_type=error_type,
        exception=exception,
        method=method,
        path=path,
        summary=summary,
        attributes=attributes,
    )


class JsonlParser:
    def __init__(self, source: LogSourceContext | None = None) -> None:
        self.source = source or LogSourceContext()

    def parse_line(self, line: str | bytes, *, line_number: int | None = None) -> ParsedLogRecord:
        raw_text = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else str(line)
        stripped = raw_text.strip()
        if not stripped:
            return ParsedLogRecord(
                project_id=self.source.project_id,
                source_id=self.source.source_id,
                log_path=self.source.log_path,
                source_timezone=self.source.timezone,
                line_number=line_number,
                raw_text=raw_text,
                valid=False,
                parse_error="empty line",
            )
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            return ParsedLogRecord(
                project_id=self.source.project_id,
                source_id=self.source.source_id,
                log_path=self.source.log_path,
                source_timezone=self.source.timezone,
                line_number=line_number,
                raw_text=raw_text,
                valid=False,
                parse_error=f"invalid json: {exc.msg}",
            )
        if not isinstance(payload, Mapping):
            return ParsedLogRecord(
                project_id=self.source.project_id,
                source_id=self.source.source_id,
                log_path=self.source.log_path,
                source_timezone=self.source.timezone,
                line_number=line_number,
                raw_text=raw_text,
                valid=False,
                parse_error=f"json object expected, got {type(payload).__name__}",
            )
        return _parse_record(payload, source=self.source, raw_text=raw_text, line_number=line_number)

    def iter_lines(self, lines: Iterable[str | bytes]) -> Iterator[ParsedLogRecord]:
        for line_number, line in enumerate(lines, start=1):
            yield self.parse_line(line, line_number=line_number)

    def iter_file(self, path: str | Path, *, encoding: str = "utf-8") -> Iterator[ParsedLogRecord]:
        file_path = Path(path)
        with file_path.open("r", encoding=encoding, errors="replace") as handle:
            yield from self.iter_lines(handle)


def parse_log_line(
    line: str | bytes,
    *,
    source: LogSourceContext | None = None,
    line_number: int | None = None,
) -> ParsedLogRecord:
    return JsonlParser(source).parse_line(line, line_number=line_number)


def parse_jsonl_lines(
    lines: Iterable[str | bytes],
    *,
    source: LogSourceContext | None = None,
) -> Iterator[ParsedLogRecord]:
    return JsonlParser(source).iter_lines(lines)


def parse_jsonl_file(
    path: str | Path,
    *,
    source: LogSourceContext | None = None,
    encoding: str = "utf-8",
) -> Iterator[ParsedLogRecord]:
    return JsonlParser(source).iter_file(path, encoding=encoding)


__all__ = [
    "JsonlParser",
    "LogSourceContext",
    "ParsedLogRecord",
    "parse_jsonl_file",
    "parse_jsonl_lines",
    "parse_log_line",
    "parse_timestamp",
]
