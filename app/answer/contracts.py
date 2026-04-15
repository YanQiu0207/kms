"""Prompt assembly and citation verification contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence

from app.retrieve.contracts import RetrievedChunk


@dataclass(slots=True)
class EvidenceSource:
    """Prompt payload returned to the host LLM."""

    chunk_id: str
    ref_index: int = 0
    file_path: str = ""
    title_path: tuple[str, ...] = field(default_factory=tuple)
    start_line: int = 0
    end_line: int = 0
    text: str = ""
    score: float = 0.0
    doc_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class EvidencePackage:
    """Evidence payload returned to the host LLM."""

    question: str
    prompt: str
    chunks: Sequence[RetrievedChunk] = field(default_factory=tuple)
    abstained: bool = False
    abstain_reason: str | None = None


@dataclass(slots=True)
class VerificationDetail:
    """Per-chunk citation verification detail."""

    chunk_id: str
    matched_ngrams: int
    total_ngrams: int


@dataclass(slots=True)
class VerificationResult:
    """Citation verification outcome for host-generated answers."""

    citation_unverified: bool
    coverage: float
    matched_chunk_ids: Sequence[str] = field(default_factory=tuple)
    details: Sequence[VerificationDetail] = field(default_factory=tuple)


class AnswerError(RuntimeError):
    """Raised when prompt assembly or verification fails."""


class PromptAssembler(Protocol):
    """Build the constrained host prompt from retrieved evidence."""

    def build(self, question: str, chunks: Sequence[RetrievedChunk]) -> EvidencePackage:
        raise NotImplementedError


class CitationVerifier(Protocol):
    """Validate answer citations against retrieved evidence."""

    def verify(self, answer: str, used_chunk_ids: Sequence[str]) -> VerificationResult:
        raise NotImplementedError


class ChunkTextProvider(Protocol):
    """Resolve a chunk_id back to its original chunk text."""

    def get_chunk_text(self, chunk_id: str) -> str | None:
        raise NotImplementedError


class PlaceholderPromptAssembler:
    """Import-safe stub used until prompt assembly is implemented."""

    def build(self, question: str, chunks: Sequence[RetrievedChunk]) -> EvidencePackage:
        raise NotImplementedError("prompt assembler is not implemented yet")


class PlaceholderCitationVerifier:
    """Import-safe stub used until citation verification is implemented."""

    def verify(self, answer: str, used_chunk_ids: Sequence[str]) -> VerificationResult:
        raise NotImplementedError("citation verifier is not implemented yet")
