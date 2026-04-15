from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import re
import uuid
from typing import Any

from fastapi import FastAPI

from .aggregator import aggregate_records
from .api_errors import router as errors_router
from .api_projects import router as projects_router
from .api_requests import router as requests_router
from .api_stages import router as stages_router
from .config import load_config
from .observability import bind_request_id, configure_logging, get_logger, log_event, reset_request_id, timed_operation
from .parser import LogSourceContext, ParsedLogRecord, parse_jsonl_file, parse_jsonl_lines
from .registry import ProjectSpec, SourceRegistry, SourceSpec
from .schemas import (
    AppConfig,
    HealthResponse,
    ProjectHealth,
    ServiceHealth,
    SourceHealth,
    UiSettingsResponse,
)
from .state_store import FileOffsetState, SQLiteStateStore, SourceHealthState
from .tailer import FileTailer, TailerError
from .web import StreamHub, create_stream_router, publish_updates

APP_TITLE = "obs-local"
APP_DESCRIPTION = "Local observability service for structured logs."
APP_VERSION = "0.1.0"
_WINDOW_PATTERN = re.compile(r"^\s*(?P<count>\d+)\s*(?P<unit>[smhd])\s*$", re.IGNORECASE)
_MIN_RECORD_TIMESTAMP = datetime.min.replace(tzinfo=timezone.utc)
LOGGER = get_logger("obs_local.app")


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def _query_log_summary(query: str) -> dict[str, int]:
    if not query:
        return {"query_len": 0}
    return {"query_len": len(query)}


def _record_cache_sort_key(record: ParsedLogRecord) -> tuple[bool, datetime, int, str, str]:
    return (
        record.timestamp is not None,
        record.timestamp or _MIN_RECORD_TIMESTAMP,
        record.line_number if record.line_number is not None else -1,
        record.project_id or "",
        record.source_id or "",
    )


def _set_cached_records(app: FastAPI, records: tuple[ParsedLogRecord, ...] | list[ParsedLogRecord]) -> tuple[ParsedLogRecord, ...]:
    cached_records = tuple(records)
    max_cached_records = app.state.config.runtime.max_cached_records
    if len(cached_records) > max_cached_records:
        original_count = len(cached_records)
        cached_records = tuple(sorted(cached_records, key=_record_cache_sort_key)[-max_cached_records:])
        log_event(
            LOGGER,
            "record_cache.trimmed",
            max_cached_records=max_cached_records,
            original_count=original_count,
            cached_record_count=len(cached_records),
            evicted_count=original_count - len(cached_records),
        )
    app.state.parsed_records = cached_records
    return cached_records


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        pass
    else:
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def _resolve_state_db_path(config: AppConfig) -> Path:
    return Path(config.storage.state_db_path).expanduser().resolve()


def _bootstrap_registry(config: AppConfig) -> SourceRegistry:
    state_db_path = _resolve_state_db_path(config)
    store = SQLiteStateStore(state_db_path)
    registry = SourceRegistry(store)
    declared_projects: list[ProjectSpec] = []
    for project in config.projects:
        sources = tuple(
            SourceSpec(
                project_id=project.project_id,
                source_id=source.source_id,
                log_path=source.log_path,
                name=source.source_id,
                format=source.format,
                timezone=source.timezone,
                service_hint=source.service_hint,
                redact_fields=tuple(source.redact_fields),
                enabled=source.enabled,
                metadata={"summary_mapping": dict(project.summary_mapping)},
            )
            for source in project.sources
        )
        declared_projects.append(
            ProjectSpec(
                project_id=project.project_id,
                name=project.display_name or project.project_id,
                enabled=project.enabled,
                metadata={"summary_mapping": dict(project.summary_mapping)},
                sources=sources,
            )
        )
    if declared_projects:
        registry.register_many(declared_projects)
    return registry


def _source_health_state(source: SourceSpec, persisted: SourceHealthState | None) -> tuple[str, str, str | None, bool, str | None]:
    last_event_at = persisted.last_event_at if persisted is not None else None
    if not source.enabled:
        return "ok", "offline", last_event_at, False, None

    tailer_error = persisted.tailer_error if persisted is not None else None
    replaying = persisted.replaying if persisted is not None else False
    if tailer_error:
        return "error", "stale", last_event_at, replaying, tailer_error
    if last_event_at:
        return "ok", "live", last_event_at, replaying, None
    return "ok", "idle", None, replaying, None


