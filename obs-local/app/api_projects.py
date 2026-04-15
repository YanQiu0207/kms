from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from .aggregator import AggregationResult
from .registry import ProjectSpec, SourceRegistry, SourceSpec
from .schemas import ProjectConfig

router = APIRouter(tags=["projects"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resolve_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
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


def _result_payload(result: AggregationResult | Mapping[str, Any] | None) -> dict[str, Any]:
    if result is None:
        return {}
    if isinstance(result, Mapping):
        return dict(result)
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, Mapping):
            return dict(payload)
    return {}


def _resolve_registry(request: Request) -> SourceRegistry:
    registry = getattr(request.app.state, "registry", None)
    if isinstance(registry, SourceRegistry):
        return registry
    raise HTTPException(status_code=503, detail="registry is not available")


def _resolve_aggregation_result(request: Request, *, project_id: str | None = None, window: str | None = None):
    for attribute_name in ("aggregation_provider", "aggregation_result_provider", "get_aggregation_result"):
        provider = getattr(request.app.state, attribute_name, None)
        if callable(provider):
            try:
                result = provider(project_id=project_id, window=window)
            except TypeError:
                result = provider(project_id, window)
            if result is not None:
                return result
    result = getattr(request.app.state, "aggregation_result", None)
    if result is not None:
        return result
    raise HTTPException(status_code=503, detail="aggregation result provider is not available")


def _source_payload(registry: SourceRegistry, project: ProjectSpec, source: SourceSpec) -> dict[str, Any]:
    persisted = registry.store.get_source_health(project.project_id, source.source_id)
    last_event_at = persisted.last_event_at if persisted is not None else None
    status = "ok"
    staleness = "idle"
    if not source.enabled:
        staleness = "offline"
        tailer_error = None
        replaying = False
    else:
        tailer_error = persisted.tailer_error if persisted is not None else None
        replaying = persisted.replaying if persisted is not None else False
        if tailer_error:
            status = "error"
            staleness = "stale"
        elif last_event_at:
            staleness = "live"

    return {
        "project_id": project.project_id,
        "source_id": source.source_id,
        "name": source.name,
        "log_path": source.log_path,
        "format": source.format,
        "timezone": source.timezone,
        "service_hint": source.service_hint,
        "redact_fields": list(source.redact_fields),
        "enabled": source.enabled,
        "metadata": dict(source.metadata),
        "status": status,
        "staleness": staleness,
        "last_event_at": last_event_at,
        "replaying": replaying,
        "tailer_error": tailer_error,
    }


def _project_payload(registry: SourceRegistry, project: ProjectSpec) -> dict[str, Any]:
    sources = [_source_payload(registry, project, source) for source in project.sources]
    status = "ok"
    staleness = "offline" if not any(source.enabled for source in project.sources) else "idle"
    last_event_at: str | None = None
    replaying = False
    tailer_error: str | None = None

    for source in sources:
        if source["status"] == "error":
            status = "error"
        if source["staleness"] == "live":
            staleness = "live"
        elif staleness != "live" and source["staleness"] == "stale":
            staleness = "stale"
        elif staleness == "offline" and source["staleness"] == "idle":
            staleness = "idle"

        source_last_event_at = source["last_event_at"]
        if source_last_event_at and (
            last_event_at is None
            or (_parse_timestamp(source_last_event_at) or datetime.min.replace(tzinfo=timezone.utc))
            > (_parse_timestamp(last_event_at) or datetime.min.replace(tzinfo=timezone.utc))
        ):
            last_event_at = source_last_event_at
        if source["tailer_error"] and not tailer_error:
            tailer_error = source["tailer_error"]
        replaying = replaying or bool(source["replaying"])

    if status != "error" and staleness in {"idle", "stale", "offline"}:
        status = "degraded"

    return {
        "project_id": project.project_id,
        "name": project.name,
        "display_name": project.name,
        "enabled": project.enabled,
        "metadata": dict(project.metadata),
        "status": status,
        "staleness": staleness,
        "last_event_at": last_event_at,
        "replaying": replaying,
        "tailer_error": tailer_error,
        "source_count": len(sources),
        "sources": sources,
    }


def build_projects_payload(registry: SourceRegistry) -> dict[str, Any]:
    projects = [_project_payload(registry, project) for project in registry.list_projects()]
    return {
        "generated_at": _now_iso(),
        "count": len(projects),
        "projects": projects,
    }


def build_project_payload(registry: SourceRegistry, project_id: str) -> dict[str, Any] | None:
    project = registry.get_project(project_id)
    if project is None:
        return None
    return _project_payload(registry, project)


def _allowed_log_roots(request: Request, registry: SourceRegistry) -> tuple[Path, ...]:
    roots: set[Path] = {_resolve_path(Path.cwd())}

    config = getattr(request.app.state, "config", None)
    storage = getattr(config, "storage", None)
    state_db_path = getattr(storage, "state_db_path", None)
    if state_db_path:
        roots.add(_resolve_path(Path(state_db_path)).parent)

    for source in registry.list_sources():
        roots.add(_resolve_path(source.log_path).parent)

    return tuple(sorted(roots))


def _validate_project_log_paths(request: Request, registry: SourceRegistry, payload: ProjectConfig) -> None:
    allowed_roots = _allowed_log_roots(request, registry)
    for source in payload.sources:
        resolved_path = _resolve_path(source.log_path)
        if any(_is_relative_to(resolved_path, root) for root in allowed_roots):
            continue
        allowed = [str(root) for root in allowed_roots]
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"log_path {source.log_path!r} is outside allowed roots",
                "allowed_roots": allowed,
            },
        )


