from __future__ import annotations

from pathlib import Path
import sys

import pytest

OBS_LOCAL_ROOT = Path(__file__).resolve().parents[1]
if str(OBS_LOCAL_ROOT) not in sys.path:
    sys.path.insert(0, str(OBS_LOCAL_ROOT))

from app.parser import LogSourceContext, _parse_timestamp_details, parse_log_line
from app.registry import ProjectSpec, SourceRegistry, SourceSpec
from app.state_store import SourceState, SQLiteStateStore
from app.tailer import FileTailer

TAILER_OPTIONS = {
    "chunk_size": 64 * 1024,
    "encoding": "utf-8",
    "errors": "replace",
}


class _TailSource:
    def __init__(self, *, project_id: str, source_id: str, log_path: str, timezone: str = "Asia/Shanghai") -> None:
        self.project_id = project_id
        self.source_id = source_id
        self.log_path = log_path
        self.timezone = timezone


def test_parser_supports_multiple_timestamp_formats_and_redaction():
    source = LogSourceContext(
        project_id="mykms",
        source_id="main",
        log_path="E:/github/mykms/.run-logs/kms-api.log",
        timezone="Asia/Shanghai",
        service_hint="kms-api",
        redact_fields=("question",),
    )

    local_record = parse_log_line(
        '{"timestamp":"2026-04-15 11:52:02.389","event":"api.ask.start","question":"secret","request_id":"abc"}',
        source=source,
    )
    epoch_record = parse_log_line(
        '{"timestamp":1776234722389,"event":"http.request.end","status_code":200,"duration_ms":12.5}',
        source=source,
    )
    naive_iso_record = parse_log_line(
        '{"timestamp":"2026-04-15T11:52:02.389","event":"api.ask.end"}',
        source=source,
    )
    bad_record = parse_log_line("not-json", source=source)

    assert local_record.valid is True
    assert local_record.timestamp is not None
    assert local_record.timestamp_format == "local_datetime"
    assert local_record.attributes["question"] == "[REDACTED]"
    assert local_record.request_id == "abc"

    assert epoch_record.valid is True
    assert epoch_record.timestamp is not None
    assert epoch_record.timestamp_format == "epoch_ms"
    assert epoch_record.status == "ok"
    assert epoch_record.duration_ms == 12.5

    assert naive_iso_record.valid is True
    assert naive_iso_record.timestamp is not None
    assert naive_iso_record.timestamp_format == "iso8601_naive"

    assert bad_record.valid is False
    assert bad_record.parse_error is not None


def test_parser_supports_canonical_span_protocol_and_trace_id_fallback():
    source = LogSourceContext(
        project_id="mykms",
        source_id="main",
        log_path="E:/github/mykms/.run-logs/kms-api.log",
        timezone="Asia/Shanghai",
        service_hint="kms-api",
        redact_fields=("question",),
    )

    canonical_record = parse_log_line(
        (
            '{"timestamp":"2026-04-15T11:52:02.389+08:00","event":"start","span_name":"api.ask",'
            '"trace_id":"trace-123","span_id":"span-ask","parent_span_id":"span-root",'
            '"attributes":{"question":"secret","display_summary":"summary from attributes"}}'
        ),
        source=source,
    )

    assert canonical_record.valid is True
    assert canonical_record.timestamp is not None
    assert canonical_record.timestamp_format == "rfc3339"
    assert canonical_record.event == "start"
    assert canonical_record.event_type == "start"
    assert canonical_record.span_name == "api.ask"
    assert canonical_record.trace_id == "trace-123"
    assert canonical_record.request_id == "trace-123"
    assert canonical_record.summary == "summary from attributes"
    assert canonical_record.attributes["question"] == "[REDACTED]"


