"""Retrieval contracts and placeholders."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Protocol, Sequence


@dataclass(slots=True)
class RetrievedChunk:
    """Single retrieval result passed into answer generation."""

    document_id: str
    content: str
    chunk_id: str = ""
    file_path: str = ""
    title_path: tuple[str, ...] = field(default_factory=tuple)
    score: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    text: str = ""

    def __post_init__(self) -> None:
        if self.text and not self.content:
            self.content = self.text
        elif self.content and not self.text:
            self.text = self.content

    @property
    def doc_id(self) -> str:
        return self.document_id

    def to_search_record(self) -> dict[str, object]:
        file_name = PurePath(self.file_path).name if self.file_path else ""
        start_line = int(self.metadata.get("start_line", 0) or 0) if isinstance(self.metadata, dict) else 0
        end_line = int(self.metadata.get("end_line", 0) or 0) if isinstance(self.metadata, dict) else 0
        location = file_name or self.file_path
        if start_line > 0:
            location = f"{location}:{start_line}-{end_line}" if end_line > start_line else f"{location}:{start_line}"
        return {
            "chunk_id": self.chunk_id or self.document_id,
            "file_path": self.file_path,
            "location": location or "",
            "title_path": list(self.title_path),
            "text": self.text or self.content,
            "score": 0.0 if self.score is None else float(self.score),
            "doc_id": self.document_id,
        }


@dataclass(slots=True)
class SearchDebug:
    """Debug counters exposed by `/search`."""

    queries_count: int = 0
    recall_count: int = 0
    rerank_count: int = 0

    def to_record(self) -> dict[str, int]:
        return {
            "queries_count": self.queries_count,
            "recall_count": self.recall_count,
            "rerank_count": self.rerank_count,
        }


@dataclass(slots=True)
class SearchResultSet:
    """Search payload returned by the hybrid retrieval pipeline."""

    results: Sequence[RetrievedChunk] = field(default_factory=tuple)
    debug: SearchDebug = field(default_factory=SearchDebug)

    def to_payload(self) -> dict[str, object]:
        return {
            "results": [result.to_search_record() for result in self.results],
            "debug": self.debug.to_record(),
        }


class RetrievalError(RuntimeError):
    """Raised when retrieval cannot satisfy a query."""


class RetrievalService(Protocol):
    """High-level retrieval boundary."""

    def search(
        self,
        queries: Sequence[str],
        recall_top_k: int = 20,
        rerank_top_k: int = 6,
    ) -> SearchResultSet:
        raise NotImplementedError

    def retrieve(self, query: str, limit: int = 5) -> Sequence[RetrievedChunk]:
        raise NotImplementedError


class PlaceholderRetrievalService:
    """Import-safe stub used until retrieval is implemented."""

    def search(
        self,
        queries: Sequence[str],
        recall_top_k: int = 20,
        rerank_top_k: int = 6,
    ) -> SearchResultSet:
        raise NotImplementedError("retrieval service is not implemented yet")

    def retrieve(self, query: str, limit: int = 5) -> Sequence[RetrievedChunk]:
        raise NotImplementedError("retrieval service is not implemented yet")
