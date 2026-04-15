from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
from pathlib import Path
from secrets import token_hex
import time
from typing import Any, Iterator

from app.timefmt import format_local_datetime

DEFAULT_LOG_DIR_ENV_VAR = "KMS_LOG_DIR"
DEFAULT_LOG_LEVEL_ENV_VAR = "KMS_LOG_LEVEL"
SERVICE_NAME = "kms-api"
LOG_SCHEMA_VERSION = 1
_EVENT_SUFFIXES = ("start", "end", "error")
_CONTEXT_KEYS_EXCLUDED_FROM_ATTRIBUTES = {
    "attributes",
    "duration_ms",
    "elapsed_ms",
    "error_type",
    "event",
    "event_type",
    "exception",
    "kind",
    "parent_span_id",
    "request_id",
    "span_id",
    "span_name",
    "status",
    "trace_id",
}
_ATTRIBUTE_ALIASES = {
    "client": "http.client",
    "method": "http.method",
    "path": "http.path",
    "query": "http.query",
    "status_code": "http.status_code",
}

_request_id_var: ContextVar[str | None] = ContextVar("kms_request_id", default=None)
_span_stack_var: ContextVar[tuple["SpanFrame", ...]] = ContextVar("kms_span_stack", default=())
_configured_signature: tuple[str | None, str] | None = None


@dataclass(frozen=True, slots=True)
class SpanFrame:
    span_id: str
    span_name: str
    kind: str


def _normalize_event(event: str, span_name: str | None = None) -> tuple[str, str | None, str | None, str]:
    text = str(event).strip()
    if not text:
        return text, None, span_name, text

    if text in _EVENT_SUFFIXES:
        canonical_message = f"{span_name}.{text}" if span_name else text
        return text, text, span_name, canonical_message

    for suffix in _EVENT_SUFFIXES:
        marker = f".{suffix}"
        if text.endswith(marker):
            resolved_span_name = span_name or text[: -len(marker)]
            canonical_message = f"{resolved_span_name}.{suffix}" if resolved_span_name else text
            return suffix, suffix, resolved_span_name, canonical_message
    return text, None, span_name, text


def _build_attributes(context: dict[str, Any]) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    existing = context.get("attributes")
    if isinstance(existing, dict):
        attributes.update(existing)

    for key, alias in _ATTRIBUTE_ALIASES.items():
        if key in context and alias not in attributes:
            attributes[alias] = context[key]

    for key, value in context.items():
        if key in _CONTEXT_KEYS_EXCLUDED_FROM_ATTRIBUTES:
            continue
        if key not in attributes:
            attributes[key] = value
    return attributes


def current_span() -> SpanFrame | None:
    stack = _span_stack_var.get()
    if not stack:
        return None
    return stack[-1]


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = getattr(record, "context", None)
        if not isinstance(context, dict):
            context = {}
        normalized_context = dict(context)

        event, event_type, span_name, canonical_message = _normalize_event(
            str(normalized_context.get("event") or record.getMessage()),
            str(normalized_context["span_name"]) if normalized_context.get("span_name") else None,
        )
        normalized_context["event"] = event
        if event_type is not None:
            normalized_context.setdefault("event_type", event_type)
        if span_name is not None:
            normalized_context.setdefault("span_name", span_name)

        request_id = str(normalized_context.get("request_id") or current_request_id() or "")
        if request_id:
            normalized_context.setdefault("request_id", request_id)
            normalized_context.setdefault("trace_id", str(normalized_context.get("trace_id") or request_id))

        attributes = _build_attributes(normalized_context)
        if attributes:
            normalized_context["attributes"] = attributes

        payload: dict[str, Any] = {
            "timestamp": format_local_datetime(),
            "schema_version": LOG_SCHEMA_VERSION,
            "service": SERVICE_NAME,
            "event": event,
            "level": record.levelname,
            "logger": record.name,
            "message": canonical_message,
        }
        payload.update(normalized_context)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def current_request_id() -> str | None:
    return _request_id_var.get()