def _build_source_context(project_id: str, source: SourceSpec) -> LogSourceContext:
    return LogSourceContext(
        project_id=project_id,
        source_id=source.source_id,
        log_path=source.log_path,
        timezone=source.timezone,
        service_hint=source.service_hint,
        redact_fields=tuple(source.redact_fields),
    )


def _persist_source_offset(registry: SourceRegistry, source: SourceSpec) -> None:
    log_path = Path(source.log_path).expanduser()
    stat_result = log_path.stat()
    inode_raw = getattr(stat_result, "st_ino", 0)
    inode = str(inode_raw) if inode_raw else None
    mtime = float(stat_result.st_mtime)
    file_size = int(stat_result.st_size)
    session_id = f"{inode}:{file_size}:{int(mtime * 1000)}" if inode else f"noinode:{file_size}:{int(mtime * 1000)}"
    registry.store.upsert_file_offset(
        FileOffsetState(
            project_id=source.project_id,
            source_id=source.source_id,
            log_path=str(log_path),
            offset=file_size,
            file_size=file_size,
            mtime=mtime,
            inode=inode,
            session_id=session_id,
        )
    )


def build_health_response(app: FastAPI) -> HealthResponse:
    config: AppConfig = app.state.config
    registry: SourceRegistry = app.state.registry
    service_status = "ok"
    service_replaying = False
    service_tailer_error: str | None = None
    projects: list[ProjectHealth] = []
    for project in registry.list_projects():
        source_health_items: list[SourceHealth] = []
        last_event_at: str | None = None
        tailer_error: str | None = None
        replaying = False
        project_status = "ok"
        project_staleness = "offline" if not any(source.enabled for source in project.sources) else "idle"

        for source in project.sources:
            persisted = registry.store.get_source_health(project.project_id, source.source_id)
            source_status, source_staleness, source_last_event_at, source_replaying, source_tailer_error = _source_health_state(source, persisted)

            if source_status == "error":
                project_status = "error"
            if source_staleness == "live":
                project_staleness = "live"
            elif project_staleness != "live" and source_staleness == "stale":
                project_staleness = "stale"
            elif project_staleness == "offline" and source_staleness == "idle":
                project_staleness = "idle"

            if source_last_event_at and (
                last_event_at is None
                or (_parse_timestamp(source_last_event_at) or datetime.min.replace(tzinfo=timezone.utc))
                > (_parse_timestamp(last_event_at) or datetime.min.replace(tzinfo=timezone.utc))
            ):
                last_event_at = source_last_event_at
            if source_tailer_error and not tailer_error:
                tailer_error = source_tailer_error
            replaying = replaying or source_replaying

            source_health_items.append(
                SourceHealth(
                    project_id=project.project_id,
                    source_id=source.source_id,
                    log_path=source.log_path,
                    status=source_status,
                    staleness=source_staleness,
                    last_event_at=source_last_event_at,
                    replaying=source_replaying,
                    tailer_error=source_tailer_error,
                )
            )

        if project_status != "error" and project_staleness in {"idle", "stale", "offline"}:
            project_status = "degraded"

        display_name = next(
            (
                configured.display_name
                for configured in config.projects
                if configured.project_id == project.project_id
            ),
            None,
        ) or project.name

        projects.append(
            ProjectHealth(
                project_id=project.project_id,
                display_name=display_name,
                status=project_status,
                staleness=project_staleness,
                last_event_at=last_event_at,
                replaying=replaying,
                tailer_error=tailer_error,
                sources=source_health_items,
            )
        )

        if project_status == "error":
            service_status = "error"
        elif service_status != "error" and project_status == "degraded":
            service_status = "degraded"
        service_replaying = service_replaying or replaying
        if tailer_error and service_tailer_error is None:
            service_tailer_error = tailer_error

    service = ServiceHealth(
        service="obs-local",
        status=service_status,
        version=APP_VERSION,
        started_at=app.state.started_at,
        replaying=service_replaying,
        tailer_error=service_tailer_error,
    )

    return HealthResponse(
        service=service,
        projects=projects,
        generated_at=_now_iso(),
    )


def _aggregate_records_for_app(
    app: FastAPI,
    records: tuple[ParsedLogRecord, ...],
    *,
    project_id: str | None = None,
):
    aggregation_config = app.state.config.aggregation
    summary_mapping = getattr(app.state, "summary_mapping_by_project", {})
    return aggregate_records(
        records,
        project_id=project_id,
        summary_mapping_by_project=summary_mapping,
        top_n=aggregation_config.top_n,
        request_stage_limit=aggregation_config.request_stage_limit,
    )


