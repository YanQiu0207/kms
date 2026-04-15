from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, HTTPException, Query, Request

from .aggregator import AggregationResult

router = APIRouter(tags=["requests"])


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


def _filter_requests(
    items: list[object],
    *,
    project_id: str | None = None,
    path: str | None = None,
    method: str | None = None,
    status: str | None = None,
    request_type: str | None = None,
) -> list[dict[str, object]]:
    filtered: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if project_id is not None and _clean_text(item.get("project_id")) != _clean_text(project_id):
            continue
        if path is not None and _clean_text(item.get("path")) != _clean_text(path):
            continue
        if method is not None and _clean_text(item.get("method")) != _clean_text(method):
            continue
        if status is not None and _clean_text(item.get("status")) != _clean_text(status):
            continue
        if request_type is not None and _clean_text(item.get("request_type")) != _clean_text(request_type):
            continue
        filtered.append(dict(item))
    return filtered


def _find_request_details(
    items: list[object],
    *,
    request_id: str,
    project_id: str | None = None,
) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    target_request_id = _clean_text(request_id)
    target_project_id = _clean_text(project_id)
    for item in items:
        if not isinstance(item, Mapping):
            continue
        summary = item.get("summary")
        if not isinstance(summary, Mapping):
            continue
        if _clean_text(summary.get("request_id")) != target_request_id:
            continue
        if target_project_id is not None and _clean_text(summary.get("project_id")) != target_project_id:
            continue
        matches.append(dict(item))
    return matches


def build_requests_payload(
    result: AggregationResult | Mapping[str, object],
    *,
    project_id: str | None = None,
    limit: int = 50,
    path: str | None = None,
    method: str | None = None,
    status: str | None = None,
    request_type: str | None = None,
) -> dict[str, object]:
    payload = _result_payload(result)
    requests = _filter_requests(
        list(payload.get("requests") or []),
        project_id=project_id,
        path=path,
        method=method,
        status=status,
        request_type=request_type,
    )
    limit = max(0, int(limit))
    return {
        "project_id": project_id,
        "limit": limit,
        "count": len(requests),
        "filters": {
            "path": path,
            "method": method,
            "status": status,
            "request_type": request_type,
        },
        "items": requests[:limit],
    }


def build_request_detail_payload(
    result: AggregationResult | Mapping[str, object],
    request_id: str,
    *,
    project_id: str | None = None,
) -> dict[str, object] | None:
    payload = _result_payload(result)
    details = _find_request_details(list(payload.get("request_details") or []), request_id=request_id, project_id=project_id)
    if not details:
        return None
    if len(details) > 1:
        return {
            "request_id": request_id,
            "project_id": project_id,
            "ambiguous": True,
            "matches": details,
        }
    detail = dict(details[0])
    summary = detail.get("summary")
    if isinstance(summary, Mapping):
        detail["project_id"] = summary.get("project_id")
        detail["request_id"] = summary.get("request_id")
    return detail


@router.get("/api/requests")
def list_requests(
    request: Request,
    project: str | None = Query(default=None),
    limit: int = Query(default=50, ge=0, le=500),
    path: str | None = Query(default=None),
    method: str | None = Query(default=None),
    status: str | None = Query(default=None),
    request_type: str | None = Query(default=None),
    window: str | None = Query(default=None),
) -> dict[str, object]:
    result = _resolve_aggregation_result(request, project_id=project, window=window)
    return build_requests_payload(
        result,
        project_id=project,
        limit=limit,
        path=path,
        method=method,
        status=status,
        request_type=request_type,
    )


@router.get("/api/requests/{request_id}")
def get_request_detail(
    request: Request,
    request_id: str,
    project: str | None = Query(default=None),
    window: str | None = Query(default=None),
) -> dict[str, object]:
    result = _resolve_aggregation_result(request, project_id=project, window=window)
    detail = build_request_detail_payload(result, request_id, project_id=project)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"request {request_id!r} not found")
    if detail.get("ambiguous"):
        raise HTTPException(status_code=409, detail=f"request {request_id!r} is ambiguous without project filter")
    return detail


__all__ = [
    "build_request_detail_payload",
    "build_requests_payload",
    "router",
]
