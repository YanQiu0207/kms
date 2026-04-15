from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Iterable, Mapping

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse


STREAM_EVENT_LIVE = "live"
STREAM_EVENT_HEALTH = "health.updated"
STREAM_EVENT_OVERVIEW = "overview.updated"
STREAM_EVENT_REQUESTS = "requests.updated"
STREAM_EVENT_ERRORS = "errors.updated"
STREAM_EVENT_STAGES = "stages.updated"
STREAM_EVENT_REPLAY = "replay.progress"
STREAM_EVENT_BATCH = "stream.batch"
STREAM_EVENT_HEARTBEAT = "stream.heartbeat"

STREAM_UPDATE_EVENT_NAMES = {
    "live": STREAM_EVENT_LIVE,
    "health": STREAM_EVENT_HEALTH,
    "overview": STREAM_EVENT_OVERVIEW,
    "requests": STREAM_EVENT_REQUESTS,
    "errors": STREAM_EVENT_ERRORS,
    "stages": STREAM_EVENT_STAGES,
    "replay": STREAM_EVENT_REPLAY,
}


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    else:
        text = str(value).strip()
    return text or None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().astimezone().isoformat(timespec="milliseconds")


def _serialize_value(value: Any) -> Any:
    if is_dataclass(value):
        return {
            field.name: _serialize_value(getattr(value, field.name))
            for field in fields(value)
            if not field.name.startswith("_")
        }
    if isinstance(value, datetime):
        return value.astimezone().isoformat(timespec="milliseconds")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _serialize_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_serialize_value(item) for item in value]
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, set):
        return [_serialize_value(item) for item in sorted(value, key=str)]
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(_serialize_value(value), ensure_ascii=False, separators=(",", ":"))


def _normalize_update_event_name(kind: str) -> str:
    cleaned = _clean_text(kind)
    if cleaned is None:
        raise ValueError("event kind cannot be empty")
    mapped = STREAM_UPDATE_EVENT_NAMES.get(cleaned)
    if mapped is not None:
        return mapped
    if cleaned in {
        STREAM_EVENT_LIVE,
        STREAM_EVENT_HEALTH,
        STREAM_EVENT_OVERVIEW,
        STREAM_EVENT_REQUESTS,
        STREAM_EVENT_ERRORS,
        STREAM_EVENT_STAGES,
        STREAM_EVENT_REPLAY,
        STREAM_EVENT_BATCH,
        STREAM_EVENT_HEARTBEAT,
    }:
        return cleaned
    return cleaned


def _scope_payload(project_id: str | None = None, source_id: str | None = None) -> dict[str, str | None]:
    return {"project_id": _clean_text(project_id), "source_id": _clean_text(source_id)}


def _is_overflow_notice(envelope: StreamEnvelope) -> bool:
    if envelope.event != STREAM_EVENT_LIVE:
        return False
    if not isinstance(envelope.data, Mapping):
        return False
    payload = envelope.data.get("payload")
    return isinstance(payload, Mapping) and payload.get("status") == "overflow"


@dataclass(slots=True)
class StreamEnvelope:
    event: str
    data: Any = None
    id: str | None = None
    retry_ms: int | None = None
    comment: str | None = None
    generated_at: datetime = field(default_factory=_now)
    project_id: str | None = None
    source_id: str | None = None
    topic: str | None = None
    batch_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "id": self.id,
            "retry_ms": self.retry_ms,
            "comment": self.comment,
            "generated_at": self.generated_at.astimezone().isoformat(timespec="milliseconds"),
            "project_id": _clean_text(self.project_id),
            "source_id": _clean_text(self.source_id),
            "topic": _clean_text(self.topic) or self.event,
            "batch_id": _clean_text(self.batch_id),
            "data": _serialize_value(self.data),
        }


def build_stream_envelope(
    kind: str,
    payload: Any | None = None,
    *,
    project_id: str | None = None,
    source_id: str | None = None,
    comment: str | None = None,
    retry_ms: int | None = None,
    event_id: str | None = None,
    generated_at: datetime | None = None,
    batch_id: str | None = None,
) -> StreamEnvelope:
    event = _normalize_update_event_name(kind)
    created_at = generated_at or _now()
    return StreamEnvelope(
        event=event,
        data={
            "topic": event,
            "scope": _scope_payload(project_id=project_id, source_id=source_id),
            "generated_at": created_at.astimezone().isoformat(timespec="milliseconds"),
            "payload": _serialize_value(payload),
        },
        id=event_id,
        retry_ms=retry_ms,
        comment=_clean_text(comment),
        generated_at=created_at,
        project_id=_clean_text(project_id),
        source_id=_clean_text(source_id),
        topic=event,
        batch_id=_clean_text(batch_id),
    )


