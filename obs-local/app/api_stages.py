from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, HTTPException, Query, Request

from .aggregator import AggregationResult

router = APIRouter(tags=["stages"])


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


def _filter_stages(
    items: list[object],
    *,
    project_id: str | None = None,
    stage: str | None = None,
) -> list[dict[str, object]]:
    filtered: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if project_id is not None and _clean_text(item.get("project_id")) != _clean_text(project_id):
            continue
        if stage is not None and _clean_text(item.get("stage")) != _clean_text(stage):
            continue
        filtered.append(dict(item))
    return filtered


def build_stages_payload(
    result: AggregationResult | Mapping[str, object],
    *,
    project_id: str | None = None,
    limit: int = 50,
    stage: str | None = None,
    window: str | None = None,
) -> dict[str, object]:
    payload = _result_payload(result)
    stages = _filter_stages(
        list(payload.get("stages") or []),
        project_id=project_id,
        stage=stage,
    )
    limit = max(0, int(limit))
    return {
        "project_id": project_id,
        "window": window,
        "limit": limit,
        "count": len(stages),
        "filters": {
            "stage": stage,
        },
        "items": stages[:limit],
    }


@router.get("/api/stages")
def list_stages(
    request: Request,
    project: str | None = Query(default=None),
    window: str | None = Query(default=None),
    limit: int = Query(default=50, ge=0, le=500),
    stage: str | None = Query(default=None),
) -> dict[str, object]:
    result = _resolve_aggregation_result(request, project_id=project, window=window)
    return build_stages_payload(
        result,
        project_id=project,
        limit=limit,
        stage=stage,
        window=window,
    )


__all__ = [
    "build_stages_payload",
    "router",
]
