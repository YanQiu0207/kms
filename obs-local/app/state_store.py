from __future__ import annotations

import json
import sqlite3
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Mapping

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS projects (
        project_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sources (
        project_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        name TEXT NOT NULL,
        log_path TEXT NOT NULL,
        format TEXT NOT NULL DEFAULT 'jsonl',
        timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
        service_hint TEXT,
        redact_fields_json TEXT NOT NULL DEFAULT '[]',
        enabled INTEGER NOT NULL DEFAULT 1,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (project_id, source_id),
        UNIQUE(project_id, log_path),
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sources_project_id ON sources(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_sources_log_path ON sources(log_path)",
    """
    CREATE TABLE IF NOT EXISTS file_offsets (
        project_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        log_path TEXT NOT NULL,
        offset INTEGER NOT NULL DEFAULT 0,
        file_size INTEGER NOT NULL DEFAULT 0,
        mtime REAL NOT NULL DEFAULT 0.0,
        inode TEXT,
        session_id TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (project_id, source_id),
        FOREIGN KEY (project_id, source_id) REFERENCES sources(project_id, source_id) ON DELETE CASCADE,
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_file_offsets_source_id ON file_offsets(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_file_offsets_log_path ON file_offsets(log_path)",
    """
    CREATE TABLE IF NOT EXISTS source_health (
        project_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        last_event_at TEXT,
        last_error_at TEXT,
        last_error_message TEXT,
        replaying INTEGER NOT NULL DEFAULT 0,
        tailer_error TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (project_id, source_id),
        FOREIGN KEY (project_id, source_id) REFERENCES sources(project_id, source_id) ON DELETE CASCADE,
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT NOT NULL,
        snapshot_type TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_snapshots_project_type ON snapshots(project_id, snapshot_type, created_at DESC)",
)

_FILE_OFFSET_MIGRATION_SETUP_STATEMENTS = (
    "ALTER TABLE file_offsets RENAME TO file_offsets_legacy",
    """
    CREATE TABLE file_offsets (
        project_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        log_path TEXT NOT NULL,
        offset INTEGER NOT NULL DEFAULT 0,
        file_size INTEGER NOT NULL DEFAULT 0,
        mtime REAL NOT NULL DEFAULT 0.0,
        inode TEXT,
        session_id TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (project_id, source_id),
        FOREIGN KEY (project_id, source_id) REFERENCES sources(project_id, source_id) ON DELETE CASCADE,
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    )
    """,
)

_FILE_OFFSET_MIGRATION_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_file_offsets_source_id ON file_offsets(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_file_offsets_log_path ON file_offsets(log_path)",
)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def _json_dumps(value: object) -> str:
    def _default(item: object) -> object:
        if isinstance(item, Path):
            return str(item)
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, tuple):
            return list(item)
        return str(item)

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_default)


def _json_loads(value: str | None, default: object) -> object:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _as_text_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return tuple(str(item) for item in value if str(item).strip())
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item).strip())
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return tuple(segment.strip() for segment in text.split(",") if segment.strip())
        if isinstance(raw, list):
            return tuple(str(item) for item in raw if str(item).strip())
    return ()


@dataclass(slots=True)
class ProjectState:
    project_id: str
    name: str
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class SourceState:
    project_id: str
    source_id: str
    name: str
    log_path: str
    format: str = "jsonl"
    timezone: str = "Asia/Shanghai"
    service_hint: str | None = None
    redact_fields: tuple[str, ...] = ()
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class FileOffsetState:
    source_id: str
    project_id: str
    log_path: str
    offset: int = 0
    file_size: int = 0
    mtime: float = 0.0
    inode: str | None = None
    session_id: str | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class SourceHealthState:
    source_id: str
    project_id: str
    last_event_at: str | None = None
    last_error_at: str | None = None
    last_error_message: str | None = None
    replaying: bool = False
    tailer_error: str | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class SnapshotState:
    project_id: str
    snapshot_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None