def encode_sse_event(envelope: StreamEnvelope) -> str:
    lines: list[str] = []
    if envelope.comment is not None:
        for line in envelope.comment.splitlines() or [""]:
            lines.append(f": {line}")
    if envelope.id is not None:
        lines.append(f"id: {envelope.id}")
    if envelope.retry_ms is not None:
        lines.append(f"retry: {int(envelope.retry_ms)}")
    lines.append(f"event: {envelope.event}")
    payload = _json_dumps(envelope.data)
    for line in payload.splitlines() or [""]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def encode_sse_comment(comment: str) -> str:
    return encode_sse_event(
        StreamEnvelope(
            event=STREAM_EVENT_HEARTBEAT,
            data={"generated_at": _now_iso(), "payload": None},
            comment=comment,
        )
    )


@dataclass(slots=True)
class StreamSubscription:
    subscription_id: int
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[StreamEnvelope | None]
    project_id: str | None = None
    topics: frozenset[str] | None = None
    closed: bool = False
    overflowed: bool = False

    def matches(self, envelope: StreamEnvelope) -> bool:
        if self.closed:
            return False
        if self.project_id is not None and _clean_text(envelope.project_id) != self.project_id:
            return False
        if self.topics is None:
            return True
        topic = _clean_text(envelope.topic) or envelope.event
        return topic in self.topics or envelope.event in self.topics

    def offer(self, envelope: StreamEnvelope) -> None:
        if self.closed:
            return
        try:
            self.loop.call_soon_threadsafe(self._offer_nowait, envelope)
        except RuntimeError:
            self.closed = True

    def _offer_nowait(self, envelope: StreamEnvelope) -> None:
        if self.closed:
            return
        if self.queue.full():
            self._handle_overflow()
            return
        self.queue.put_nowait(envelope)

    def _handle_overflow(self) -> None:
        if self.closed or self.overflowed:
            return
        dropped_events = self.queue.qsize() + 1
        while True:
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.queue.put_nowait(
            build_stream_envelope(
                "live",
                {
                    "status": "overflow",
                    "reason": "subscriber_backpressure",
                    "dropped_events": dropped_events,
                    "reconnect": False,
                    "action": "resync_recommended",
                },
                project_id=self.project_id,
                comment="sse overflow",
            )
        )
        self.overflowed = True

    def _close_nowait(self) -> None:
        if self.closed:
            return
        self.closed = True
        while True:
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.queue.put_nowait(None)

    def close(self) -> None:
        try:
            self.loop.call_soon_threadsafe(self._close_nowait)
        except RuntimeError:
            self.closed = True

    async def get(self) -> StreamEnvelope | None:
        item = await self.queue.get()
        if item is not None and _is_overflow_notice(item):
            self.overflowed = False
        return item


class StreamHub:
    """Thread-safe pub/sub hub for SSE updates."""

    def __init__(self, *, max_queue_size: int) -> None:
        self._lock = threading.RLock()
        self._subscribers: dict[int, StreamSubscription] = {}
        self._next_subscription_id = 1
        self._sequence = 0
        self._max_queue_size = max(1, int(max_queue_size))

    def subscribe(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        project_id: str | None = None,
        topics: Iterable[str] | None = None,
    ) -> StreamSubscription:
        topic_set = frozenset(_normalize_update_event_name(topic) for topic in topics) if topics is not None else None
        with self._lock:
            subscription_id = self._next_subscription_id
            self._next_subscription_id += 1
            subscription = StreamSubscription(
                subscription_id=subscription_id,
                loop=loop,
                queue=asyncio.Queue(maxsize=self._max_queue_size),
                project_id=_clean_text(project_id),
                topics=topic_set,
            )
            self._subscribers[subscription_id] = subscription
            return subscription

    def unsubscribe(self, subscription: StreamSubscription) -> None:
        with self._lock:
            self._subscribers.pop(subscription.subscription_id, None)
        subscription.close()

    def publish(
        self,
        kind: str | StreamEnvelope,
        payload: Any | None = None,
        *,
        project_id: str | None = None,
        source_id: str | None = None,
        comment: str | None = None,
        retry_ms: int | None = None,
    ) -> StreamEnvelope:
        if isinstance(kind, StreamEnvelope):
            envelope = kind
        else:
            envelope = build_stream_envelope(
                kind,
                payload,
                project_id=project_id,
                source_id=source_id,
                comment=comment,
                retry_ms=retry_ms,
            )

        with self._lock:
            self._sequence += 1
            if envelope.id is None:
                envelope.id = str(self._sequence)
            subscribers = tuple(self._subscribers.values())

        for subscription in subscribers:
            if subscription.matches(envelope):
                subscription.offer(envelope)
        return envelope

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def close(self) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers.values())
            self._subscribers.clear()
        for subscription in subscribers:
            subscription.close()


