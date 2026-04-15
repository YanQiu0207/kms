from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.store.timestamp_migration import migrate_sqlite_timestamp_columns, migration_summary_payload


def _default_db_path() -> Path:
    return ROOT / "data" / "meta.db"


def _default_backup_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return ROOT / ".run-logs" / f"db-backup-{stamp}"


def _backup_sqlite_family(db_path: Path, backup_dir: Path) -> list[str]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for candidate in (db_path, db_path.with_name(db_path.name + "-wal"), db_path.with_name(db_path.name + "-shm")):
        if not candidate.exists():
            continue
        target = backup_dir / candidate.name
        shutil.copy2(candidate, target)
        copied.append(str(target))
    return copied


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate SQLite timestamp columns to local time strings.")
    parser.add_argument("--db", type=str, default=str(_default_db_path()), help="Path to SQLite database.")
    parser.add_argument("--dry-run", action="store_true", help="Scan and report without writing changes.")
    parser.add_argument(
        "--backup-dir",
        type=str,
        default=None,
        help="Optional backup directory. Defaults to a timestamped folder under .run-logs.",
    )
    parser.add_argument("--no-backup", action="store_true", help="Skip sqlite file backup before migration.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(json.dumps({"status": "error", "reason": "db_not_found", "db_path": str(db_path)}, ensure_ascii=False))
        return 1

    backups: list[str] = []
    if not args.no_backup and not args.dry_run:
        backup_dir = Path(args.backup_dir).resolve() if args.backup_dir else _default_backup_dir()
        backups = _backup_sqlite_family(db_path, backup_dir)

    stats = migrate_sqlite_timestamp_columns(db_path, dry_run=args.dry_run)
    payload = migration_summary_payload(stats, db_path=db_path, dry_run=args.dry_run)
    payload["status"] = "ok"
    if backups:
        payload["backups"] = backups
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
