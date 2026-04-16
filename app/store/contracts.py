"""Storage contracts and placeholders."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Iterable, Protocol, Sequence


@dataclass(slots=True)
class DocumentRecord:
    """Canonical stored record used across retrieval and answering."""

    document_id: str
    content: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class StoredDocument:
    """SQLite document row used by the M1 metadata store."""

    document_id: str
    content: str
    file_path: str = ""
    title_path: tuple[str, ...] = field(default_factory=tuple)
    source_path: str | None = None
    file_hash: str | None = None
    updated_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def doc_id(self) -> str:
        return self.document_id


@dataclass(slots=True)
class StoredChunk:
    """SQLite chunk row and downstream index payload."""

    chunk_id: str
    document_id: str
    content: str
    file_path: str = ""
    chunk_index: int = 0
    title_path: tuple[str, ...] = field(default_factory=tuple)
    token_count: int = 0
    file_hash: str | None = None
    chunker_version: str = "v1"
    embedding_model: str = ""
    updated_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def doc_id(self) -> str:
        return self.document_id


@dataclass(slots=True)
class IngestLogEntry:
    """Single ingest run record."""

    source_id: str
    mode: str = "incremental"
    status: str = "started"
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    document_count: int = 0
    chunk_count: int = 0
    message: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class VectorChunk:
    """Vector-store payload expected by the Chroma wrapper."""

    chunk_id: str
    document_id: str
    content: str
    embedding: Sequence[float] | None = None
    file_path: str = ""
    title_path: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def doc_id(self) -> str:
        return self.document_id


@dataclass(slots=True)
class StoreStats:
    """Basic counts used by later health/stats surfaces."""

    document_count: int = 0
    chunk_count: int = 0
    ingest_log_count: int = 0
    last_indexed_at: datetime | None = None


class StoreError(RuntimeError):
    """Raised when persistence or indexing fails."""


class StoreWriter(Protocol):
    """Write-side storage boundary."""

    def upsert(self, records: Sequence[DocumentRecord]) -> None:
        raise NotImplementedError


class VectorIndex(Protocol):
    """Read-side index boundary for similarity lookup."""

    def search(self, query: str, limit: int = 5) -> Iterable[DocumentRecord]:
        raise NotImplementedError


class MetadataStore(Protocol):
    """Persistence boundary for documents, chunks, and ingest logs."""

    def upsert_documents(self, records: Sequence[StoredDocument]) -> None:
        raise NotImplementedError

    def upsert_chunks(self, records: Sequence[StoredChunk]) -> None:
        raise NotImplementedError

    def delete_documents(self, document_ids: Sequence[str]) -> None:
        raise NotImplementedError

    def list_chunk_ids(self, document_ids: Sequence[str] | None = None) -> Sequence[str]:
        raise NotImplementedError

    def list_file_states(self) -> Sequence[dict[str, object]]:
        raise NotImplementedError

    def list_chunks_by_document(self, document_id: str) -> Sequence[StoredChunk]:
        raise NotImplementedError

    def append_ingest_log(self, entry: IngestLogEntry) -> int:
        raise NotImplementedError

    def stats(self) -> StoreStats:
        raise NotImplementedError


class FTSWriter(Protocol):
    """FTS5 write boundary used by the lexical index."""

    def upsert_chunks(self, records: Sequence[StoredChunk]) -> None:
        raise NotImplementedError

    def delete_chunk_ids(self, chunk_ids: Sequence[str]) -> None:
        raise NotImplementedError


class VectorWriter(Protocol):
    """Vector-store write boundary used by the semantic index."""

    def upsert(self, records: Sequence[VectorChunk]) -> None:
        raise NotImplementedError

    def delete(self, chunk_ids: Sequence[str]) -> None:
        raise NotImplementedError


class PlaceholderStoreWriter:
    """Import-safe stub used until a concrete store is wired."""

    def upsert(self, records: Sequence[DocumentRecord]) -> None:
        raise NotImplementedError("store writer is not implemented yet")
