"""Ingestion package scaffold and Markdown pipeline helpers."""

from .boilerplate_rules import apply_source_rules, compile_source_rules
from .chunker import MarkdownChunker, build_contextual_chunk_text, build_chunk_id
from .cleaner import MarkdownCleaner
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
from .table_normalizer import normalize_markdown_tables

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
    "MarkdownCleaner",
    "MarkdownDocument",
    "MarkdownIngestLoader",
    "MarkdownParser",
    "MarkdownParserProtocol",
    "MarkdownSection",
    "PlaceholderIngestor",
    "SourceSpec",
    "apply_source_rules",
    "build_contextual_chunk_text",
    "build_chunk_id",
    "build_file_hash",
    "build_file_state_map",
    "capture_file_state",
    "compile_source_rules",
    "diff_file_states",
    "is_file_state_stale",
    "normalize_markdown_tables",
    "parse_markdown_sections",
]
