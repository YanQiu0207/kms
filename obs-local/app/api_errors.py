from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, HTTPException, Query, Request

from .aggregator import AggregationResult

router = APIRouter(tags=["errors"])


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _result_payload(result: AggregationResult | Mapping[str, object] | None) -> dict[str, object]:
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


def _filter_errors(
    items: list[object],
    *,
    project_id: str | None = None,
    path: str | None = None,
    error_type: str | None = None,
    status_code: int | None = None,
    request_id: str | None = None,
) -> list[dict[str, object]]:
    filtered: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if project_id is not None and _clean_text(item.get("project_id")) != _clean_text(project_id):
            continue
        if path is not None and _clean_text(item.get("path")) != _clean_text(path):
            continue
        if error_type is not None and _clean_text(item.get("error_type")) != _clean_text(error_type):
            continue
        if status_code is not None:
            item_status_code = item.get("status_code")
            if item_status_code is None or int(item_status_code) != int(status_code):
                continue
        if request_id is not None and _clean_text(item.get("request_id")) != _clean_text(request_id):
            continue
        filtered.append(dict(item))
    return filtered


def build_errors_payload(
    result: AggregationResult | Mapping[str, object],
    *,
    project_id: str | None = None,
    limit: int = 50,
    path: str | None = None,
    error_type: str | None = None,
    status_code: int | None = None,
    request_id: str | None = None,
) -> dict[str, object]:
    payload = _result_payload(result)
    errors = _filter_errors(
        list(payload.get("errors") or []),
        project_id=project_id,
        path=path,
        error_type=error_type,
        status_code=status_code,
        request_id=request_id,
    )
    limit = max(0, int(limit))
    return {
        "project_id": project_id,
        "limit": limit,
        "count": len(errors),
        "filters": {
            "path": path,
            "error_type": error_type,
            "status_code": status_code,
            "request_id": request_id,
        },
        "items": errors[:limit],
    }


@router.get("/api/errors")
def list_errors(
    request: Request,
    project: str | None = Query(default=None),
    limit: int = Query(default=50, ge=0, le=500),
    path: str | None = Query(default=None),
    error_type: str | None = Query(default=None),
    status_code: int | None = Query(default=None),
    request_id: str | None = Query(default=None),
    window: str | None = Query(default=None),
) -> dict[str, object]:
    result = _resolve_aggregation_result(request, project_id=project, window=window)
    return build_errors_payload(
        result,
        project_id=project,
        limit=limit,
        path=path,
        error_type=error_type,
        status_code=status_code,
        request_id=request_id,
    )


__all__ = [
    "build_errors_payload",
    "router",
]