def test_parse_timestamp_details_covers_timezone_fallback_epoch_seconds_and_bool_values():
    fallback_parsed, fallback_kind, fallback_warning = _parse_timestamp_details(
        "2026-04-15 11:52:02.389",
        timezone_name="Mars/Olympus",
    )
    assert fallback_parsed is not None
    assert fallback_kind == "local_datetime"
    assert fallback_warning is not None
    assert "falling back to UTC" in fallback_warning

    epoch_seconds, epoch_kind, epoch_warning = _parse_timestamp_details(9_999_999_999, timezone_name="UTC")
    assert epoch_seconds is not None
    assert epoch_kind == "epoch_s"
    assert epoch_warning is None

    boolean_timestamp, boolean_kind, boolean_warning = _parse_timestamp_details(True, timezone_name="UTC")
    assert boolean_timestamp is None
    assert boolean_kind is None
    assert boolean_warning is not None


def test_tailer_replay_incremental_and_truncation(tmp_path: Path):
    state_store = SQLiteStateStore(tmp_path / "state.db")
    registry = SourceRegistry(state_store)
    tailer = FileTailer(state_store, **TAILER_OPTIONS)
    log_path = tmp_path / "kms-api.log"
    log_path.write_text("line-1\nline-2\nline-3\n", encoding="utf-8")
    source = _TailSource(project_id="mykms", source_id="main", log_path=str(log_path))
    registry.register_project(
        ProjectSpec(
            project_id="mykms",
            name="mykms",
            sources=(
                SourceSpec(
                    project_id="mykms",
                    source_id="main",
                    log_path=str(log_path),
                ),
            ),
        )
    )

    replay = tailer.replay(source, max_lines=2)

    assert replay.mode == "replay"
    assert replay.lines == ("line-2", "line-3")
    assert replay.persisted_offset is None

    incremental_first = tailer.incremental(source)

    assert incremental_first.mode == "incremental"
    assert incremental_first.lines == ("line-1", "line-2", "line-3")
    assert incremental_first.persisted_offset == incremental_first.end_offset

    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("line-4\n")

    incremental_second = tailer.incremental(source)

    assert incremental_second.lines == ("line-4",)
    assert incremental_second.start_offset == incremental_first.end_offset

    log_path.write_text("reset-1\n", encoding="utf-8")

    incremental_after_truncate = tailer.incremental(source)

    assert incremental_after_truncate.truncated is True
    assert incremental_after_truncate.start_offset == 0
    assert incremental_after_truncate.lines == ("reset-1",)


def test_tailer_keeps_offsets_isolated_when_projects_share_same_log_path(tmp_path: Path):
    state_store = SQLiteStateStore(tmp_path / "state.db")
    registry = SourceRegistry(state_store)
    tailer = FileTailer(state_store, **TAILER_OPTIONS)
    log_path = tmp_path / "shared.log"
    log_path.write_text("line-1\n", encoding="utf-8")

    for project_id in ("proj-a", "proj-b"):
        registry.register_project(
            ProjectSpec(
                project_id=project_id,
                name=project_id,
                sources=(
                    SourceSpec(
                        project_id=project_id,
                        source_id="main",
                        log_path=str(log_path),
                    ),
                ),
            )
        )

    source_a = _TailSource(project_id="proj-a", source_id="main", log_path=str(log_path))
    source_b = _TailSource(project_id="proj-b", source_id="main", log_path=str(log_path))

    first_a = tailer.incremental(source_a)
    assert first_a.lines == ("line-1",)
    assert tailer.load_offset(source_a) is not None
    assert tailer.load_offset(source_b) is None

    first_b = tailer.incremental(source_b)
    assert first_b.lines == ("line-1",)
    assert tailer.load_offset(source_b) is not None

    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("line-2\n")

    second_a = tailer.incremental(source_a)
    second_b = tailer.incremental(source_b)

    assert second_a.lines == ("line-2",)
    assert second_b.lines == ("line-2",)
    assert second_a.start_offset == first_a.end_offset
    assert second_b.start_offset == first_b.end_offset


