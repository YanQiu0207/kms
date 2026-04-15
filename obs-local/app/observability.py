from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import time
from typing import Any, Iterator

SERVICE_NAME = "obs-local"

_request_id_var: ContextVar[str | None] = ContextVar("obs_local_request_id", default=None)
_configured_signature: tuple[str | None, str] | None = None


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = getattr(record, "context", None)
        if not isinstance(context, dict):
            context = {}

        event = str(context.get("event") or record.getMessage())
        payload: dict[str, Any] = {
            "timestamp": _now_iso(),
            "service": SERVICE_NAME,
            "event": event,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = current_request_id()
        if request_id:
            payload["request_id"] = request_id
        payload.update(context)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def current_request_id() -> str | None:
    return _request_id_var.get()


def bind_request_id(request_id: str | None) -> Token[str | None]:
    return _request_id_var.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id_var.reset(token)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def configure_logging(*, log_dir: str | Path | None = None, level: str | int | None = None) -> Path | None:
    global _configured_signature

    resolved_level = str(level or "INFO").upper()
    resolved_dir: Path | None = None
    if log_dir:
        resolved_dir = Path(log_dir).expanduser().resolve()

    signature = (str(resolved_dir) if resolved_dir is not None else None, resolved_level)
    if _configured_signature == signature:
        return resolved_dir

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, resolved_level, logging.INFO))

    for handler in list(root_logger.handlers):
        if getattr(handler, "_obs_local_managed", False):
            root_logger.removeHandler(handler)
            handler.close()

    formatter = JsonLogFormatter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler._obs_local_managed = True  # type: ignore[attr-defined]
    root_logger.addHandler(stream_handler)

    if resolved_dir is not None:
        resolved_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(resolved_dir / "obs-local.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler._obs_local_managed = True  # type: ignore[attr-defined]
        root_logger.addHandler(file_handler)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        logger = logging.getLogger(logger_name)
        logger.handlers = []
        logger.propagate = True
        logger.setLevel(root_logger.level)

    _configured_signature = signature
    return resolved_dir


def log_event(logger: logging.Logger, event: str, *, level: int = logging.INFO, **context: Any) -> None:
    logger.log(level, event, extra={"context": {"event": event, **context}})


@dataclass(slots=True)
class OperationSpan:
    logger: logging.Logger
    operation: str
    level: int = logging.INFO
    context: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.perf_counter)

    def set(self, **context: Any) -> None:
        self.context.update(context)


@contextmanager
def timed_operation(
    logger: logging.Logger,
    operation: str,
    *,
    level: int = logging.INFO,
    **context: Any,
) -> Iterator[OperationSpan]:
    span = OperationSpan(logger=logger, operation=operation, level=level, context=dict(context))
    log_event(logger, f"{operation}.start", level=level, **dict(span.context))
    status = "ok"
    try:
        yield span
    except Exception as exc:
        status = "error"
        span.set(error_type=type(exc).__name__)
        logger.exception(
            f"{operation}.error",
            extra={"context": {"event": f"{operation}.error", **dict(span.context)}},
        )
        raise
    finally:
        span.set(status=status, elapsed_ms=round((time.perf_counter() - span.started_at) * 1000.0, 3))
        log_event(logger, f"{operation}.end", level=level, **dict(span.context))

