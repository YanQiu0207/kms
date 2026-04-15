"""Evidence-based abstain threshold evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import Sequence

from app.retrieve.contracts import RetrievedChunk

from .contracts import AnswerError


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
    hit_count = len(materialized)
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