def register_project_from_config(registry: SourceRegistry, payload: ProjectConfig) -> dict[str, Any]:
    sources = [
        {
            "source_id": source.source_id,
            "log_path": source.log_path,
            "format": source.format,
            "timezone": source.timezone,
            "service_hint": source.service_hint,
            "redact_fields": list(source.redact_fields),
            "enabled": source.enabled,
            "metadata": {"summary_mapping": dict(payload.summary_mapping)},
        }
        for source in payload.sources
    ]
    project = registry.merge_declared_project(
        payload.project_id,
        name=payload.display_name or payload.project_id,
        enabled=payload.enabled,
        metadata={"summary_mapping": dict(payload.summary_mapping)},
        sources=sources,
    )
    return _project_payload(registry, project)


def _filter_result_payload(payload: dict[str, Any], project_id: str | None) -> dict[str, Any]:
    if project_id is None:
        return payload

    def _matches(item: Mapping[str, Any]) -> bool:
        return _clean_text(item.get("project_id")) == _clean_text(project_id)

    filtered = dict(payload)
    filtered["requests"] = [item for item in payload.get("requests", []) if isinstance(item, Mapping) and _matches(item)]
    filtered["errors"] = [item for item in payload.get("errors", []) if isinstance(item, Mapping) and _matches(item)]
    filtered["stages"] = [item for item in payload.get("stages", []) if isinstance(item, Mapping) and _matches(item)]
    filtered["request_details"] = [
        item
        for item in payload.get("request_details", [])
        if isinstance(item, Mapping)
        and isinstance(item.get("summary"), Mapping)
        and _matches(item["summary"])
    ]

    overview = dict(filtered.get("overview") or {})
    overview["scope_project_id"] = project_id
    overview["request_count"] = len(filtered["requests"])
    overview["failed_request_count"] = sum(
        1
        for item in filtered["requests"]
        if isinstance(item, Mapping)
        and (
            item.get("failed_request")
            or item.get("status") == "failed"
            or (item.get("status_code") is not None and int(item["status_code"]) >= 400)
        )
    )
    overview["partial_request_count"] = sum(1 for item in filtered["requests"] if isinstance(item, Mapping) and item.get("partial"))
    overview["error_count"] = len(filtered["errors"])
    overview["stage_count"] = len(filtered["stages"])
    filtered["overview"] = overview
    return filtered


