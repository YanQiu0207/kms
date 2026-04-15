from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import sqlite3

from app.timefmt import format_local_datetime, parse_datetime_maybe_local


@dataclass(slots=True)
class MigrationStats:
    table: str
    column: str
    scanned: int = 0
    updated: int = 0
    skipped_null: int = 0
    unchanged: int = 0


def _iter_timestamp_targets() -> tuple[tuple[str, str, str], ...]:
    return (
        ("documents", "document_id", "updated_at"),
        ("chunks", "chunk_id", "updated_at"),
        ("ingest_log", "id", "started_at"),
        ("ingest_log", "id", "finished_at"),
    )


def migrate_sqlite_timestamp_columns(db_path: str | Path, *, dry_run: bool = False) -> list[MigrationStats]:
    path = Path(db_path)
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    results: list[MigrationStats] = []

    try:
        with connection:
            for table, key_column, target_column in _iter_timestamp_targets():
                stats = MigrationStats(table=table, column=target_column)
                rows = connection.execute(
                    f"SELECT {key_column} AS row_id, {target_column} AS value FROM {table}"
                ).fetchall()
                for row in rows:
                    stats.scanned += 1
                    raw = row["value"]
                    if raw is None or str(raw).strip() == "":
                        stats.skipped_null += 1
                        continue

                    parsed = parse_datetime_maybe_local(str(raw))
                    if parsed is None:
                        stats.skipped_null += 1
                        continue
                    normalized = format_local_datetime(parsed)
                    if str(raw) == normalized:
                        stats.unchanged += 1
                        continue

                    if not dry_run:
                        connection.execute(
                            f"UPDATE {table} SET {target_column} = ? WHERE {key_column} = ?",
                            (normalized, row["row_id"]),
                        )
                    stats.updated += 1
                results.append(stats)
    finally:
        connection.close()

    return results


def migration_summary_payload(stats: list[MigrationStats], *, db_path: str | Path, dry_run: bool) -> dict[str, object]:
    return {
        "db_path": str(Path(db_path).resolve()),
        "dry_run": dry_run,
        "tables": [asdict(item) for item in stats],
        "updated_total": sum(item.updated for item in stats),
        "scanned_total": sum(item.scanned for item in stats),
    }
