from __future__ import annotations

import json
import sqlite3
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Sequence

from app.timefmt import format_local_datetime, parse_datetime_maybe_local

from .contracts import (
    IngestLogEntry,
    StoreError,
    StoreStats,
    StoredChunk,
    StoredDocument,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    return str(value)


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default)


def _loads_dict(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    raw = json.loads(value)
    return raw if isinstance(raw, dict) else {}


def _loads_title_path(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    raw = json.loads(value)
    if isinstance(raw, list):
        return tuple(str(item) for item in raw)
    return ()


def _parse_datetime(value: str | None) -> datetime | None:
    return parse_datetime_maybe_local(value)


class SQLiteMetadataStore:
    """SQLite-backed metadata store for documents, chunks, and ingest logs."""

    def __init__(self, path: str | Path, *, initialize: bool = True) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(self.path))
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = NORMAL")
        if initialize:
            self.initialize()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def close(self) -> None:
        with suppress(sqlite3.Error):
            self._connection.close()

    def __enter__(self) -> SQLiteMetadataStore:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def initialize(self) -> None:
        try:
            with self._connection:
                self._connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS documents (
                        document_id TEXT PRIMARY KEY,
                        file_path TEXT NOT NULL DEFAULT '',
                        content TEXT NOT NULL DEFAULT '',
                        title_path TEXT NOT NULL DEFAULT '[]',
                        source_path TEXT,
                        file_hash TEXT,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS chunks (
                        chunk_id TEXT PRIMARY KEY,
                        document_id TEXT NOT NULL,
                        chunk_index INTEGER NOT NULL DEFAULT 0,
                        file_path TEXT NOT NULL DEFAULT '',
                        content TEXT NOT NULL DEFAULT '',
                        title_path TEXT NOT NULL DEFAULT '[]',
                        token_count INTEGER NOT NULL DEFAULT 0,
                        file_hash TEXT,
                        chunker_version TEXT NOT NULL DEFAULT 'v1',
                        embedding_model TEXT NOT NULL DEFAULT '',
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE
                    );

                    CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_document_index
                    ON chunks(document_id, chunk_index);

                    CREATE INDEX IF NOT EXISTS idx_chunks_document_id
                    ON chunks(document_id);

                    CREATE TABLE IF NOT EXISTS ingest_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_id TEXT NOT NULL,
                        mode TEXT NOT NULL DEFAULT 'incremental',
                        status TEXT NOT NULL DEFAULT 'started',
                        started_at TEXT NOT NULL,
                        finished_at TEXT,
                        document_count INTEGER NOT NULL DEFAULT 0,
                        chunk_count INTEGER NOT NULL DEFAULT 0,
                        message TEXT NOT NULL DEFAULT '',
                        metadata_json TEXT NOT NULL DEFAULT '{}'
                    );
                    """
                )
        except sqlite3.Error as exc:
            raise StoreError(f"failed to initialize sqlite store at {self.path}") from exc

    def upsert_documents(self, records: Sequence[StoredDocument]) -> None:
        if not records:
            return

        try:
            with self._connection:
                self._connection.executemany(
                    """
                    INSERT INTO documents (
                        document_id,
                        file_path,
                        content,
                        title_path,
                        source_path,
                        file_hash,
                        metadata_json,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(document_id) DO UPDATE SET
                        file_path = excluded.file_path,
                        content = excluded.content,
                        title_path = excluded.title_path,
                        source_path = excluded.source_path,
                        file_hash = excluded.file_hash,
                        metadata_json = excluded.metadata_json,
                        updated_at = excluded.updated_at
                    """,
                    [
                        (
                            record.document_id,
                            record.file_path,
                            record.content,
                            _dumps(list(record.title_path)),
                            record.source_path,
                            record.file_hash,
                            _dumps(record.metadata),
                            format_local_datetime(record.updated_at or _now()),
                        )
                        for record in records
                    ],
                )
        except sqlite3.Error as exc:
            raise StoreError("failed to upsert documents") from exc

    def upsert_chunks(self, records: Sequence[StoredChunk]) -> None:
        if not records:
            return

        try:
            with self._connection:
                self._connection.executemany(
                    """
                    INSERT INTO chunks (
                        chunk_id,
                        document_id,
                        chunk_index,
                        file_path,
                        content,
                        title_path,
                        token_count,
                        file_hash,
                        chunker_version,
                        embedding_model,
                        metadata_json,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chunk_id) DO UPDATE SET
                        document_id = excluded.document_id,
                        chunk_index = excluded.chunk_index,
                        file_path = excluded.file_path,
                        content = excluded.content,
                        title_path = excluded.title_path,
                        token_count = excluded.token_count,
                        file_hash = excluded.file_hash,
                        chunker_version = excluded.chunker_version,
                        embedding_model = excluded.embedding_model,
                        metadata_json = excluded.metadata_json,
                        updated_at = excluded.updated_at
                    """,
                    [
                        (
                            record.chunk_id,
                            record.document_id,
                            record.chunk_index,
                            record.file_path,
                            record.content,
                            _dumps(list(record.title_path)),
                            record.token_count,
                            record.file_hash,
                            record.chunker_version,
                            record.embedding_model,
                            _dumps(record.metadata),
                            format_local_datetime(record.updated_at or _now()),
                        )
                        for record in records
                    ],
                )
        except sqlite3.Error as exc:
            raise StoreError("failed to upsert chunks") from exc

    def delete_documents(self, document_ids: Sequence[str]) -> None:
        if not document_ids:
            return

        try:
            with self._connection:
                self._connection.executemany(
                    "DELETE FROM documents WHERE document_id = ?",
                    [(document_id,) for document_id in document_ids],
                )
        except sqlite3.Error as exc:
            raise StoreError("failed to delete documents") from exc

    def list_chunk_ids(self, document_ids: Sequence[str] | None = None) -> Sequence[str]:
        try:
            if document_ids:
                placeholders = ", ".join("?" for _ in document_ids)
                cursor = self._connection.execute(
                    f"SELECT chunk_id FROM chunks WHERE document_id IN ({placeholders}) ORDER BY chunk_id",
                    tuple(document_ids),
                )
            else:
                cursor = self._connection.execute("SELECT chunk_id FROM chunks ORDER BY chunk_id")
        except sqlite3.Error as exc:
            raise StoreError("failed to list chunk ids") from exc

        return tuple(str(row["chunk_id"]) for row in cursor)

    def list_file_states(self) -> Sequence[dict[str, object]]:
        records: list[dict[str, object]] = []
        for document in self.iter_documents():
            metadata = dict(document.metadata)
            records.append(
                {
                    "document_id": document.document_id,
                    "file_path": document.file_path,
                    "file_hash": document.file_hash or str(metadata.get("file_hash", "")),
                    "mtime_ns": int(metadata.get("mtime_ns", 0) or 0),
                    "size": int(metadata.get("size", 0) or 0),
                    "source_id": str(metadata.get("source_id", "")),
                }
            )
        return tuple(records)

    def append_ingest_log(self, entry: IngestLogEntry) -> int:
        try:
            with self._connection:
                cursor = self._connection.execute(
                    """
                    INSERT INTO ingest_log (
                        source_id,
                        mode,
                        status,
                        started_at,
                        finished_at,
                        document_count,
                        chunk_count,
                        message,
                        metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.source_id,
                        entry.mode,
                        entry.status,
                        format_local_datetime(entry.started_at),
                        format_local_datetime(entry.finished_at) if entry.finished_at else None,
                        entry.document_count,
                        entry.chunk_count,
                        entry.message,
                        _dumps(entry.metadata),
                    ),
                )
                return int(cursor.lastrowid)
        except sqlite3.Error as exc:
            raise StoreError("failed to append ingest log") from exc

    def get_document(self, document_id: str) -> StoredDocument | None:
        row = self._fetchone("SELECT * FROM documents WHERE document_id = ?", (document_id,))
        return None if row is None else self._row_to_document(row)

    def get_chunk(self, chunk_id: str) -> StoredChunk | None:
        row = self._fetchone("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,))
        return None if row is None else self._row_to_chunk(row)

    def list_chunks_by_document(self, document_id: str) -> Sequence[StoredChunk]:
        try:
            cursor = self._connection.execute(
                "SELECT * FROM chunks WHERE document_id = ? ORDER BY chunk_index, chunk_id",
                (document_id,),
            )
        except sqlite3.Error as exc:
            raise StoreError("failed to list document chunks") from exc
        return tuple(self._row_to_chunk(row) for row in cursor)

    def iter_documents(self) -> Iterable[StoredDocument]:
        cursor = self._connection.execute("SELECT * FROM documents ORDER BY document_id")
        for row in cursor:
            yield self._row_to_document(row)

    def iter_chunks(self) -> Iterable[StoredChunk]:
        cursor = self._connection.execute("SELECT * FROM chunks ORDER BY document_id, chunk_index, chunk_id")
        for row in cursor:
            yield self._row_to_chunk(row)

    def stats(self) -> StoreStats:
        try:
            row = self._connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM documents) AS document_count,
                    (SELECT COUNT(*) FROM chunks) AS chunk_count,
                    (SELECT COUNT(*) FROM ingest_log) AS ingest_log_count,
                    (SELECT MAX(COALESCE(finished_at, started_at)) FROM ingest_log) AS last_indexed_at
                """
            ).fetchone()
        except sqlite3.Error as exc:
            raise StoreError("failed to read store stats") from exc

        if row is None:
            return StoreStats()

        return StoreStats(
            document_count=int(row["document_count"] or 0),
            chunk_count=int(row["chunk_count"] or 0),
            ingest_log_count=int(row["ingest_log_count"] or 0),
            last_indexed_at=_parse_datetime(row["last_indexed_at"]),
        )

    def _fetchone(self, query: str, params: tuple[object, ...]) -> sqlite3.Row | None:
        try:
            return self._connection.execute(query, params).fetchone()
        except sqlite3.Error as exc:
            raise StoreError("failed to read from sqlite store") from exc

    def _row_to_document(self, row: sqlite3.Row) -> StoredDocument:
        return StoredDocument(
            document_id=str(row["document_id"]),
            content=str(row["content"] or ""),
            file_path=str(row["file_path"] or ""),
            title_path=_loads_title_path(row["title_path"]),
            source_path=row["source_path"],
            file_hash=row["file_hash"],
            updated_at=_parse_datetime(row["updated_at"]),
            metadata=_loads_dict(row["metadata_json"]),
        )

    def _row_to_chunk(self, row: sqlite3.Row) -> StoredChunk:
        return StoredChunk(
            chunk_id=str(row["chunk_id"]),
            document_id=str(row["document_id"]),
            content=str(row["content"] or ""),
            file_path=str(row["file_path"] or ""),
            chunk_index=int(row["chunk_index"] or 0),
            title_path=_loads_title_path(row["title_path"]),
            token_count=int(row["token_count"] or 0),
            file_hash=row["file_hash"],
            chunker_version=str(row["chunker_version"] or "v1"),
            embedding_model=str(row["embedding_model"] or ""),
            updated_at=_parse_datetime(row["updated_at"]),
            metadata=_loads_dict(row["metadata_json"]),
        )