def _build_empty_aggregation_result(config: AppConfig):
    return aggregate_records(
        (),
        project_id=None,
        summary_mapping_by_project={},
        top_n=config.aggregation.top_n,
        request_stage_limit=config.aggregation.request_stage_limit,
    )


def _summary_mapping_by_project(registry: SourceRegistry) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    for project in registry.list_projects():
        raw_mapping = project.metadata.get("summary_mapping") if isinstance(project.metadata, dict) else None
        if isinstance(raw_mapping, dict):
            normalized = {
                str(key).strip(): str(value).strip()
                for key, value in raw_mapping.items()
                if str(key).strip() and str(value).strip()
            }
            mapping[project.project_id] = normalized
    return mapping


def _parse_window(window: str | None) -> timedelta | None:
    if not window:
        return None
    match = _WINDOW_PATTERN.match(window)
    if match is None:
        return None
    count = int(match.group("count"))
    unit = match.group("unit").lower()
    if unit == "s":
        return timedelta(seconds=count)
    if unit == "m":
        return timedelta(minutes=count)
    if unit == "h":
        return timedelta(hours=count)
    return timedelta(days=count)


def _filter_records(
    records: tuple[ParsedLogRecord, ...],
    *,
    project_id: str | None = None,
    window: str | None = None,
) -> tuple[ParsedLogRecord, ...]:
    cutoff: datetime | None = None
    delta = _parse_window(window)
    if delta is not None:
        cutoff = datetime.now(timezone.utc) - delta

    filtered: list[ParsedLogRecord] = []
    for record in records:
        if project_id is not None and record.project_id != project_id:
            continue
        if cutoff is not None:
            if record.timestamp is None:
                continue
            if record.timestamp < cutoff:
                continue
        filtered.append(record)
    return tuple(filtered)