class StreamBatcher:
    """Coalesce bursty updates into batch events."""

    def __init__(
        self,
        *,
        window_ms: int,
        max_items: int,
    ) -> None:
        self.window_ms = max(0, int(window_ms))
        self.max_items = max(1, int(max_items))
        self._pending: dict[tuple[str | None, str | None, str], StreamEnvelope] = {}
        self._first_pending_at: float | None = None
        self._batch_sequence = 0

    def record(
        self,
        kind: str,
        payload: Any | None = None,
        *,
        project_id: str | None = None,
        source_id: str | None = None,
        now: float | None = None,
    ) -> tuple[StreamEnvelope, ...]:
        envelope = build_stream_envelope(
            kind,
            payload,
            project_id=project_id,
            source_id=source_id,
        )
        key = (envelope.project_id, envelope.source_id, envelope.topic or envelope.event)
        current = now if now is not None else time.monotonic()
        if self._first_pending_at is None:
            self._first_pending_at = current
        self._pending[key] = envelope
        return self.drain_due(now=current)

    def record_envelope(
        self,
        envelope: StreamEnvelope,
        *,
        now: float | None = None,
    ) -> tuple[StreamEnvelope, ...]:
        key = (envelope.project_id, envelope.source_id, envelope.topic or envelope.event)
        current = now if now is not None else time.monotonic()
        if self._first_pending_at is None:
            self._first_pending_at = current
        self._pending[key] = envelope
        return self.drain_due(now=current)

    def drain_due(self, *, now: float | None = None) -> tuple[StreamEnvelope, ...]:
        if not self._pending:
            self._first_pending_at = None
            return ()
        current = now if now is not None else time.monotonic()
        if len(self._pending) < self.max_items and self._first_pending_at is not None:
            elapsed_ms = (current - self._first_pending_at) * 1000.0
            if elapsed_ms < self.window_ms:
                return ()
        return self.flush(now=current)

    def flush(self, *, now: float | None = None) -> tuple[StreamEnvelope, ...]:
        if not self._pending:
            self._first_pending_at = None
            return ()
        current = now if now is not None else time.monotonic()
        items = list(self._pending.values())
        self._pending.clear()
        self._first_pending_at = None
        if len(items) == 1:
            return (items[0],)

        self._batch_sequence += 1
        batch_id = f"batch-{int(current * 1000)}-{self._batch_sequence}"
        payload = {
            "count": len(items),
            "topics": [item.topic or item.event for item in items],
            "items": [item.to_dict() for item in items],
        }
        return (
            StreamEnvelope(
                event=STREAM_EVENT_BATCH,
                data=payload,
                generated_at=_now(),
                topic=STREAM_EVENT_BATCH,
                batch_id=batch_id,
            ),
        )

    def has_pending(self) -> bool:
        return bool(self._pending)


def publish_update(
    hub: StreamHub,
    kind: str,
    payload: Any | None = None,
    *,
    project_id: str | None = None,
    source_id: str | None = None,
    comment: str | None = None,
) -> StreamEnvelope:
    return hub.publish(
        kind,
        payload,
        project_id=project_id,
        source_id=source_id,
        comment=comment,
    )


def publish_updates(
    hub: StreamHub,
    *,
    project_id: str | None = None,
    source_id: str | None = None,
    live: Any | None = None,
    health: Any | None = None,
    overview: Any | None = None,
    requests: Any | None = None,
    errors: Any | None = None,
    stages: Any | None = None,
    replay: Any | None = None,
) -> tuple[StreamEnvelope, ...]:
    published: list[StreamEnvelope] = []
    payloads = (
        ("live", live),
        ("health", health),
        ("overview", overview),
        ("requests", requests),
        ("errors", errors),
        ("stages", stages),
        ("replay", replay),
    )
    for kind, payload in payloads:
        if payload is None:
            continue
        published.append(
            hub.publish(
                kind,
                payload,
                project_id=project_id,
                source_id=source_id,
            )
        )
    return tuple(published)