def test_tailer_retries_trailing_partial_line_until_it_is_completed(tmp_path: Path):
    state_store = SQLiteStateStore(tmp_path / "state.db")
    registry = SourceRegistry(state_store)
    tailer = FileTailer(state_store, **TAILER_OPTIONS)
    log_path = tmp_path / "partial.log"
    source = _TailSource(project_id="mykms", source_id="main", log_path=str(log_path))
    registry.register_project(
        ProjectSpec(
            project_id="mykms",
            name="mykms",
            sources=(
                SourceSpec(
                    project_id="mykms",
                    source_id="main",
                    log_path=str(log_path),
                ),
            ),
        )
    )

    log_path.write_text("line-1\npartial", encoding="utf-8")

    first = tailer.incremental(source)
    assert first.lines == ("line-1",)
    assert first.persisted_offset == first.end_offset
    assert first.end_offset < log_path.stat().st_size

    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("-line\n")

    second = tailer.incremental(source)
    assert second.lines == ("partial-line",)
    assert second.start_offset == first.end_offset


def test_tailer_replay_handles_single_line_without_newline(tmp_path: Path):
    state_store = SQLiteStateStore(tmp_path / "state.db")
    tailer = FileTailer(state_store, chunk_size=8, encoding="utf-8", errors="replace")
    log_path = tmp_path / "single-line.log"
    source = _TailSource(project_id="mykms", source_id="main", log_path=str(log_path))
    log_path.write_text("single-line", encoding="utf-8")

    replay = tailer.replay(source, max_lines=1)

    assert replay.lines == ("single-line",)
    assert replay.start_offset == 0


def test_tailer_replay_keeps_last_line_when_file_has_no_trailing_newline(tmp_path: Path):
    state_store = SQLiteStateStore(tmp_path / "state.db")
    tailer = FileTailer(state_store, chunk_size=8, encoding="utf-8", errors="replace")
    log_path = tmp_path / "missing-trailing-newline.log"
    source = _TailSource(project_id="mykms", source_id="main", log_path=str(log_path))
    log_path.write_text("line-1\nline-2", encoding="utf-8")

    replay = tailer.replay(source, max_lines=1)

    assert replay.lines == ("line-2",)


def test_state_store_migration_rolls_back_when_file_offsets_upgrade_fails(tmp_path: Path):
    store = SQLiteStateStore(tmp_path / "state.db", initialize=False)

    with store.connection:
        store.connection.execute(
            """
            CREATE TABLE file_offsets (
                project_id TEXT,
                source_id TEXT,
                log_path TEXT NOT NULL PRIMARY KEY,
                offset INTEGER NOT NULL DEFAULT 0,
                file_size INTEGER NOT NULL DEFAULT 0,
                mtime REAL NOT NULL DEFAULT 0.0,
                inode TEXT,
                session_id TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        store.connection.execute(
            """
            INSERT INTO file_offsets (
                project_id,
                source_id,
                log_path,
                offset,
                file_size,
                mtime,
                inode,
                session_id,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("proj-a", "main", "bad.log", 0, 0, 0.0, None, None, "2026-04-15T11:52:01+08:00"),
        )

    with pytest.raises(RuntimeError, match="failed to initialize sqlite state store"):
        store.initialize()

    table_names = {
        str(row[0])
        for row in store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('file_offsets', 'file_offsets_legacy')"
        ).fetchall()
    }
    assert table_names == {"file_offsets"}

    columns = {
        str(row[1]): int(row[5] or 0)
        for row in store.connection.execute("PRAGMA table_info(file_offsets)").fetchall()
    }
    assert columns.get("log_path") == 1
    assert columns.get("project_id") == 0

    store.close()


def test_replace_project_sources_rejects_duplicate_source_ids(tmp_path: Path):
    state_store = SQLiteStateStore(tmp_path / "state.db")
    registry = SourceRegistry(state_store)
    registry.register_project(ProjectSpec(project_id="mykms", name="mykms"))

    with pytest.raises(ValueError, match="duplicate source_id"):
        state_store.replace_project_sources(
            "mykms",
            (
                SourceState(project_id="mykms", source_id="main", name="Main A", log_path="a.log"),
                SourceState(project_id="mykms", source_id="main", name="Main B", log_path="b.log"),
            ),
        )
