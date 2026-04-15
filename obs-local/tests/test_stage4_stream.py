from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

OBS_LOCAL_ROOT = Path(__file__).resolve().parents[1]
if str(OBS_LOCAL_ROOT) not in sys.path:
    sys.path.insert(0, str(OBS_LOCAL_ROOT))

from app.web import (
    STREAM_EVENT_BATCH,
    StreamBatcher,
    StreamHub,
    _iter_sse_events,
    build_stream_envelope,
    encode_sse_event,
)
from app.main import create_app
from app.schemas import AppConfig, ProjectConfig, SourceConfig, StorageConfig


class _FakeRequest:
    def __init__(self) -> None:
        self._disconnected = False

    async def is_disconnected(self) -> bool:
        return self._disconnected

    def disconnect(self) -> None:
        self._disconnected = True


def _payload(timestamp: str, event: str, **fields: object) -> dict[str, object]:
    payload: dict[str, object] = {"timestamp": timestamp, "event": event}
    payload.update(fields)
    return payload


def _write_jsonl(log_path: Path, payloads: list[dict[str, object]]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "\n".join(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) for payload in payloads) + "\n",
        encoding="utf-8",
    )


def _build_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        storage=StorageConfig(state_db_path=str(tmp_path / "state" / "state.db")),
        projects=[
            ProjectConfig(
                project_id="mykms",
                display_name="mykms",
                summary_mapping={"api.ask.start": "question"},
                sources=[
                    SourceConfig(
                        source_id="main",
                        log_path=str(tmp_path / "logs" / "kms-api.log"),
                        format="jsonl",
                        timezone="Asia/Shanghai",
                        enabled=True,
                    )
                ],
            )
        ],
    )


def test_encode_sse_event_wraps_metadata_and_payload():
    envelope = build_stream_envelope(
        "overview",
        {"count": 3, "requests": 9},
        project_id="mykms",
        source_id="main",
        comment="warm cache",
        event_id="42",
        retry_ms=5000,
    )

    encoded = encode_sse_event(envelope)
    lines = encoded.strip().splitlines()

    assert lines[0] == ": warm cache"
    assert lines[1] == "id: 42"
    assert lines[2] == "retry: 5000"
    assert lines[3] == "event: overview.updated"
    assert lines[4].startswith("data: ")

    payload = json.loads(lines[4][len("data: ") :])
    assert payload["topic"] == "overview.updated"
    assert payload["scope"] == {"project_id": "mykms", "source_id": "main"}
    assert payload["payload"] == {"count": 3, "requests": 9}
    assert payload["generated_at"]


def test_stream_batcher_coalesces_burst_updates_and_keeps_latest_payload():
    batcher = StreamBatcher(window_ms=200, max_items=8)

    assert batcher.record("overview", {"count": 1}, project_id="mykms", now=0.00) == ()
    assert batcher.record("requests", {"count": 10}, project_id="mykms", now=0.05) == ()
    assert batcher.record("overview", {"count": 2}, project_id="mykms", now=0.10) == ()

    ready = batcher.drain_due(now=0.25)
    assert len(ready) == 1

    batch = ready[0]
    assert batch.event == STREAM_EVENT_BATCH
    assert batch.data["count"] == 2
    assert batch.data["topics"] == ["overview.updated", "requests.updated"]

    items = {item["topic"]: item for item in batch.data["items"]}
    assert items["overview.updated"]["data"]["payload"] == {"count": 2}
    assert items["requests.updated"]["data"]["payload"] == {"count": 10}


def test_stream_batcher_flushes_single_pending_update_without_batch_wrapper():
    batcher = StreamBatcher(window_ms=1000, max_items=8)

    assert batcher.record("health", {"status": "ok"}, project_id="mykms", now=0.00) == ()
    ready = batcher.flush(now=0.01)

    assert len(ready) == 1
    assert ready[0].event == "health.updated"
    assert ready[0].data["payload"] == {"status": "ok"}


@pytest.mark.anyio
async def test_stream_hub_fanout_and_project_filter():
    hub = StreamHub(max_queue_size=4)
    loop = asyncio.get_running_loop()
    subscriber_all = hub.subscribe(loop=loop)
    subscriber_project = hub.subscribe(loop=loop, project_id="mykms")
    subscriber_other = hub.subscribe(loop=loop, project_id="other")

    hub.publish("overview", {"count": 3}, project_id="mykms")

    event_all = await asyncio.wait_for(subscriber_all.get(), timeout=1.0)
    event_project = await asyncio.wait_for(subscriber_project.get(), timeout=1.0)
    assert event_all is not None
    assert event_all.event == "overview.updated"
    assert event_project is not None
    assert event_project.project_id == "mykms"
    assert subscriber_other.queue.empty()

    hub.unsubscribe(subscriber_all)
    hub.unsubscribe(subscriber_project)
    hub.unsubscribe(subscriber_other)
    assert hub.subscriber_count() == 0