def _resolve_stream_hub(request: Request, fallback: StreamHub) -> StreamHub:
    app_state = getattr(request.app, "state", None)
    if app_state is None:
        return fallback
    hub = getattr(app_state, "stream_hub", None)
    if isinstance(hub, StreamHub):
        return hub
    return fallback


async def _iter_sse_events(
    request: Request,
    *,
    hub: StreamHub,
    project_id: str | None,
    heartbeat_ms: int,
    batch_window_ms: int,
    batch_max_items: int,
) -> AsyncIterator[str]:
    subscription = hub.subscribe(loop=asyncio.get_running_loop(), project_id=project_id)
    batcher = StreamBatcher(window_ms=batch_window_ms, max_items=batch_max_items)
    heartbeat_seconds = max(0.2, heartbeat_ms / 1000.0)
    batch_window_seconds = 0.01 if batch_window_ms <= 0 else max(0.01, batch_window_ms / 1000.0)
    try:
        yield encode_sse_event(
            build_stream_envelope(
                "live",
                {
                    "status": "connected",
                    "heartbeat_ms": heartbeat_ms,
                    "batch_window_ms": batch_window_ms,
                    "batch_max_items": batch_max_items,
                },
                project_id=project_id,
                comment="sse connected",
            )
        )
        while True:
            if await request.is_disconnected():
                break
            wait_timeout = heartbeat_seconds
            waiting_for_pending_flush = batcher.has_pending()
            if waiting_for_pending_flush:
                wait_timeout = min(wait_timeout, batch_window_seconds)
            try:
                envelope = await asyncio.wait_for(subscription.get(), timeout=wait_timeout)
            except TimeoutError:
                ready_events = batcher.drain_due()
                for ready in ready_events:
                    yield encode_sse_event(ready)
                if ready_events:
                    continue
                if waiting_for_pending_flush:
                    continue
                yield encode_sse_event(
                    build_stream_envelope(
                        "live",
                        {
                            "status": "heartbeat",
                            "project_id": project_id,
                        },
                        project_id=project_id,
                        comment="sse heartbeat",
                    )
                )
                continue

            if envelope is None:
                break

            ready_events = batcher.record_envelope(envelope)
            for ready in ready_events:
                yield encode_sse_event(ready)
        for ready in batcher.flush():
            yield encode_sse_event(ready)
    finally:
        hub.unsubscribe(subscription)


def create_stream_router(
    *,
    hub: StreamHub,
    heartbeat_ms: int,
    batch_window_ms: int,
    batch_max_items: int,
    path: str,
) -> APIRouter:
    router = APIRouter()
    stream_hub = hub

    @router.get(path, tags=["stream"])
    async def stream(
        request: Request,
        project: str | None = None,
        heartbeat_ms: int = heartbeat_ms,
        batch_window_ms: int = batch_window_ms,
        batch_max_items: int = batch_max_items,
    ) -> StreamingResponse:
        active_hub = _resolve_stream_hub(request, stream_hub)
        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(
            _iter_sse_events(
                request,
                hub=active_hub,
                project_id=project,
                heartbeat_ms=heartbeat_ms,
                batch_window_ms=batch_window_ms,
                batch_max_items=batch_max_items,
            ),
            media_type="text/event-stream",
            headers=headers,
        )

    return router
__all__ = [
    "STREAM_EVENT_BATCH",
    "STREAM_EVENT_ERRORS",
    "STREAM_EVENT_HEALTH",
    "STREAM_EVENT_HEARTBEAT",
    "STREAM_EVENT_LIVE",
    "STREAM_EVENT_OVERVIEW",
    "STREAM_EVENT_REQUESTS",
    "STREAM_EVENT_REPLAY",
    "STREAM_EVENT_STAGES",
    "STREAM_UPDATE_EVENT_NAMES",
    "StreamBatcher",
    "StreamEnvelope",
    "StreamHub",
    "StreamSubscription",
    "build_stream_envelope",
    "create_stream_router",
    "encode_sse_comment",
    "encode_sse_event",
    "publish_update",
    "publish_updates",
]
