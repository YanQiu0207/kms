"""Ingestion package scaffold and Markdown pipeline helpers."""

from .chunker import MarkdownChunker, build_chunk_id
from .contracts import (
    FileChangeStatus,
    FileState,
    FileStateChange,
    IngestBatch,
    IngestError,
    IngestSource,
    IngestStateTrackerProtocol,
    Ingestor,
    MarkdownChunk,
    MarkdownChunkerProtocol,
    MarkdownDocument,
    MarkdownParserProtocol,
    MarkdownSection,
    PlaceholderIngestor,
    SourceSpec,
)
from .loader import MarkdownIngestLoader
from .markdown_parser import MarkdownParser, parse_markdown_sections
from .state import (
    IngestStateTracker,
    build_file_hash,
    build_file_state_map,
    capture_file_state,
    diff_file_states,
    is_file_state_stale,
)

__all__ = [
    "FileChangeStatus",
    "FileState",
    "FileStateChange",
    "IngestBatch",
    "IngestError",
    "IngestSource",
    "IngestStateTracker",
    "IngestStateTrackerProtocol",
    "Ingestor",
    "MarkdownChunk",
    "MarkdownChunker",
    "MarkdownChunkerProtocol",
    "MarkdownDocument",
    "MarkdownIngestLoader",
    "MarkdownParser",
    "MarkdownParserProtocol",
    "MarkdownSection",
    "PlaceholderIngestor",
    "SourceSpec",
    "build_chunk_id",
    "build_file_hash",
    "build_file_state_map",
    "capture_file_state",
    "diff_file_states",
    "is_file_state_stale",
    "parse_markdown_sections",
]
