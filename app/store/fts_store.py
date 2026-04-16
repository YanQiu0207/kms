from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path, PurePath
from typing import Sequence

from app.metadata_utils import FTS_METADATA_EXTRA_SCALAR_FIELDS, metadata_text_values
from app.vendors import cut_tokens

from .contracts import StoreError, StoredChunk

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+")


def _validate_identifier(value: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise StoreError(f"invalid sqlite identifier: {value!r}")
    return value


def _normalize_tokens(tokens: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    for token in tokens:
        cleaned = token.strip()
        if not cleaned:
            continue
        cleaned = cleaned.lower() if cleaned.isascii() else cleaned
        normalized.append(cleaned)
    return normalized


def _fallback_tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for chunk in _TOKEN_RE.findall(text):
        if chunk.isascii():
            tokens.append(chunk.lower())
            continue

        if len(chunk) <= 2:
            tokens.append(chunk)
            continue

        tokens.append(chunk)
        tokens.extend(chunk[index : index + 2] for index in range(len(chunk) - 1))

    return _normalize_tokens(tokens)


def tokenize_fts(text: str) -> str:
    """Prepare text for FTS5 insertion and query matching."""

    stripped = text.strip()
    if not stripped:
        return ""

    tokens = cut_tokens(stripped)
    if tokens is not None:
        tokens = _normalize_tokens(tokens)
        if not tokens:
            tokens = _fallback_tokenize(stripped)
    else:
        tokens = _fallback_tokenize(stripped)

    return " ".join(tokens)


def tokenize_title_path(title_path: Sequence[str]) -> str:
    return tokenize_fts(" / ".join(segment for segment in title_path if segment.strip()))


def tokenize_metadata_text(file_path: str, metadata: dict[str, object]) -> str:
    values = list(metadata_text_values(metadata, extra_scalar_fields=FTS_METADATA_EXTRA_SCALAR_FIELDS))
    file_name = PurePath(file_path).stem if file_path else ""
    if file_name:
        values.append(file_name)
    return tokenize_fts(" ".join(values))


def _stable_rowid(chunk_id: str) -> int:
    digest = hashlib.sha1(chunk_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False) & 0x7FFF_FFFF_FFFF_FFFF


class FTS5Writer:
    """FTS5 write helper backed by the same SQLite database."""

    def __init__(
        self,
        database: str | Path | sqlite3.Connection,
        *,
        table_name: str = "chunk_fts",
        initialize: bool = True,
    ) -> None:
        self._table_name = _validate_identifier(table_name)
        self._owns_connection = not isinstance(database, sqlite3.Connection)
        if self._owns_connection:
            self._connection = sqlite3.connect(str(Path(database)))
        else:
            self._connection = database
        if initialize:
            self.initialize()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def close(self) -> None:
        if self._owns_connection:
            self._connection.close()

    def initialize(self) -> None:
        try:
            existing_columns = self._list_columns()
            expected_columns = ("chunk_id", "document_id", "file_path", "title_path", "content", "metadata_text")
            with self._connection:
                if existing_columns and existing_columns != expected_columns:
                    self._connection.execute(f"DROP TABLE IF EXISTS {self._table_name}")
                self._connection.execute(
                    f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS {self._table_name}
                    USING fts5(
                        chunk_id UNINDEXED,
                        document_id UNINDEXED,
                        file_path UNINDEXED,
                        title_path,
                        content,
                        metadata_text,
                        tokenize = 'unicode61 remove_diacritics 2'
                    )
                    """
                )
        except sqlite3.Error as exc:
            raise StoreError("failed to initialize fts5 writer") from exc

    def _list_columns(self) -> tuple[str, ...]:
        try:
            rows = self._connection.execute(f"PRAGMA table_info({self._table_name})").fetchall()
        except sqlite3.Error:
            return ()
        if not rows:
            return ()
        return tuple(str(row[1]) for row in rows if len(row) > 1)

    def upsert_chunks(self, records: Sequence[StoredChunk]) -> None:
        if not records:
            return

        self.initialize()
        try:
            with self._connection:
                for record in records:
                    rowid = _stable_rowid(record.chunk_id)
                    self._connection.execute(
                        f"DELETE FROM {self._table_name} WHERE rowid = ?",
                        (rowid,),
                    )
                    self._connection.execute(
                        f"""
                        INSERT INTO {self._table_name} (
                            rowid,
                            chunk_id,
                            document_id,
                            file_path,
                            title_path,
                            content,
                            metadata_text
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            rowid,
                            record.chunk_id,
                            record.document_id,
                            record.file_path,
                            tokenize_title_path(record.title_path),
                            tokenize_fts(record.content),
                            tokenize_metadata_text(record.file_path, record.metadata),
                        ),
                    )
        except sqlite3.Error as exc:
            raise StoreError("failed to upsert chunks into fts5") from exc

    def delete_chunk_ids(self, chunk_ids: Sequence[str]) -> None:
        if not chunk_ids:
            return

        try:
            with self._connection:
                for chunk_id in chunk_ids:
                    self._connection.execute(
                        f"DELETE FROM {self._table_name} WHERE rowid = ?",
                        (_stable_rowid(chunk_id),),
                    )
        except sqlite3.Error as exc:
            raise StoreError("failed to delete chunks from fts5") from exc
