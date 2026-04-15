from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from .state_store import FileOffsetState, SQLiteStateStore

TailMode = Literal["replay", "incremental"]


class TailSource(Protocol):
    project_id: str
    source_id: str
    log_path: str
    timezone: str


@dataclass(slots=True)
class TailPlan:
    project_id: str
    source_id: str
    log_path: str
    mode: TailMode
    file_size: int
    file_mtime: float
    inode: str | None
    session_id: str
    stored_offset: int | None
    start_offset: int
    read_limit: int | None
    truncated: bool
    replaying: bool


@dataclass(slots=True)
class TailReadResult:
    project_id: str
    source_id: str
    log_path: str
    mode: TailMode
    lines: tuple[str, ...]
    raw_text: str
    start_offset: int
    end_offset: int
    file_size: int
    file_mtime: float
    inode: str | None
    session_id: str
    stored_offset: int | None
    persisted_offset: int | None
    truncated: bool
    replaying: bool
    partial_line_skipped: bool
    window_lines: int | None
    window_bytes: int | None


class TailerError(RuntimeError):
    pass


class FileTailer:
    def __init__(
        self,
        state_store: SQLiteStateStore,
        *,
        chunk_size: int,
        encoding: str,
        errors: str,
    ) -> None:
        self._store = state_store
        self._chunk_size = max(1024, int(chunk_size))
        self._encoding = encoding
        self._errors = errors

    def plan(
        self,
        source: TailSource,
        *,
        mode: TailMode = "incremental",
        max_lines: int | None = None,
        max_bytes: int | None = None,
    ) -> TailPlan:
        log_path = Path(source.log_path).expanduser()
        stat = self._stat_log_file(log_path)
        file_size = int(stat.st_size)
        file_mtime = float(stat.st_mtime)
        inode = self._stat_inode(stat)
        session_id = self._build_session_id(inode, file_size, file_mtime)

        stored = self._store.get_file_offset(source.project_id, source.source_id)
        stored_offset = stored.offset if stored is not None else None
        truncated = self._is_truncated(stored, file_size, inode)

        if mode == "incremental":
            start_offset = 0 if truncated or stored_offset is None else min(int(stored_offset), file_size)
            read_limit = None
            replaying = False
        else:
            start_offset = self._resolve_replay_start(
                log_path=log_path,
                file_size=file_size,
                max_lines=max_lines,
                max_bytes=max_bytes,
            )
            read_limit = None
            replaying = True

        if max_bytes is not None and max_bytes > 0:
            read_limit = max_bytes if read_limit is None else min(read_limit, max_bytes)

        return TailPlan(
            project_id=source.project_id,
            source_id=source.source_id,
            log_path=str(log_path),
            mode=mode,
            file_size=file_size,
            file_mtime=file_mtime,
            inode=inode,
            session_id=session_id,
            stored_offset=stored_offset,
            start_offset=start_offset,
            read_limit=read_limit,
            truncated=truncated,
            replaying=replaying,
        )

    def read(
        self,
        source: TailSource,
        *,
        mode: TailMode = "incremental",
        max_lines: int | None = None,
        max_bytes: int | None = None,
        persist_offset: bool | None = None,
    ) -> TailReadResult:
        plan = self.plan(source, mode=mode, max_lines=max_lines, max_bytes=max_bytes)
        if persist_offset is None:
            persist_offset = mode == "incremental"
        return self._execute_plan(
            source=source,
            plan=plan,
            max_lines=max_lines,
            max_bytes=max_bytes,
            persist_offset=persist_offset,
        )

    def replay(
        self,
        source: TailSource,
        *,
        max_lines: int | None = None,
        max_bytes: int | None = None,
    ) -> TailReadResult:
        return self.read(
            source,
            mode="replay",
            max_lines=max_lines,
            max_bytes=max_bytes,
            persist_offset=False,
        )

    def incremental(
        self,
        source: TailSource,
        *,
        max_bytes: int | None = None,
        persist_offset: bool = True,
    ) -> TailReadResult:
        return self.read(
            source,
            mode="incremental",
            max_bytes=max_bytes,
            persist_offset=persist_offset,
        )

    def load_offset(self, source: TailSource) -> FileOffsetState | None:
        return self._store.get_file_offset(source.project_id, source.source_id)

    def _execute_plan(
        self,
        *,
        source: TailSource,
        plan: TailPlan,
        max_lines: int | None,
        max_bytes: int | None,
        persist_offset: bool,
    ) -> TailReadResult:
        start_offset, partial_line_skipped, raw_bytes = self._read_from_start(
            Path(plan.log_path),
            plan.start_offset,
            file_size=plan.file_size,
            max_bytes=plan.read_limit,
        )

        if plan.mode == "replay" and max_lines is not None and max_lines > 0:
            raw_bytes = self._trim_tail_lines(raw_bytes, max_lines)

        if plan.mode == "incremental":
            raw_bytes = self._trim_trailing_incomplete_line(raw_bytes)

        text = raw_bytes.decode(self._encoding, errors=self._errors)
        lines = tuple(text.splitlines())
        end_offset = start_offset + len(raw_bytes)

        persisted_offset = None
        if persist_offset and plan.mode == "incremental":
            stored = self._store.upsert_file_offset(
                FileOffsetState(
                    source_id=source.source_id,
                    project_id=source.project_id,
                    log_path=plan.log_path,
                    offset=end_offset,
                    file_size=plan.file_size,
                    mtime=plan.file_mtime,
                    inode=plan.inode,
                    session_id=plan.session_id,
                )
            )
            persisted_offset = stored.offset

        return TailReadResult(
            project_id=source.project_id,
            source_id=source.source_id,
            log_path=plan.log_path,
            mode=plan.mode,
            lines=lines,
            raw_text=text,
            start_offset=start_offset,
            end_offset=end_offset,
            file_size=plan.file_size,
            file_mtime=plan.file_mtime,
            inode=plan.inode,
            session_id=plan.session_id,
            stored_offset=plan.stored_offset,
            persisted_offset=persisted_offset,
            truncated=plan.truncated,
            replaying=plan.replaying,
            partial_line_skipped=partial_line_skipped,
            window_lines=max_lines,
            window_bytes=max_bytes,
        )

    def _resolve_replay_start(
        self,
        *,
        log_path: Path,
        file_size: int,
        max_lines: int | None,
        max_bytes: int | None,
    ) -> int:
        start_offset = 0
        if max_bytes is not None and max_bytes > 0:
            start_offset = max(start_offset, max(0, file_size - max_bytes))
        if max_lines is not None and max_lines > 0:
            start_offset = max(start_offset, self._find_start_for_last_lines(log_path, file_size, max_lines))
        return min(start_offset, file_size)

    def _find_start_for_last_lines(self, log_path: Path, file_size: int, max_lines: int) -> int:
        if max_lines <= 0 or file_size <= 0:
            return 0

        with log_path.open("rb") as handle:
            read_end = file_size
            chunks: list[bytes] = []
            newline_count = 0
            while read_end > 0 and newline_count <= max_lines:
                read_size = min(self._chunk_size, read_end)
                read_end -= read_size
                handle.seek(read_end)
                chunk = handle.read(read_size)
                if not chunk:
                    break
                chunks.append(chunk)
                newline_count += chunk.count(b"\n")

            if read_end <= 0:
                return 0

            buffer = b"".join(reversed(chunks))
            handle.seek(read_end - 1)
            previous = handle.read(1)
            prefix_offset = 0
            if previous not in {b"\n", b"\r"} and buffer:
                first_newline = buffer.find(b"\n")
                if first_newline < 0:
                    return file_size
                buffer = buffer[first_newline + 1 :]
                prefix_offset = first_newline + 1

            lines = buffer.splitlines(keepends=True)
            if len(lines) <= max_lines:
                return read_end + prefix_offset

            leading_bytes = b"".join(lines[:-max_lines])
            return read_end + prefix_offset + len(leading_bytes)

    def _read_from_start(
        self,
        log_path: Path,
        start_offset: int,
        *,
        file_size: int,
        max_bytes: int | None,
    ) -> tuple[int, bool, bytes]:
        with log_path.open("rb") as handle:
            handle.seek(start_offset)
            partial_line_skipped = False
            if start_offset > 0:
                previous = self._peek_previous_byte(handle, start_offset)
                handle.seek(start_offset)
                if previous not in {b"\n", b"\r"}:
                    handle.readline()
                    start_offset = handle.tell()
                    partial_line_skipped = True

            remaining = file_size - start_offset
            if max_bytes is not None and max_bytes >= 0:
                remaining = min(remaining, max_bytes)

            chunks: list[bytes] = []
            while remaining > 0:
                read_size = min(self._chunk_size, remaining)
                chunk = handle.read(read_size)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)

        return start_offset, partial_line_skipped, b"".join(chunks)

    @staticmethod
    def _trim_trailing_incomplete_line(raw_bytes: bytes) -> bytes:
        if not raw_bytes:
            return raw_bytes
        if raw_bytes.endswith((b"\n", b"\r")):
            return raw_bytes
        last_newline = max(raw_bytes.rfind(b"\n"), raw_bytes.rfind(b"\r"))
        if last_newline < 0:
            return b""
        return raw_bytes[: last_newline + 1]

    @staticmethod
    def _peek_previous_byte(handle, start_offset: int) -> bytes:
        handle.seek(start_offset - 1)
        return handle.read(1)

    @staticmethod
    def _trim_tail_lines(raw_bytes: bytes, max_lines: int) -> bytes:
        if max_lines <= 0:
            return raw_bytes
        parts = raw_bytes.splitlines(keepends=True)
        if len(parts) <= max_lines:
            return raw_bytes
        return b"".join(parts[-max_lines:])

    @staticmethod
    def _stat_log_file(log_path: Path):
        try:
            return log_path.stat()
        except FileNotFoundError as exc:
            raise TailerError(f"log file does not exist: {log_path}") from exc
        except PermissionError as exc:
            raise TailerError(f"log file is not readable: {log_path}") from exc

    @staticmethod
    def _stat_inode(stat_result) -> str | None:
        inode = getattr(stat_result, "st_ino", 0)
        if inode:
            return str(inode)
        return None

    @staticmethod
    def _build_session_id(inode: str | None, file_size: int, file_mtime: float) -> str:
        if inode:
            return f"{inode}:{file_size}:{int(file_mtime * 1000)}"
        return f"noinode:{file_size}:{int(file_mtime * 1000)}"

    @staticmethod
    def _is_truncated(
        stored: FileOffsetState | None,
        file_size: int,
        inode: str | None,
    ) -> bool:
        if stored is None:
            return False
        if stored.offset > file_size:
            return True
        if stored.file_size > file_size:
            return True
        if stored.inode and inode and stored.inode != inode:
            return True
        return False


__all__ = [
    "FileTailer",
    "TailMode",
    "TailPlan",
    "TailReadResult",
    "TailSource",
    "TailerError",
]
