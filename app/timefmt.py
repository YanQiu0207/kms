from __future__ import annotations

from datetime import datetime


def format_local_datetime(value: datetime | None = None) -> str:
    current = value or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.astimezone()
    else:
        current = current.astimezone()
    return current.isoformat(timespec="milliseconds")


def parse_datetime_maybe_local(value: str | None) -> datetime | None:
    if not value:
        return None

    text = value.strip()
    if not text:
        return None

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass

    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None
