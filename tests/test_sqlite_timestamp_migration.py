from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3
import subprocess
import sys

from app.store import IngestLogEntry, SQLiteMetadataStore, StoredChunk, StoredDocument
from app.store.timestamp_migration import migrate_sqlite_timestamp_columns
from app.timefmt import format_local_datetime, parse_datetime_maybe_local


def test_sqlite_store_writes_local_timestamp_strings(tmp_path: Path):
    db_path = tmp_path / "meta.db"
    store = SQLiteMetadataStore(db_path)
    instant = datetime(2026, 6, 4, 11, 25, 3, 836000, tzinfo=UTC)

    store.upsert_documents(
        [
            StoredDocument(
                document_id="doc-1",
                content="alpha",
                updated_at=instant,
            )
        ]
    )
    store.upsert_chunks(
        [
            StoredChunk(
                chunk_id="chunk-1",
                document_id="doc-1",
                content="alpha",
                updated_at=instant,
            )
        ]
    )
    store.append_ingest_log(
        IngestLogEntry(
            source_id="all",
            started_at=instant,
            finished_at=instant,
        )
    )
    store.close()

    connection = sqlite3.connect(str(db_path))
    try:
        document_time = connection.execute("SELECT updated_at FROM documents WHERE document_id = 'doc-1'").fetchone()[0]
        chunk_time = connection.execute("SELECT updated_at FROM chunks WHERE chunk_id = 'chunk-1'").fetchone()[0]
        log_times = connection.execute("SELECT started_at, finished_at FROM ingest_log").fetchone()
    finally:
        connection.close()

    expected = format_local_datetime(instant)
    assert document_time == expected
    assert chunk_time == expected
    assert log_times[0] == expected
    assert log_times[1] == expected


def test_sqlite_timestamp_migration_converts_legacy_iso_rows(tmp_path: Path):
    db_path = tmp_path / "meta.db"
    store = SQLiteMetadataStore(db_path)
    connection = store.connection
    with connection:
        connection.execute(
            "INSERT INTO documents (document_id, file_path, content, title_path, source_path, file_hash, metadata_json, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("doc-1", "", "alpha", "[]", None, None, "{}", "2026-06-04T03:25:03.836000+00:00"),
        )
        connection.execute(
            "INSERT INTO chunks (chunk_id, document_id, chunk_index, file_path, content, title_path, token_count, file_hash, chunker_version, embedding_model, metadata_json, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("chunk-1", "doc-1", 0, "", "alpha", "[]", 0, None, "v1", "", "{}", "2026-06-04T03:25:03.836000+00:00"),
        )
        connection.execute(
            "INSERT INTO ingest_log (source_id, mode, status, started_at, finished_at, document_count, chunk_count, message, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("all", "full", "completed", "2026-06-04T03:25:03.836000+00:00", "2026-06-04T03:25:05.100000+00:00", 1, 1, "", "{}"),
        )

    stats = migrate_sqlite_timestamp_columns(db_path)
    migrated_document = connection.execute("SELECT updated_at FROM documents WHERE document_id = 'doc-1'").fetchone()[0]
    migrated_chunk = connection.execute("SELECT updated_at FROM chunks WHERE chunk_id = 'chunk-1'").fetchone()[0]
    migrated_log = connection.execute("SELECT started_at, finished_at FROM ingest_log").fetchone()
    parsed_document = store.get_document("doc-1")
    store_stats = store.stats()
    store.close()

    assert sum(item.updated for item in stats) == 4
    assert migrated_document == "2026-06-04T11:25:03.836+08:00"
    assert migrated_chunk == "2026-06-04T11:25:03.836+08:00"
    assert migrated_log[0] == "2026-06-04T11:25:03.836+08:00"
    assert migrated_log[1] == "2026-06-04T11:25:05.100+08:00"
    assert parsed_document is not None
    assert parsed_document.updated_at is not None
    assert store_stats.last_indexed_at is not None


def test_migrate_script_reports_summary_and_keeps_backup(tmp_path: Path):
    db_path = tmp_path / "meta.db"
    backup_dir = tmp_path / "backup"
    store = SQLiteMetadataStore(db_path)
    with store.connection:
        store.connection.execute(
            "INSERT INTO ingest_log (source_id, mode, status, started_at, finished_at, document_count, chunk_count, message, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("all", "incremental", "completed", "2026-06-04T03:25:03.836000+00:00", None, 0, 0, "", "{}"),
        )
    store.close()

    result = subprocess.run(
        [
            sys.executable,
            "scripts/migrate_db_timestamps.py",
            "--db",
            str(db_path),
            "--backup-dir",
            str(backup_dir),
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        text=True,
        capture_output=True,
        check=True,
    )

    assert '"status": "ok"' in result.stdout
    assert backup_dir.exists()
    assert (backup_dir / "meta.db").exists()


def test_parse_datetime_returns_none_for_unknown_format():
    assert parse_datetime_maybe_local("2026/06/04 03:25:03") is None


def test_timestamp_migration_skips_unparseable_datetime_values(tmp_path: Path):
    db_path = tmp_path / "meta.db"
    store = SQLiteMetadataStore(db_path)
    with store.connection:
        store.connection.execute(
            "INSERT INTO documents (document_id, file_path, content, title_path, source_path, file_hash, metadata_json, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("doc-1", "", "alpha", "[]", None, None, "{}", "2026/06/04 03:25:03"),
        )

    stats = migrate_sqlite_timestamp_columns(db_path)
    value = store.connection.execute("SELECT updated_at FROM documents WHERE document_id = 'doc-1'").fetchone()[0]
    store.close()

    assert value == "2026/06/04 03:25:03"
    target = next(item for item in stats if item.table == "documents" and item.column == "updated_at")
    assert target.scanned == 1
    assert target.updated == 0
    assert target.skipped_null == 1