class SQLiteStateStore:
    """SQLite-backed state store for project and source registry metadata."""

    def __init__(self, path: str | Path, *, initialize: bool = True) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
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
        with self._lock:
            with suppress(sqlite3.Error):
                self._connection.close()

    def __enter__(self) -> SQLiteStateStore:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def initialize(self) -> None:
        with self._lock:
            try:
                with self._connection:
                    self._execute_statements(_SCHEMA_STATEMENTS)
                    self._migrate_file_offsets_table()
            except sqlite3.Error as exc:
                raise RuntimeError(f"failed to initialize sqlite state store at {self.path}") from exc

    def _execute_statements(self, statements: Iterable[str]) -> None:
        for statement in statements:
            self._connection.execute(statement)

    def _migrate_file_offsets_table(self) -> None:
        columns = self._fetchall("PRAGMA table_info(file_offsets)", ())
        column_names = {str(row["name"]) for row in columns}
        if {"project_id", "source_id", "log_path"} - column_names:
            return

        primary_keys = {
            int(row["pk"]): str(row["name"])
            for row in columns
            if int(row["pk"] or 0) > 0
        }
        expected_primary_keys = {1: "project_id", 2: "source_id"}
        if primary_keys == expected_primary_keys:
            return

        savepoint_name = "file_offsets_migration"
        self._connection.execute(f"SAVEPOINT {savepoint_name}")
        try:
            self._execute_statements(_FILE_OFFSET_MIGRATION_SETUP_STATEMENTS)
            self._connection.execute(
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
                )
                SELECT
                    legacy.project_id,
                    legacy.source_id,
                    legacy.log_path,
                    legacy.offset,
                    legacy.file_size,
                    legacy.mtime,
                    legacy.inode,
                    legacy.session_id,
                    legacy.updated_at
                FROM file_offsets_legacy AS legacy
                JOIN (
                    SELECT
                        project_id,
                        source_id,
                        MAX(updated_at) AS max_updated_at
                    FROM file_offsets_legacy
                    GROUP BY project_id, source_id
                ) AS latest
                  ON legacy.project_id = latest.project_id
                 AND legacy.source_id = latest.source_id
                 AND legacy.updated_at = latest.max_updated_at
                """
            )
            self._connection.execute("DROP TABLE file_offsets_legacy")
            self._execute_statements(_FILE_OFFSET_MIGRATION_INDEX_STATEMENTS)
        except sqlite3.Error:
            self._connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
            self._connection.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            raise
        self._connection.execute(f"RELEASE SAVEPOINT {savepoint_name}")

    def upsert_project(self, project: ProjectState) -> ProjectState:
        current = _now()
        created_at = project.created_at or current
        updated_at = current
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    """
                    INSERT INTO projects (
                        project_id,
                        name,
                        enabled,
                        metadata_json,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_id) DO UPDATE SET
                        name = excluded.name,
                        enabled = excluded.enabled,
                        metadata_json = excluded.metadata_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        project.project_id,
                        project.name,
                        1 if project.enabled else 0,
                        _json_dumps(project.metadata),
                        created_at,
                        updated_at,
                    ),
                )
        except sqlite3.Error as exc:
            raise RuntimeError(f"failed to upsert project {project.project_id}") from exc
        stored = self.get_project(project.project_id)
        if stored is not None:
            return stored
        return ProjectState(
            project_id=project.project_id,
            name=project.name,
            enabled=project.enabled,
            metadata=dict(project.metadata),
            created_at=created_at,
            updated_at=updated_at,
        )

    def upsert_source(self, source: SourceState) -> SourceState:
        current = _now()
        created_at = source.created_at or current
        updated_at = current
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    """
                    INSERT INTO sources (
                        project_id,
                        source_id,
                        name,
                        log_path,
                        format,
                        timezone,
                        service_hint,
                        redact_fields_json,
                        enabled,
                        metadata_json,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_id, source_id) DO UPDATE SET
                        name = excluded.name,
                        log_path = excluded.log_path,
                        format = excluded.format,
                        timezone = excluded.timezone,
                        service_hint = excluded.service_hint,
                        redact_fields_json = excluded.redact_fields_json,
                        enabled = excluded.enabled,
                        metadata_json = excluded.metadata_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        source.project_id,
                        source.source_id,
                        source.name,
                        source.log_path,
                        source.format,
                        source.timezone,
                        source.service_hint,
                        _json_dumps(list(source.redact_fields)),
                        1 if source.enabled else 0,
                        _json_dumps(source.metadata),
                        created_at,
                        updated_at,
                    ),
                )
        except sqlite3.Error as exc:
            raise RuntimeError(f"failed to upsert source {source.project_id}/{source.source_id}") from exc
        stored = self.get_source(source.project_id, source.source_id)
        if stored is not None:
            return stored
        return SourceState(
            project_id=source.project_id,
            source_id=source.source_id,
            name=source.name,
            log_path=source.log_path,
            format=source.format,
            timezone=source.timezone,
            service_hint=source.service_hint,
            redact_fields=tuple(source.redact_fields),
            enabled=source.enabled,
            metadata=dict(source.metadata),
            created_at=created_at,
            updated_at=updated_at,
        )

    def replace_project_sources(self, project_id: str, sources: Iterable[SourceState]) -> tuple[SourceState, ...]:
        source_list = tuple(sources)
        seen_source_ids: set[str] = set()
        duplicates: set[str] = set()
        for source in source_list:
            if source.project_id != project_id:
                raise ValueError(f"source {source.source_id} does not belong to project {project_id}")
            if source.source_id in seen_source_ids:
                duplicates.add(source.source_id)
            seen_source_ids.add(source.source_id)
        if duplicates:
            duplicate_list = ", ".join(sorted(duplicates))
            raise ValueError(f"duplicate source_id values for project {project_id}: {duplicate_list}")

        source_ids = {source.source_id for source in source_list}
        try:
            with self._lock, self._connection:
                if source_ids:
                    placeholders = ",".join("?" for _ in source_ids)
                    self._connection.execute(
                        f"DELETE FROM sources WHERE project_id = ? AND source_id NOT IN ({placeholders})",
                        (project_id, *sorted(source_ids)),
                    )
                else:
                    self._connection.execute("DELETE FROM sources WHERE project_id = ?", (project_id,))
                for source in source_list:
                    current = _now()
                    created_at = source.created_at or current
                    self._connection.execute(
                        """
                        INSERT INTO sources (
                            project_id,
                            source_id,
                            name,
                            log_path,
                            format,
                            timezone,
                            service_hint,
                            redact_fields_json,
                            enabled,
                            metadata_json,
                            created_at,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(project_id, source_id) DO UPDATE SET
                            name = excluded.name,
                            log_path = excluded.log_path,
                            format = excluded.format,
                            timezone = excluded.timezone,
                            service_hint = excluded.service_hint,
                            redact_fields_json = excluded.redact_fields_json,
                            enabled = excluded.enabled,
                            metadata_json = excluded.metadata_json,
                            updated_at = excluded.updated_at
                        """,
                        (
                            source.project_id,
                            source.source_id,
                            source.name,
                            source.log_path,
                            source.format,
                            source.timezone,
                            source.service_hint,
                            _json_dumps(list(source.redact_fields)),
                            1 if source.enabled else 0,
                            _json_dumps(source.metadata),
                            created_at,
                            current,
                        ),
                    )
        except sqlite3.Error as exc:
            raise RuntimeError(f"failed to replace sources for project {project_id}") from exc
        return self.get_sources(project_id)

    def upsert_file_offset(self, record: FileOffsetState) -> FileOffsetState:
        updated_at = record.updated_at or _now()
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    """
                    INSERT INTO file_offsets (
                        log_path,
                        source_id,
                        project_id,
                        offset,
                        file_size,
                        mtime,
                        inode,
                        session_id,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_id, source_id) DO UPDATE SET
                        log_path = excluded.log_path,
                        offset = excluded.offset,
                        file_size = excluded.file_size,
                        mtime = excluded.mtime,
                        inode = excluded.inode,
                        session_id = excluded.session_id,
                        updated_at = excluded.updated_at
                    """,
                    (
                        record.log_path,
                        record.source_id,
                        record.project_id,
                        int(record.offset),
                        int(record.file_size),
                        float(record.mtime),
                        record.inode,
                        record.session_id,
                        updated_at,
                    ),
                )
        except sqlite3.Error as exc:
            raise RuntimeError(f"failed to upsert file offset for {record.log_path}") from exc
        return FileOffsetState(
            source_id=record.source_id,
            project_id=record.project_id,
            log_path=record.log_path,
            offset=int(record.offset),
            file_size=int(record.file_size),
            mtime=float(record.mtime),
            inode=record.inode,
            session_id=record.session_id,
            updated_at=updated_at,
        )

    def upsert_source_health(self, record: SourceHealthState) -> SourceHealthState:
        updated_at = record.updated_at or _now()
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    """
                    INSERT INTO source_health (
                        project_id,
                        source_id,
                        last_event_at,
                        last_error_at,
                        last_error_message,
                        replaying,
                        tailer_error,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_id, source_id) DO UPDATE SET
                        last_event_at = excluded.last_event_at,
                        last_error_at = excluded.last_error_at,
                        last_error_message = excluded.last_error_message,
                        replaying = excluded.replaying,
                        tailer_error = excluded.tailer_error,
                        updated_at = excluded.updated_at
                    """,
                    (
                        record.project_id,
                        record.source_id,
                        record.last_event_at,
                        record.last_error_at,
                        record.last_error_message,
                        1 if record.replaying else 0,
                        record.tailer_error,
                        updated_at,
                    ),
                )
        except sqlite3.Error as exc:
            raise RuntimeError(f"failed to upsert source health for {record.project_id}/{record.source_id}") from exc
        return SourceHealthState(
            source_id=record.source_id,
            project_id=record.project_id,
            last_event_at=record.last_event_at,
            last_error_at=record.last_error_at,
            last_error_message=record.last_error_message,
            replaying=record.replaying,
            tailer_error=record.tailer_error,
            updated_at=updated_at,
        )

    def record_snapshot(self, project_id: str, snapshot_type: str, payload: Mapping[str, Any]) -> SnapshotState:
        created_at = _now()
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    """
                    INSERT INTO snapshots (
                        project_id,
                        snapshot_type,
                        payload_json,
                        created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (project_id, snapshot_type, _json_dumps(dict(payload)), created_at),
                )
        except sqlite3.Error as exc:
            raise RuntimeError(f"failed to record snapshot for {project_id}") from exc
        return SnapshotState(project_id=project_id, snapshot_type=snapshot_type, payload=dict(payload), created_at=created_at)

    def get_project(self, project_id: str) -> ProjectState | None:
        row = self._fetchone("SELECT * FROM projects WHERE project_id = ?", (project_id,))
        return self._row_to_project(row) if row else None

    def list_projects(self) -> tuple[ProjectState, ...]:
        rows = self._fetchall("SELECT * FROM projects ORDER BY project_id ASC", ())
        return tuple(self._row_to_project(row) for row in rows)

    def get_source(self, project_id: str, source_id: str) -> SourceState | None:
        row = self._fetchone(
            "SELECT * FROM sources WHERE project_id = ? AND source_id = ?",
            (project_id, source_id),
        )
        return self._row_to_source(row) if row else None

    def get_sources(self, project_id: str | None = None) -> tuple[SourceState, ...]:
        if project_id is None:
            rows = self._fetchall("SELECT * FROM sources ORDER BY project_id ASC, source_id ASC", ())
        else:
            rows = self._fetchall(
                "SELECT * FROM sources WHERE project_id = ? ORDER BY source_id ASC",
                (project_id,),
            )
        return tuple(self._row_to_source(row) for row in rows)

    def get_file_offset(self, project_id: str, source_id: str) -> FileOffsetState | None:
        row = self._fetchone(
            "SELECT * FROM file_offsets WHERE project_id = ? AND source_id = ?",
            (project_id, source_id),
        )
        return self._row_to_offset(row) if row else None

    def get_source_health(self, project_id: str, source_id: str) -> SourceHealthState | None:
        row = self._fetchone(
            "SELECT * FROM source_health WHERE project_id = ? AND source_id = ?",
            (project_id, source_id),
        )
        return self._row_to_health(row) if row else None

    def list_snapshots(self, project_id: str, snapshot_type: str | None = None, limit: int = 20) -> tuple[SnapshotState, ...]:
        limit = max(0, int(limit))
        if limit == 0:
            return ()
        if snapshot_type is None:
            rows = self._fetchall(
                "SELECT * FROM snapshots WHERE project_id = ? ORDER BY id DESC LIMIT ?",
                (project_id, limit),
            )
        else:
            rows = self._fetchall(
                """
                SELECT * FROM snapshots
                WHERE project_id = ? AND snapshot_type = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (project_id, snapshot_type, limit),
            )
        return tuple(self._row_to_snapshot(row) for row in rows)

    def _fetchone(self, query: str, params: tuple[object, ...]) -> sqlite3.Row | None:
        with self._lock:
            try:
                return self._connection.execute(query, params).fetchone()
            except sqlite3.Error as exc:
                raise RuntimeError("failed to query state store") from exc

    def _fetchall(self, query: str, params: tuple[object, ...]) -> list[sqlite3.Row]:
        with self._lock:
            try:
                return list(self._connection.execute(query, params).fetchall())
            except sqlite3.Error as exc:
                raise RuntimeError("failed to query state store") from exc

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> ProjectState:
        return ProjectState(
            project_id=str(row["project_id"]),
            name=str(row["name"] or row["project_id"]),
            enabled=bool(row["enabled"]),
            metadata=dict(_json_loads(row["metadata_json"], {}) or {}),
            created_at=str(row["created_at"]) if row["created_at"] is not None else None,
            updated_at=str(row["updated_at"]) if row["updated_at"] is not None else None,
        )

    @staticmethod
    def _row_to_source(row: sqlite3.Row) -> SourceState:
        return SourceState(
            project_id=str(row["project_id"]),
            source_id=str(row["source_id"]),
            name=str(row["name"] or row["source_id"]),
            log_path=str(row["log_path"] or ""),
            format=str(row["format"] or "jsonl"),
            timezone=str(row["timezone"] or "Asia/Shanghai"),
            service_hint=str(row["service_hint"]) if row["service_hint"] is not None else None,
            redact_fields=_as_text_tuple(_json_loads(row["redact_fields_json"], [])),
            enabled=bool(row["enabled"]),
            metadata=dict(_json_loads(row["metadata_json"], {}) or {}),
            created_at=str(row["created_at"]) if row["created_at"] is not None else None,
            updated_at=str(row["updated_at"]) if row["updated_at"] is not None else None,
        )

    @staticmethod
    def _row_to_offset(row: sqlite3.Row) -> FileOffsetState:
        return FileOffsetState(
            log_path=str(row["log_path"]),
            source_id=str(row["source_id"]),
            project_id=str(row["project_id"]),
            offset=int(row["offset"] or 0),
            file_size=int(row["file_size"] or 0),
            mtime=float(row["mtime"] or 0.0),
            inode=str(row["inode"]) if row["inode"] is not None else None,
            session_id=str(row["session_id"]) if row["session_id"] is not None else None,
            updated_at=str(row["updated_at"]) if row["updated_at"] is not None else None,
        )

    @staticmethod
    def _row_to_health(row: sqlite3.Row) -> SourceHealthState:
        return SourceHealthState(
            source_id=str(row["source_id"]),
            project_id=str(row["project_id"]),
            last_event_at=str(row["last_event_at"]) if row["last_event_at"] is not None else None,
            last_error_at=str(row["last_error_at"]) if row["last_error_at"] is not None else None,
            last_error_message=str(row["last_error_message"]) if row["last_error_message"] is not None else None,
            replaying=bool(row["replaying"]),
            tailer_error=str(row["tailer_error"]) if row["tailer_error"] is not None else None,
            updated_at=str(row["updated_at"]) if row["updated_at"] is not None else None,
        )

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> SnapshotState:
        return SnapshotState(
            project_id=str(row["project_id"]),
            snapshot_type=str(row["snapshot_type"]),
            payload=dict(_json_loads(row["payload_json"], {}) or {}),
            created_at=str(row["created_at"]) if row["created_at"] is not None else None,
        )


__all__ = [
    "FileOffsetState",
    "ProjectState",
    "SQLiteStateStore",
    "SnapshotState",
    "SourceHealthState",
    "SourceState",
]