def _load_records_from_registry(registry: SourceRegistry) -> tuple[ParsedLogRecord, ...]:
    records: list[ParsedLogRecord] = []
    for project in registry.list_projects():
        for source in project.sources:
            if not source.enabled or source.format != "jsonl":
                continue
            context = LogSourceContext(
                project_id=project.project_id,
                source_id=source.source_id,
                log_path=source.log_path,
                timezone=source.timezone,
                service_hint=source.service_hint,
                redact_fields=tuple(source.redact_fields),
            )
            try:
                source_records = tuple(parse_jsonl_file(source.log_path, source=context))
            except (FileNotFoundError, PermissionError, OSError) as exc:
                log_event(
                    LOGGER,
                    "source.load.error",
                    level=logging.ERROR,
                    project_id=project.project_id,
                    source_id=source.source_id,
                    log_path=source.log_path,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                registry.store.upsert_source_health(
                    SourceHealthState(
                        project_id=project.project_id,
                        source_id=source.source_id,
                        last_error_at=_now_iso(),
                        last_error_message=str(exc),
                        replaying=False,
                        tailer_error=str(exc),
                    )
                )
                continue

            records.extend(source_records)
            log_event(
                LOGGER,
                "source.load.completed",
                project_id=project.project_id,
                source_id=source.source_id,
                log_path=source.log_path,
                record_count=len(source_records),
            )
            latest_event_at = max(
                (record.timestamp for record in source_records if record.timestamp is not None),
                default=None,
            )
            registry.store.upsert_source_health(
                SourceHealthState(
                    project_id=project.project_id,
                    source_id=source.source_id,
                    last_event_at=latest_event_at.astimezone().isoformat(timespec="milliseconds") if latest_event_at else None,
                    last_error_at=None,
                    last_error_message=None,
                    replaying=False,
                    tailer_error=None,
                )
            )
            with suppress(FileNotFoundError, PermissionError, OSError):
                _persist_source_offset(registry, source)
    return tuple(records)


def _rebuild_aggregation_state(app: FastAPI):
    registry: SourceRegistry = app.state.registry
    parsed_records = _set_cached_records(app, _load_records_from_registry(registry))
    summary_mapping = _summary_mapping_by_project(registry)
    app.state.summary_mapping_by_project = summary_mapping
    aggregation_result = _aggregate_records_for_app(app, parsed_records)
    app.state.aggregation_result = aggregation_result
    log_event(
        LOGGER,
        "aggregation.rebuild.completed",
        project_count=len(registry.list_projects()),
        parsed_record_count=len(parsed_records),
        request_count=len(aggregation_result.requests),
        error_count=len(aggregation_result.errors),
        stage_count=len(aggregation_result.stages),
    )
    return aggregation_result


def _publish_state_snapshot(app: FastAPI, *, project_id: str | None = None) -> None:
    global_result = getattr(app.state, "aggregation_result", None)
    if global_result is not None:
        publish_updates(
            app.state.stream_hub,
            project_id=None,
            health=build_health_response(app).model_dump(),
            overview=global_result.overview.to_dict() if hasattr(global_result, "overview") else None,
            requests=[item.to_dict() for item in getattr(global_result, "requests", ())],
            errors=[item.to_dict() for item in getattr(global_result, "errors", ())],
            stages=[item.to_dict() for item in getattr(global_result, "stages", ())],
        )
    if project_id is None:
        return
    scoped_result = app.state.aggregation_provider(project_id=project_id, window=None)
    publish_updates(
        app.state.stream_hub,
        project_id=project_id,
        health=build_health_response(app).model_dump(),
        overview=scoped_result.overview.to_dict() if hasattr(scoped_result, "overview") else None,
        requests=[item.to_dict() for item in getattr(scoped_result, "requests", ())],
        errors=[item.to_dict() for item in getattr(scoped_result, "errors", ())],
        stages=[item.to_dict() for item in getattr(scoped_result, "stages", ())],
    )


def _default_aggregation_provider(app: FastAPI):
    def _provider(*, project_id: str | None = None, window: str | None = None) -> Any:
        parsed_records = getattr(app.state, "parsed_records", ())
        if project_id is None and not window:
            return getattr(app.state, "aggregation_result", None)
        filtered = _filter_records(parsed_records, project_id=project_id, window=window)
        return _aggregate_records_for_app(app, filtered, project_id=project_id)

    return _provider


def _default_reload_provider(app: FastAPI):
    def _reload(*, project_id: str | None = None) -> Any:
        with timed_operation(LOGGER, "registry.reload", project_id=project_id):
            app.state.registry.reload()
            result = _rebuild_aggregation_state(app)
            _publish_state_snapshot(app, project_id=project_id)
            return result

    return _reload


async def _tail_registry_forever(app: FastAPI, *, poll_interval_seconds: float) -> None:
    registry: SourceRegistry = app.state.registry
    tailer = FileTailer(
        registry.store,
        chunk_size=app.state.config.tailer.chunk_size,
        encoding=app.state.config.tailer.encoding,
        errors=app.state.config.tailer.errors,
    )
    sleep_interval = max(0.05, float(poll_interval_seconds))

    while True:
        changed_projects: set[str] = set()
        for project in registry.list_projects():
            for source in project.sources:
                if not source.enabled or source.format != "jsonl":
                    continue
                context = _build_source_context(project.project_id, source)
                try:
                    tail_result = tailer.incremental(source)
                except TailerError as exc:
                    log_event(
                        LOGGER,
                        "tail.source.error",
                        level=logging.ERROR,
                        project_id=project.project_id,
                        source_id=source.source_id,
                        log_path=source.log_path,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                    registry.store.upsert_source_health(
                        SourceHealthState(
                            project_id=project.project_id,
                            source_id=source.source_id,
                            last_error_at=_now_iso(),
                            last_error_message=str(exc),
                            replaying=False,
                            tailer_error=str(exc),
                        )
                    )
                    changed_projects.add(project.project_id)
                    continue

                persisted = registry.store.get_source_health(project.project_id, source.source_id)
                latest_event_at = persisted.last_event_at if persisted is not None else None
                if tail_result.lines:
                    parsed = tuple(parse_jsonl_lines(tail_result.lines, source=context))
                    if parsed:
                        _set_cached_records(app, tuple(getattr(app.state, "parsed_records", ())) + parsed)
                        latest_timestamp = max((record.timestamp for record in parsed if record.timestamp is not None), default=None)
                        if latest_timestamp is not None:
                            latest_event_at = latest_timestamp.astimezone().isoformat(timespec="milliseconds")
                        changed_projects.add(project.project_id)
                        log_event(
                            LOGGER,
                            "tail.source.ingested",
                            project_id=project.project_id,
                            source_id=source.source_id,
                            log_path=source.log_path,
                            line_count=len(tail_result.lines),
                            parsed_record_count=len(parsed),
                            start_offset=tail_result.start_offset,
                            end_offset=tail_result.end_offset,
                        )

                if persisted is None or persisted.tailer_error is not None or persisted.replaying:
                    changed_projects.add(project.project_id)
                registry.store.upsert_source_health(
                    SourceHealthState(
                        project_id=project.project_id,
                        source_id=source.source_id,
                        last_event_at=latest_event_at,
                        last_error_at=None,
                        last_error_message=None,
                        replaying=False,
                        tailer_error=None,
                    )
                )

        if changed_projects:
            app.state.aggregation_result = _aggregate_records_for_app(app, getattr(app.state, "parsed_records", ()))
            log_event(
                LOGGER,
                "tail.registry.flush",
                changed_project_count=len(changed_projects),
                changed_projects=sorted(changed_projects),
                request_count=len(app.state.aggregation_result.requests),
                error_count=len(app.state.aggregation_result.errors),
                stage_count=len(app.state.aggregation_result.stages),
            )
            for project_id in sorted(changed_projects):
                _publish_state_snapshot(app, project_id=project_id)

        await asyncio.sleep(sleep_interval)


def create_app(config: AppConfig | None = None, *, tail_poll_interval_seconds: float | None = None) -> FastAPI:
    settings = config or load_config()
    configure_logging(log_dir=settings.logging.log_dir, level=settings.logging.level)
    stream_hub = StreamHub(max_queue_size=settings.stream.max_queue_size)
    resolved_tail_poll_interval_seconds = (
        settings.runtime.tail_poll_interval_seconds
        if tail_poll_interval_seconds is None
        else float(tail_poll_interval_seconds)
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with timed_operation(
            LOGGER,
            "app.startup",
            host=settings.server.host,
            port=settings.server.port,
            tail_poll_interval_seconds=resolved_tail_poll_interval_seconds,
            max_queue_size=settings.stream.max_queue_size,
            batch_window_ms=settings.stream.batch_window_ms,
            batch_max_items=settings.stream.batch_max_items,
            aggregation_top_n=settings.aggregation.top_n,
            request_stage_limit=settings.aggregation.request_stage_limit,
        ):
            app.state.config = settings
            app.state.started_at = _now_iso()
            app.state.registry = _bootstrap_registry(settings)
            app.state.stream_hub = stream_hub
            app.state.parsed_records = ()
            app.state.summary_mapping_by_project = {}
            app.state.aggregation_result = _build_empty_aggregation_result(settings)
            app.state.aggregation_provider = _default_aggregation_provider(app)
            app.state.reload_provider = _default_reload_provider(app)
            _rebuild_aggregation_state(app)
            tail_task = asyncio.create_task(
                _tail_registry_forever(app, poll_interval_seconds=resolved_tail_poll_interval_seconds),
                name="obs-local-tail-registry",
            )
        try:
            yield
        finally:
            with timed_operation(LOGGER, "app.shutdown", host=settings.server.host, port=settings.server.port):
                tail_task.cancel()
                with suppress(asyncio.CancelledError):
                    await tail_task
                active_hub = getattr(app.state, "stream_hub", None)
                if isinstance(active_hub, StreamHub):
                    active_hub.close()
                registry = getattr(app.state, "registry", None)
                if registry is not None:
                    registry.close()

    app = FastAPI(
        title=APP_TITLE,
        description=APP_DESCRIPTION,
        version=APP_VERSION,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def log_requests(request, call_next):
        request_id = uuid.uuid4().hex[:12]
        token = bind_request_id(request_id)
        started_at = asyncio.get_running_loop().time()
        log_event(
            LOGGER,
            "http.request.start",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            client=request.client.host if request.client else None,
            **_query_log_summary(request.url.query),
        )
        try:
            response = await call_next(request)
        except Exception:
            LOGGER.exception(
                "http.request.error",
                extra={
                    "context": {
                        "event": "http.request.error",
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "elapsed_ms": round((asyncio.get_running_loop().time() - started_at) * 1000.0, 3),
                    }
                },
            )
            raise
        else:
            log_event(
                LOGGER,
                "http.request.end",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                elapsed_ms=round((asyncio.get_running_loop().time() - started_at) * 1000.0, 3),
            )
            return response
        finally:
            reset_request_id(token)

    @app.get("/api/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return build_health_response(app)

    @app.get("/api/ui-settings", response_model=UiSettingsResponse, tags=["system"])
    def ui_settings() -> UiSettingsResponse:
        return UiSettingsResponse(default_locale=settings.ui.default_locale)

    app.include_router(projects_router)
    app.include_router(requests_router)
    app.include_router(errors_router)
    app.include_router(stages_router)
    app.include_router(
        create_stream_router(
            hub=stream_hub,
            heartbeat_ms=settings.stream.heartbeat_ms,
            batch_window_ms=settings.stream.batch_window_ms,
            batch_max_items=settings.stream.batch_max_items,
            path=settings.stream.path,
        )
    )

    return app


app = create_app()
