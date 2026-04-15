"""Markdown source scanning and ingest orchestration."""

from __future__ import annotations

from fnmatch import fnmatchcase
from hashlib import sha1
from pathlib import Path
from typing import Iterator, Sequence

from .chunker import MarkdownChunker
from .contracts import (
    FileState,
    FileStateChange,
    IngestBatch,
    IngestError,
    MarkdownChunk,
    MarkdownDocument,
    MarkdownSection,
    SourceSpec,
)
from .markdown_parser import MarkdownParser
from .state import IngestStateTracker, build_file_hash, build_file_state_map

MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkdn", ".mdtxt"}


def _normalize_path(path: Path) -> str:
    return path.resolve(strict=False).as_posix()


def _source_id_for_root(root: Path) -> str:
    return sha1(_normalize_path(root).encode("utf-8")).hexdigest()[:12]


def _normalize_excludes(excludes: Sequence[str]) -> tuple[str, ...]:
    cleaned = tuple(pattern.strip() for pattern in excludes if pattern.strip())
    return cleaned


def _matches_exclude(path: Path, root: Path, excludes: Sequence[str]) -> bool:
    if not excludes:
        return False

    absolute = _normalize_path(path)
    try:
        relative = path.resolve(strict=False).relative_to(root.resolve(strict=False)).as_posix()
    except ValueError:
        relative = path.name

    for pattern in excludes:
        if fnmatchcase(relative, pattern):
            return True
        if fnmatchcase(absolute, pattern):
            return True
        if fnmatchcase(path.name, pattern):
            return True
    return False


def _iter_markdown_paths(root: Path) -> Iterator[Path]:
    if root.is_file():
        if root.suffix.lower() in MARKDOWN_SUFFIXES:
            yield root
        return

    for candidate in root.rglob("*"):
        if candidate.is_file() and candidate.suffix.lower() in MARKDOWN_SUFFIXES:
            yield candidate


def _read_document(path: Path, source_root: Path, source_id: str) -> MarkdownDocument:
    raw = path.read_bytes()
    file_hash = build_file_hash(raw)
    encoding = "utf-8"
    for candidate_encoding in ("utf-8-sig", "utf-8"):
        try:
            text = raw.decode(candidate_encoding)
            encoding = candidate_encoding
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
        encoding = "utf-8"

    resolved_path = path.resolve(strict=False)
    resolved_root = source_root.resolve(strict=False)
    try:
        relative_path = resolved_path.relative_to(resolved_root).as_posix()
    except ValueError:
        relative_path = resolved_path.name

    document_id = f"{source_id}:{relative_path}"
    stat = path.stat()

    return MarkdownDocument(
        source_id=source_id,
        source_root=_normalize_path(source_root),
        document_id=document_id,
        file_path=_normalize_path(path),
        relative_path=relative_path,
        file_hash=file_hash,
        mtime_ns=stat.st_mtime_ns,
        size=stat.st_size,
        text=text,
        encoding=encoding,
    )


class MarkdownIngestLoader:
    """High-level ingest pipeline used by /index."""

    def __init__(
        self,
        sources: Sequence[SourceSpec],
        *,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
        chunker_version: str = "v1",
        embedding_model: str = "",
    ) -> None:
        if not sources:
            raise IngestError("at least one source is required")

        normalized_sources = []
        for source in sources:
            normalized_sources.append(
                SourceSpec(
                    path=source.path,
                    excludes=_normalize_excludes(source.excludes),
                    source_id=source.source_id,
                )
            )

        self.sources = tuple(normalized_sources)
        self.parser = MarkdownParser()
        self.chunker = MarkdownChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            chunker_version=chunker_version,
            embedding_model=embedding_model,
        )
        self.state_tracker = IngestStateTracker()

    def iter_documents(self) -> Iterator[MarkdownDocument]:
        for source in self.sources:
            root = Path(source.path).expanduser()
            if not root.exists():
                raise IngestError(f"source path does not exist: {source.path}")

            source_root = root if root.is_dir() else root.parent
            source_id = source.source_id or _source_id_for_root(source_root)

            for path in _iter_markdown_paths(root):
                if _matches_exclude(path, source_root, source.excludes):
                    continue
                yield _read_document(path, source_root, source_id)

    def iter_sections(self, document: MarkdownDocument) -> Sequence[MarkdownSection]:
        return self.parser.parse(document)

    def iter_chunks(self, document: MarkdownDocument) -> tuple[MarkdownChunk, ...]:
        chunks: list[MarkdownChunk] = []
        for section in self.iter_sections(document):
            chunks.extend(self.chunker.chunk(section))
        return tuple(chunks)

    def build_state_snapshot(self) -> dict[str, object]:
        documents = tuple(self.iter_documents())
        return {
            "documents": documents,
            "file_states": build_file_state_map(documents),
        }

    def build_file_state_snapshot(self) -> dict[str, FileState]:
        return build_file_state_map(tuple(self.iter_documents()))

    def diff_file_states(
        self,
        previous: dict[str, FileState] | None,
    ) -> tuple[FileStateChange, ...]:
        current = self.build_file_state_snapshot()
        return tuple(self.state_tracker.diff(previous, current))

    def build_incremental_plan(
        self,
        previous: dict[str, FileState] | None,
    ) -> dict[str, object]:
        documents = tuple(self.iter_documents())
        current = build_file_state_map(documents)
        changes = tuple(self.state_tracker.diff(previous, current))
        return {
            "documents": documents,
            "file_states": current,
            "changes": changes,
            "needs_reindex": any(change.status != "unchanged" for change in changes),
        }

    def build_batch(self) -> IngestBatch:
        documents: list[MarkdownDocument] = []
        sections: list[MarkdownSection] = []
        chunks: list[MarkdownChunk] = []

        for document in self.iter_documents():
            documents.append(document)
            document_sections = list(self.iter_sections(document))
            sections.extend(document_sections)
            for section in document_sections:
                chunks.extend(self.chunker.chunk(section))

        return IngestBatch(
            source_id="markdown-ingest",
            documents=tuple(documents),
            sections=tuple(sections),
            chunks=tuple(chunks),
            items=tuple(chunk.to_record() for chunk in chunks),
        )
