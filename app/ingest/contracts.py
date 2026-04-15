"""Ingestion contracts and core datatypes.

These types define the boundary for the Markdown ingest pipeline without
pulling in any heavy runtime dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal, Protocol, Sequence


FileChangeStatus = Literal["added", "modified", "unchanged", "removed"]


@dataclass(slots=True)
class SourceSpec:
    """Declared Markdown source root configured by the host."""

    path: str
    excludes: tuple[str, ...] = field(default_factory=tuple)
    source_id: str = ""


@dataclass(slots=True)
class MarkdownDocument:
    """Loaded Markdown document with content hash and path metadata."""

    source_id: str
    source_root: str
    document_id: str
    file_path: str
    relative_path: str
    file_hash: str
    mtime_ns: int
    size: int
    text: str
    encoding: str = "utf-8"

    def to_record(self) -> dict[str, object]:
        return {
            "doc_id": self.document_id,
            "document_id": self.document_id,
            "source_id": self.source_id,
            "source_root": self.source_root,
            "file_path": self.file_path,
            "relative_path": self.relative_path,
            "file_hash": self.file_hash,
            "mtime_ns": self.mtime_ns,
            "size": self.size,
            "encoding": self.encoding,
            "text": self.text,
        }


@dataclass(slots=True)
class MarkdownSection:
    """Title-scoped section extracted from a Markdown document."""

    document_id: str
    file_path: str
    file_hash: str
    title_path: tuple[str, ...] = field(default_factory=tuple)
    heading: str = ""
    heading_level: int = 0
    section_index: int = 0
    start_line: int = 0
    end_line: int = 0
    text: str = ""

    def to_record(self) -> dict[str, object]:
        return {
            "doc_id": self.document_id,
            "document_id": self.document_id,
            "file_path": self.file_path,
            "file_hash": self.file_hash,
            "title_path": list(self.title_path),
            "heading": self.heading,
            "heading_level": self.heading_level,
            "section_index": self.section_index,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "text": self.text,
        }


@dataclass(slots=True)
class MarkdownChunk:
    """Final ingest unit passed to storage and retrieval layers."""

    chunk_id: str
    document_id: str
    file_path: str
    file_hash: str
    title_path: tuple[str, ...] = field(default_factory=tuple)
    section_index: int = 0
    chunk_index: int = 0
    start_line: int = 0
    end_line: int = 0
    text: str = ""
    token_count: int = 0
    chunker_version: str = "v1"
    embedding_model: str = ""

    def to_record(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.document_id,
            "document_id": self.document_id,
            "file_path": self.file_path,
            "file_hash": self.file_hash,
            "title_path": list(self.title_path),
            "section_index": self.section_index,
            "chunk_index": self.chunk_index,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "text": self.text,
            "token_count": self.token_count,
            "chunker_version": self.chunker_version,
            "embedding_model": self.embedding_model,
        }


@dataclass(slots=True)
class FileState:
    """Incremental indexing state for one Markdown document."""

    document_id: str
    file_path: str
    file_hash: str
    mtime_ns: int
    size: int
    source_id: str = ""

    def to_record(self) -> dict[str, object]:
        return {
            "doc_id": self.document_id,
            "document_id": self.document_id,
            "file_path": self.file_path,
            "file_hash": self.file_hash,
            "mtime_ns": self.mtime_ns,
            "size": self.size,
            "source_id": self.source_id,
        }


@dataclass(slots=True)
class FileStateChange:
    """Diff entry between two file-state snapshots."""

    document_id: str
    file_path: str
    status: FileChangeStatus
    previous: FileState | None = None
    current: FileState | None = None


@dataclass(slots=True)
class IngestBatch:
    """Normalized payload passed from ingestion into storage."""

    source_id: str
    documents: Sequence[MarkdownDocument] = field(default_factory=tuple)
    sections: Sequence[MarkdownSection] = field(default_factory=tuple)
    chunks: Sequence[MarkdownChunk] = field(default_factory=tuple)
    items: Sequence[dict[str, object]] = field(default_factory=tuple)


class IngestError(RuntimeError):
    """Raised when an ingestion stage cannot complete."""


class IngestSource(Protocol):
    """Legacy source boundary kept for compatibility with the scaffold."""

    def load(self) -> Iterable[dict[str, object]]:
        """Yield raw items ready for normalisation."""
        raise NotImplementedError


class MarkdownParserProtocol(Protocol):
    """Title-aware Markdown parser boundary."""

    def parse(self, document: MarkdownDocument) -> Sequence[MarkdownSection]:
        raise NotImplementedError


class MarkdownChunkerProtocol(Protocol):
    """Chunker boundary for long Markdown sections."""

    def chunk(self, section: MarkdownSection) -> Sequence[MarkdownChunk]:
        raise NotImplementedError


class IngestStateTrackerProtocol(Protocol):
    """Incremental indexing state helper boundary."""

    def diff(
        self,
        previous: dict[str, FileState] | None,
        current: dict[str, FileState],
    ) -> Sequence[FileStateChange]:
        raise NotImplementedError


class Ingestor(Protocol):
    """Callable ingestion boundary for the main application."""

    def ingest(self, source: IngestSource) -> IngestBatch:
        """Convert a source into a normalized batch."""
        raise NotImplementedError


class PlaceholderIngestor:
    """Import-safe stub used until the real pipeline lands."""

    def ingest(self, source: IngestSource) -> IngestBatch:
        raise NotImplementedError("ingest pipeline is not implemented yet")
