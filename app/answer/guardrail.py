"""Evidence-based abstain threshold evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import Sequence

from app.metadata_utils import chunk_text_values, normalize_metadata
from app.retrieve.contracts import RetrievedChunk

from .contracts import AnswerError

_MIN_SUBSTANTIVE_CHARS = 8
_METADATA_CLUSTER_MIN_HITS = 3
_METADATA_CLUSTER_MIN_TOTAL_CHARS = 100


@dataclass(slots=True)
class AbstainThresholds:
    """Thresholds used to decide whether the service should abstain."""

    top1_min: float = 0.20
    top3_avg_min: float = 0.30
    min_hits: int = 2
    min_total_chars: int = 150

    @classmethod
    def from_any(cls, value: object | None) -> "AbstainThresholds":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        return cls(
            top1_min=float(getattr(value, "top1_min", cls.top1_min)),
            top3_avg_min=float(getattr(value, "top3_avg_min", cls.top3_avg_min)),
            min_hits=int(getattr(value, "min_hits", cls.min_hits)),
            min_total_chars=int(getattr(value, "min_total_chars", cls.min_total_chars)),
        )


@dataclass(slots=True)
class GuardrailDecision:
    """Outcome of abstain evaluation."""

    abstained: bool
    reason: str | None
    confidence: float
    top1_score: float
    top3_avg_score: float
    hit_count: int
    total_chars: int


def _clean_score(score: float | None) -> float:
    if score is None:
        return 0.0
    try:
        value = float(score)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise AnswerError(f"invalid score value: {score!r}") from exc
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _chunk_score(chunk: RetrievedChunk) -> float:
    return _clean_score(chunk.score)


def _chunk_text_length(chunk: RetrievedChunk) -> int:
    return len(chunk.content.strip())


def _metadata_document_counts(chunks: Sequence[RetrievedChunk]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for chunk in chunks:
        metadata = normalize_metadata(chunk.metadata)
        if not bool(metadata.get("metadata_constraint_passed")):
            continue
        document_key = chunk.file_path or str(metadata.get("document_id") or chunk.document_id or chunk.chunk_id)
        counts[document_key] = counts.get(document_key, 0) + 1
    return counts


def _count_recall_hits(chunks: Sequence[RetrievedChunk]) -> int:
    metadata_doc_counts = _metadata_document_counts(chunks)
    hit_count = 0
    for chunk in chunks:
        if _chunk_text_length(chunk) >= _MIN_SUBSTANTIVE_CHARS:
            hit_count += 1
            continue
        metadata = normalize_metadata(chunk.metadata)
        if not bool(metadata.get("metadata_constraint_passed")):
            continue
        document_key = chunk.file_path or str(metadata.get("document_id") or chunk.document_id or chunk.chunk_id)
        if metadata_doc_counts.get(document_key, 0) >= 2:
            hit_count += 1
    return hit_count


def _metadata_support_chars(chunks: Sequence[RetrievedChunk]) -> int:
    seen: set[str] = set()
    parts: list[str] = []
    for chunk in chunks:
        for value in (
            chunk.file_path,
            " / ".join(chunk.title_path),
        ):
            cleaned = str(value or "").strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                parts.append(cleaned)
        for value in chunk_text_values(chunk, dedupe=True):
            if value in seen:
                continue
            seen.add(value)
            parts.append(value)
    return sum(len(part) for part in parts)


def _has_dual_source_support(chunk: RetrievedChunk) -> bool:
    metadata = normalize_metadata(chunk.metadata)
    source_hits = metadata.get("source_hits")
    if not isinstance(source_hits, list) or len(source_hits) < 2:
        return False
    has_lexical = any(str(hit).startswith("lexical:") for hit in source_hits)
    has_semantic = any(str(hit).startswith("semantic:") for hit in source_hits)
    return has_lexical and has_semantic


def _is_strong_single_metadata_hit(
    chunks: Sequence[RetrievedChunk],
    *,
    config: AbstainThresholds,
    top1_score: float,
    top3_avg_score: float,
    total_chars: int,
) -> bool:
    if len(chunks) != 1:
        return False
    if top1_score < max(config.top1_min, 0.35):
        return False
    if top3_avg_score < config.top3_avg_min:
        return False

    chunk = chunks[0]
    metadata = normalize_metadata(chunk.metadata)
    if not bool(metadata.get("metadata_constraint_passed")):
        return False
    if float(metadata.get("metadata_constraint_coverage", 0.0) or 0.0) < 0.8:
        return False

    if not _has_dual_source_support(chunk):
        return False

    effective_total_chars = total_chars + _metadata_support_chars(chunks)
    return effective_total_chars >= config.min_total_chars


def _is_strong_metadata_document_cluster(
    chunks: Sequence[RetrievedChunk],
    *,
    config: AbstainThresholds,
    hit_count: int,
    top1_score: float,
    top3_avg_score: float,
    total_chars: int,
) -> bool:
    if hit_count < config.min_hits:
        return False
    if top1_score < max(config.top1_min, 0.35):
        return False
    if top3_avg_score < config.top3_avg_min:
        return False

    constrained = [chunk for chunk in chunks if bool((chunk.metadata or {}).get("metadata_constraint_passed"))]
    if len(constrained) < max(config.min_hits, _METADATA_CLUSTER_MIN_HITS):
        return False

    metadata_doc_counts = _metadata_document_counts(constrained)
    if len(metadata_doc_counts) != 1:
        return False
    if max(metadata_doc_counts.values(), default=0) < _METADATA_CLUSTER_MIN_HITS:
        return False

    avg_coverage = fmean(
        float((chunk.metadata or {}).get("metadata_constraint_coverage", 0.0) or 0.0)
        for chunk in constrained[:3]
    )
    if avg_coverage < 0.8:
        return False
    if not any(_has_dual_source_support(chunk) for chunk in constrained):
        return False

    effective_total_chars = total_chars + _metadata_support_chars(constrained)
    relaxed_min_total_chars = max(_METADATA_CLUSTER_MIN_TOTAL_CHARS, int(config.min_total_chars * 0.75))
    return effective_total_chars >= relaxed_min_total_chars


def _can_relax_min_total_chars(
    chunks: Sequence[RetrievedChunk],
    *,
    config: AbstainThresholds,
    hit_count: int,
    top1_score: float,
    top3_avg_score: float,
    total_chars: int,
) -> bool:
    if _is_strong_single_metadata_hit(
        chunks,
        config=config,
        top1_score=top1_score,
        top3_avg_score=top3_avg_score,
        total_chars=total_chars,
    ):
        return True

    if _is_strong_metadata_document_cluster(
        chunks,
        config=config,
        hit_count=hit_count,
        top1_score=top1_score,
        top3_avg_score=top3_avg_score,
        total_chars=total_chars,
    ):
        return True

    if hit_count < config.min_hits:
        return False
    if top1_score < max(config.top1_min, 0.3):
        return False
    if top3_avg_score < config.top3_avg_min:
        return False

    constrained = [chunk for chunk in chunks if bool((chunk.metadata or {}).get("metadata_constraint_passed"))]
    if len(constrained) < config.min_hits:
        return False

    avg_coverage = fmean(
        float((chunk.metadata or {}).get("metadata_constraint_coverage", 0.0) or 0.0)
        for chunk in constrained[:3]
    )
    if avg_coverage < 0.8:
        return False

    effective_total_chars = total_chars + _metadata_support_chars(constrained)
    return effective_total_chars >= config.min_total_chars


def evaluate_abstain(
    chunks: Sequence[RetrievedChunk],
    thresholds: AbstainThresholds | object | None = None,
) -> GuardrailDecision:
    """Evaluate the evidence set and decide whether the host should abstain."""

    config = AbstainThresholds.from_any(thresholds)
    materialized = [chunk for chunk in chunks if chunk.content.strip()]

    scores = sorted((_chunk_score(chunk) for chunk in materialized), reverse=True)
    top1_score = scores[0] if scores else 0.0
    top3_avg_score = fmean(scores[:3]) if scores[:3] else 0.0
    hit_count = _count_recall_hits(materialized)
    total_chars = sum(len(chunk.content.strip()) for chunk in materialized)
    confidence = round((top1_score + top3_avg_score) / 2.0, 4)

    if top1_score < config.top1_min:
        return GuardrailDecision(
            abstained=True,
            reason="top1_score_below_threshold",
            confidence=confidence,
            top1_score=top1_score,
            top3_avg_score=top3_avg_score,
            hit_count=hit_count,
            total_chars=total_chars,
        )

    if top3_avg_score < config.top3_avg_min:
        return GuardrailDecision(
            abstained=True,
            reason="top3_avg_score_below_threshold",
            confidence=confidence,
            top1_score=top1_score,
            top3_avg_score=top3_avg_score,
            hit_count=hit_count,
            total_chars=total_chars,
        )

    if hit_count < config.min_hits:
        if _is_strong_single_metadata_hit(
            materialized,
            config=config,
            top1_score=top1_score,
            top3_avg_score=top3_avg_score,
            total_chars=total_chars,
        ):
            hit_count = config.min_hits
        else:
            return GuardrailDecision(
                abstained=True,
                reason="recall_hits_below_threshold",
                confidence=confidence,
                top1_score=top1_score,
                top3_avg_score=top3_avg_score,
                hit_count=hit_count,
                total_chars=total_chars,
            )

    if total_chars < config.min_total_chars:
        if _can_relax_min_total_chars(
            materialized,
            config=config,
            hit_count=hit_count,
            top1_score=top1_score,
            top3_avg_score=top3_avg_score,
            total_chars=total_chars,
        ):
            return GuardrailDecision(
                abstained=False,
                reason=None,
                confidence=confidence,
                top1_score=top1_score,
                top3_avg_score=top3_avg_score,
                hit_count=hit_count,
                total_chars=total_chars,
            )
        return GuardrailDecision(
            abstained=True,
            reason="evidence_chars_below_threshold",
            confidence=confidence,
            top1_score=top1_score,
            top3_avg_score=top3_avg_score,
            hit_count=hit_count,
            total_chars=total_chars,
        )

    return GuardrailDecision(
        abstained=False,
        reason=None,
        confidence=confidence,
        top1_score=top1_score,
        top3_avg_score=top3_avg_score,
        hit_count=hit_count,
        total_chars=total_chars,
    )
