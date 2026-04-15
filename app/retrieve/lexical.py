from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from app.store.fts_store import tokenize_fts

from .contracts import RetrievedChunk, RetrievalError

_FTS_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+")


def _coerce_connection(database: str | Path | sqlite3.Connection | object) -> tuple[sqlite3.Connection, bool]:
    if isinstance(database, sqlite3.Connection):
        return database, False

    connection = getattr(database, "connection", None)
    if isinstance(connection, sqlite3.Connection):
        return connection, False

    return sqlite3.connect(str(Path(database))), True


def _loads_title_path(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    if isinstance(value, str) and value.strip():
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError:
                raw = None
            else:
                if isinstance(raw, list):
                    return tuple(str(item) for item in raw)
        return tuple(segment.strip() for segment in value.split(" / ") if segment.strip())
    return ()


def _coerce_limit(limit: int) -> int:
    return max(0, int(limit))


def _build_fts_query(query: str) -> str:
    raw_tokens = tokenize_fts(query).split()
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in raw_tokens:
        token = raw.strip()
        if not token or not _FTS_TOKEN_RE.fullmatch(token):
            continue
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    if not tokens:
        return ""
    return " OR ".join(tokens)


@dataclass(slots=True)
class LexicalRetriever:
    """FTS5-backed lexical retriever."""

    database: str | Path | sqlite3.Connection | object
    table_name: str = "chunk_fts"
    chunk_table: str = "chunks"
    _connection: sqlite3.Connection = field(init=False, repr=False)
    _owns_connection: bool = field(init=False, repr=False, default=False)

    def __post_init__(self) -> None:
        self._connection, self._owns_connection = _coerce_connection(self.database)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def close(self) -> None:
        if self._owns_connection:
            self._connection.close()

    def __enter__(self) -> LexicalRetriever:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def search(self, query: str, limit: int = 5) -> Sequence[RetrievedChunk]:
        query = query.strip()
        if not query or _coerce_limit(limit) <= 0:
            return ()

        fts_query = _build_fts_query(query)
        if not fts_query:
            return ()
        sql = f"""
            WITH ranked AS (
                SELECT
                    chunk_id,
                    bm25({self.table_name}) AS bm25_score
                FROM {self.table_name}
                WHERE {self.table_name} MATCH ?
                ORDER BY bm25_score ASC
                LIMIT ?
            )
            SELECT
                c.chunk_id AS chunk_id,
                c.document_id AS document_id,
                c.file_path AS file_path,
                c.title_path AS title_path,
                c.content AS content,
                c.metadata_json AS metadata_json,
                ranked.bm25_score AS bm25_score
            FROM ranked
            JOIN {self.chunk_table} AS c
                ON c.chunk_id = ranked.chunk_id
            ORDER BY ranked.bm25_score ASC, c.document_id ASC, c.chunk_index ASC, c.chunk_id ASC
        """

        try:
            rows = self._connection.execute(sql, (fts_query, _coerce_limit(limit))).fetchall()
        except sqlite3.Error as exc:
            if "no such table" in str(exc).lower():
                return ()
            raise RetrievalError("lexical retrieval is unavailable") from exc

        results: list[RetrievedChunk] = []
        for index, row in enumerate(rows, start=1):
            metadata = self._loads_metadata(row["metadata_json"] if "metadata_json" in row.keys() else None)
            metadata["lexical_rank"] = index
            metadata["lexical_score"] = 1.0 / float(index)
            metadata["lexical_bm25"] = float(row["bm25_score"] or 0.0)
            results.append(
                RetrievedChunk(
                    document_id=str(row["document_id"]),
                    content=str(row["content"] or ""),
                    chunk_id=str(row["chunk_id"]),
                    file_path=str(row["file_path"] or ""),
                    title_path=_loads_title_path(row["title_path"]),
                    score=1.0 / float(index),
                    metadata=metadata,
                )
            )
        return tuple(results)

    def search_many(self, queries: Sequence[str], limit: int = 5) -> tuple[RetrievedChunk, ...]:
        hits: list[RetrievedChunk] = []
        for query in queries:
            hits.extend(self.search(query, limit=limit))
        return tuple(hits)

    @staticmethod
    def _loads_metadata(value: object) -> dict[str, object]:
        if not value:
            return {}
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            try:
                raw = json.loads(value)
            except json.JSONDecodeError:
                return {}
            return raw if isinstance(raw, dict) else {}
        return {}
