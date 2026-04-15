"""Helpers for incremental indexing state comparison."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping, Sequence

from .contracts import FileState, FileStateChange, MarkdownDocument


def build_file_hash(data: bytes) -> str:
    """Return a stable content hash for a Markdown file."""

    return hashlib.sha256(data).hexdigest()


def capture_file_state(document: MarkdownDocument) -> FileState:
    """Convert a loaded document into the file-state record used by /index."""

    return FileState(
        document_id=document.document_id,
        file_path=document.file_path,
        file_hash=document.file_hash,
        mtime_ns=document.mtime_ns,
        size=document.size,
        source_id=document.source_id,
    )


def build_file_state_map(documents: Sequence[MarkdownDocument]) -> dict[str, FileState]:
    """Build a document-id keyed snapshot from the current ingest run."""

    return {document.document_id: capture_file_state(document) for document in documents}


def is_file_state_stale(previous: FileState | None, current: FileState | None) -> bool:
    """Decide whether a document must be reindexed."""

    if previous is None or current is None:
        return True
    return (
        previous.file_hash != current.file_hash
        or previous.mtime_ns != current.mtime_ns
        or previous.size != current.size
        or previous.file_path != current.file_path
    )


def diff_file_states(
    previous: Mapping[str, FileState] | None,
    current: Mapping[str, FileState],
) -> list[FileStateChange]:
    """Return a deterministic diff for incremental indexing."""

    previous = previous or {}
    changes: list[FileStateChange] = []

    for document_id in sorted(current):
        current_state = current[document_id]
        previous_state = previous.get(document_id)
        if previous_state is None:
            status = "added"
        elif is_file_state_stale(previous_state, current_state):
            status = "modified"
        else:
            status = "unchanged"

        changes.append(
            FileStateChange(
                document_id=document_id,
                file_path=current_state.file_path,
                status=status,
                previous=previous_state,
                current=current_state,
            )
        )

    for document_id in sorted(previous):
        if document_id in current:
            continue
        previous_state = previous[document_id]
        changes.append(
            FileStateChange(
                document_id=document_id,
                file_path=previous_state.file_path,
                status="removed",
                previous=previous_state,
                current=None,
            )
        )

    return changes


@dataclass(slots=True)
class IngestStateTracker:
    """Small utility object for /index incremental planning."""

    def diff(
        self,
        previous: dict[str, FileState] | None,
        current: dict[str, FileState],
    ) -> Sequence[FileStateChange]:
        return diff_file_states(previous, current)

    def needs_reindex(
        self,
        previous: FileState | None,
        current: FileState | None,
    ) -> bool:
        return is_file_state_stale(previous, current)