@pytest.mark.anyio
async def test_iter_sse_events_emits_overflow_notice_and_cleans_subscription():
    hub = StreamHub(max_queue_size=1)
    request = _FakeRequest()
    iterator = _iter_sse_events(
        request,
        hub=hub,
        project_id="mykms",
        heartbeat_ms=200,
        batch_window_ms=0,
        batch_max_items=16,
    )

    connected_event = await anext(iterator)
    assert "event: live" in connected_event
    assert hub.subscriber_count() == 1

    hub.publish("overview", {"count": 1}, project_id="mykms")
    hub.publish("requests", {"count": 2}, project_id="mykms")

    overflow_event = await anext(iterator)
    assert '"status":"overflow"' in overflow_event
    assert '"reconnect":false' in overflow_event

    hub.publish("errors", {"count": 1}, project_id="mykms")
    next_event = await anext(iterator)
    assert "event: errors.updated" in next_event

    request.disconnect()
    await iterator.aclose()
    assert hub.subscriber_count() == 0


@pytest.mark.anyio
async def test_iter_sse_events_preserves_direct_payload_shape_for_runtime_updates():
    hub = StreamHub(max_queue_size=4)
    request = _FakeRequest()
    iterator = _iter_sse_events(
        request,
        hub=hub,
        project_id="mykms",
        heartbeat_ms=200,
        batch_window_ms=0,
        batch_max_items=16,
    )

    connected_event = await anext(iterator)
    assert "event: live" in connected_event

    hub.publish("requests", [{"request_id": "req-live"}], project_id="mykms")
    raw_event = await anext(iterator)
    lines = [line for line in raw_event.splitlines() if line.startswith("data: ")]
    assert lines
    payload = json.loads(lines[0][len("data: ") :])

    assert payload["topic"] == "requests.updated"
    assert payload["payload"] == [{"request_id": "req-live"}]

    request.disconnect()
    await iterator.aclose()


@pytest.mark.anyio
async def test_iter_sse_events_flushes_pending_updates_on_batch_window_before_heartbeat():
    hub = StreamHub(max_queue_size=4)
    request = _FakeRequest()
    iterator = _iter_sse_events(
        request,
        hub=hub,
        project_id="mykms",
        heartbeat_ms=10000,
        batch_window_ms=50,
        batch_max_items=16,
    )

    connected_event = await anext(iterator)
    assert "event: live" in connected_event

    hub.publish("overview", {"count": 1}, project_id="mykms")
    raw_event = await asyncio.wait_for(anext(iterator), timeout=0.5)
    assert "event: overview.updated" in raw_event

    lines = [line for line in raw_event.splitlines() if line.startswith("data: ")]
    assert lines
    payload = json.loads(lines[0][len("data: ") :])
    assert payload["topic"] == "overview.updated"
    assert payload["payload"] == {"count": 1}

    request.disconnect()
    await iterator.aclose()


@pytest.mark.anyio
async def test_iter_sse_events_disconnect_releases_subscription():
    hub = StreamHub(max_queue_size=4)
    request = _FakeRequest()
    iterator = _iter_sse_events(
        request,
        hub=hub,
        project_id="mykms",
        heartbeat_ms=200,
        batch_window_ms=0,
        batch_max_items=16,
    )

    connected_event = await anext(iterator)
    assert "event: live" in connected_event
    assert hub.subscriber_count() == 1

    request.disconnect()
    await iterator.aclose()

    assert hub.subscriber_count() == 0


@pytest.mark.anyio
async def test_reload_pushes_live_updates_to_stream_subscribers(tmp_path: Path):
    log_path = tmp_path / "logs" / "kms-api.log"
    _write_jsonl(
        log_path,
        [
            _payload(
                "2026-04-15T11:52:01.000+08:00",
                "http.request.start",
                request_id="req-1",
                method="POST",
                path="/ask",
            ),
            _payload(
                "2026-04-15T11:52:01.010+08:00",
                "query.plan.end",
                request_id="req-1",
                span_id="span-root",
                duration_ms=30,
            ),
            _payload(
                "2026-04-15T11:52:01.045+08:00",
                "http.request.end",
                request_id="req-1",
                status_code=200,
                duration_ms=45,
            ),
            _payload(
                "2026-04-15T11:52:02.000+08:00",
                "semantic.client_load.error",
                level="ERROR",
                error_type="RetrievalError",
                exception="dependency missing",
            ),
        ],
    )
    app = create_app(_build_config(tmp_path))

    with TestClient(app) as client:
        hub = app.state.stream_hub
        subscription = hub.subscribe(loop=asyncio.get_running_loop(), project_id="mykms")
        try:
            response = client.post("/api/reload", params={"project": "mykms"})
            assert response.status_code == 200

            seen_events: set[str] = set()
            for _ in range(5):
                envelope = await asyncio.wait_for(subscription.get(), timeout=1.0)
                assert envelope is not None
                seen_events.add(envelope.event)
                if {
                    "health.updated",
                    "overview.updated",
                    "requests.updated",
                    "errors.updated",
                    "stages.updated",
                }.issubset(seen_events):
                    break

            assert "health.updated" in seen_events
            assert "overview.updated" in seen_events
            assert "requests.updated" in seen_events
            assert "errors.updated" in seen_events
            assert "stages.updated" in seen_events
        finally:
            hub.unsubscribe(subscription)