def build_overview_payload(
    registry: SourceRegistry,
    result: AggregationResult | Mapping[str, Any],
    *,
    project_id: str | None = None,
    window: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    payload = _result_payload(result)
    filtered = _filter_result_payload(payload, project_id)
    overview = dict(filtered.get("overview") or {})
    requests = list(filtered.get("requests") or [])
    errors = list(filtered.get("errors") or [])
    stages = list(filtered.get("stages") or [])

    durations = [
        float(item["duration_ms"])
        for item in requests
        if isinstance(item, Mapping) and item.get("duration_ms") is not None
    ]
    request_p95_ms = _percentile(durations, 0.95)
    slowest_stage = stages[0] if stages else None
    scoped_project_id = project_id or _clean_text(overview.get("scope_project_id"))
    project = build_project_payload(registry, scoped_project_id) if scoped_project_id else None
    if isinstance(project, Mapping):
        staleness = project.get("staleness")
        last_event_at = project.get("last_event_at")
    else:
        project_items = [item for item in build_projects_payload(registry).get("projects", []) if isinstance(item, Mapping)]
        staleness = "offline" if project_items else "idle"
        last_event_at = None
        for item in project_items:
            item_staleness = _clean_text(item.get("staleness"))
            if item_staleness == "live":
                staleness = "live"
            elif staleness != "live" and item_staleness == "stale":
                staleness = "stale"
            elif staleness == "offline" and item_staleness == "idle":
                staleness = "idle"
            item_last_event_at = _clean_text(item.get("last_event_at"))
            if item_last_event_at and (
                last_event_at is None
                or (_parse_timestamp(item_last_event_at) or datetime.min.replace(tzinfo=timezone.utc))
                > (_parse_timestamp(last_event_at) or datetime.min.replace(tzinfo=timezone.utc))
            ):
                last_event_at = item_last_event_at

    return {
        "generated_at": _now_iso(),
        "project_id": scoped_project_id,
        "window": window,
        "overview": overview,
        "request_p95_ms": request_p95_ms,
        "slowest_stage": slowest_stage,
        "staleness": staleness,
        "last_event_at": last_event_at,
        "project": project,
        "top_requests": requests[: max(0, int(limit))],
        "top_errors": errors[: max(0, int(limit))],
        "top_stages": stages[: max(0, int(limit))],
}


def _resolve_reload_provider(request: Request):
    provider = getattr(request.app.state, "reload_provider", None)
    return provider if callable(provider) else None


def build_reload_payload(registry: SourceRegistry) -> dict[str, Any]:
    registry.reload()
    return build_projects_payload(registry)


@router.get("/api/projects")
def get_projects(request: Request) -> dict[str, Any]:
    registry = _resolve_registry(request)
    return build_projects_payload(registry)


@router.post("/api/projects")
def post_project(request: Request, payload: ProjectConfig) -> dict[str, Any]:
    registry = _resolve_registry(request)
    _validate_project_log_paths(request, registry, payload)
    return register_project_from_config(registry, payload)


@router.get("/api/overview")
def get_overview(
    request: Request,
    project: str | None = Query(default=None),
    window: str | None = Query(default=None),
    limit: int = Query(default=20, ge=0, le=200),
) -> dict[str, Any]:
    registry = _resolve_registry(request)
    if project is not None and registry.get_project(project) is None:
        raise HTTPException(status_code=404, detail=f"project {project!r} not found")
    result = _resolve_aggregation_result(request, project_id=project, window=window)
    return build_overview_payload(registry, result, project_id=project, window=window, limit=limit)


@router.post("/api/reload")
def reload_projects(request: Request, project: str | None = Query(default=None)) -> dict[str, Any]:
    registry = _resolve_registry(request)
    reload_provider = _resolve_reload_provider(request)
    if reload_provider is not None:
        try:
            reload_provider(project_id=project)
        except TypeError:
            reload_provider(project)
        payload = build_projects_payload(registry)
    else:
        payload = build_reload_payload(registry)
    if project is None:
        return payload
    project_payload = build_project_payload(registry, project)
    if project_payload is None:
        raise HTTPException(status_code=404, detail=f"project {project!r} not found")
    return {
        "generated_at": payload["generated_at"],
        "project_id": project,
        "project": project_payload,
        "reloaded": True,
    }


__all__ = [
    "build_overview_payload",
    "build_project_payload",
    "build_projects_payload",
    "build_reload_payload",
    "register_project_from_config",
    "router",
]