def bind_request_id(request_id: str | None) -> Token[str | None]:
    return _request_id_var.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id_var.reset(token)


def bind_span(span_name: str, *, kind: str = "internal", span_id: str | None = None) -> tuple[SpanFrame, Token[tuple[SpanFrame, ...]]]:
    frame = SpanFrame(
        span_id=span_id or token_hex(4),
        span_name=span_name,
        kind=kind,
    )
    stack = _span_stack_var.get()
    return frame, _span_stack_var.set(stack + (frame,))


def reset_span(token: Token[tuple[SpanFrame, ...]]) -> None:
    _span_stack_var.reset(token)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def configure_logging(*, log_dir: str | Path | None = None, level: str | int | None = None) -> Path | None:
    global _configured_signature

    resolved_level = str(level or os.getenv(DEFAULT_LOG_LEVEL_ENV_VAR) or "INFO").upper()
    resolved_dir: Path | None = None
    raw_dir = log_dir or os.getenv(DEFAULT_LOG_DIR_ENV_VAR)
    if raw_dir:
        resolved_dir = Path(raw_dir).resolve()

    signature = (str(resolved_dir) if resolved_dir is not None else None, resolved_level)
    if _configured_signature == signature:
        return resolved_dir

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, resolved_level, logging.INFO))

    for handler in list(root_logger.handlers):
        if getattr(handler, "_kms_managed", False):
            root_logger.removeHandler(handler)
            handler.close()

    formatter = JsonLogFormatter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler._kms_managed = True  # type: ignore[attr-defined]
    root_logger.addHandler(stream_handler)

    if resolved_dir is not None:
        resolved_dir.mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            resolved_dir / "kms-api.log",
            when="midnight",
            backupCount=14,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler._kms_managed = True  # type: ignore[attr-defined]
        root_logger.addHandler(file_handler)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        logger = logging.getLogger(logger_name)
        logger.handlers = []
        logger.propagate = True
        logger.setLevel(root_logger.level)

    _configured_signature = signature
    return resolved_dir


def log_event(logger: logging.Logger, event: str, **context: Any) -> None:
    logger.info(event, extra={"context": {"event": event, **context}})


def duration_fields(elapsed_ms: float) -> dict[str, float]:
    rounded = round(float(elapsed_ms), 3)
    return {
        "duration_ms": rounded,
        "elapsed_ms": rounded,
    }


@dataclass(slots=True)
class OperationSpan:
    logger: logging.Logger
    operation: str
    context: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.perf_counter)

    def set(self, **context: Any) -> None:
        self.context.update(context)


@contextmanager
def timed_operation(logger: logging.Logger, operation: str, **context: Any) -> Iterator[OperationSpan]:
    parent_span = current_span()
    span_frame, stack_token = bind_span(
        operation,
        kind=str(context.get("kind") or "internal"),
    )
    span_context = dict(context)
    span_context.setdefault("span_name", operation)
    span_context.setdefault("span_id", span_frame.span_id)
    span_context.setdefault("kind", span_frame.kind)
    if parent_span is not None:
        span_context.setdefault("parent_span_id", parent_span.span_id)
    trace_id = current_request_id()
    if trace_id:
        span_context.setdefault("trace_id", trace_id)
        span_context.setdefault("request_id", trace_id)

    span = OperationSpan(logger=logger, operation=operation, context=span_context)
    logger.info(
        "start",
        extra={"context": {"event": "start", **dict(span.context)}},
    )
    status = "ok"
    try:
        yield span
    except Exception as exc:
        status = "error"
        span.set(error_type=type(exc).__name__)
        logger.exception(
            "error",
            extra={"context": {"event": "error", **dict(span.context)}},
        )
        raise
    finally:
        span.set(status=status, **duration_fields((time.perf_counter() - span.started_at) * 1000.0))
        logger.info(
            "end",
            extra={"context": {"event": "end", **dict(span.context)}},
        )
        reset_span(stack_token)
