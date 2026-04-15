from __future__ import annotations

import hashlib
import math
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol, Sequence

from app.observability import get_logger, timed_operation
from app.runtime_cleanup import best_effort_close, best_effort_release_runtime_resources
from app.store.fts_store import tokenize_fts
from app.vendors import VendorFlagEmbeddingError, create_flag_reranker

from .contracts import RetrievedChunk, RetrievalError

LOGGER = get_logger("kms.rerank")


class RerankerProtocol(Protocol):
    def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievedChunk],
        top_k: int | None = None,
    ) -> Sequence[RetrievedChunk]:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


def _is_debug_model_name(model_name: str) -> bool:
    model_name = (model_name or "").strip().lower()
    return not model_name or model_name.startswith("debug-")


def _tokenize(text: str) -> set[str]:
    return {token for token in tokenize_fts(text).split() if token}


def _debug_score(query: str, candidate: RetrievedChunk) -> float:
    query_tokens = _tokenize(query)
    candidate_tokens = _tokenize(candidate.content)
    if not query_tokens or not candidate_tokens:
        return float(candidate.score or 0.0) * 0.1

    overlap = len(query_tokens & candidate_tokens)
    coverage = overlap / max(1, len(query_tokens))
    precision = overlap / max(1, len(candidate_tokens))
    rrf_score = float(candidate.metadata.get("rrf_score", candidate.score or 0.0))
    source_hint = max(
        float(candidate.metadata.get("lexical_score", 0.0) or 0.0),
        float(candidate.metadata.get("semantic_score", 0.0) or 0.0),
    )
    return (0.5 * coverage) + (0.2 * precision) + (0.2 * min(1.0, rrf_score * 10.0)) + (0.1 * min(1.0, source_hint))


class DebugReranker:
    """Deterministic reranker used for tests and local smoke runs."""

    def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievedChunk],
        top_k: int | None = None,
    ) -> Sequence[RetrievedChunk]:
        ranked: list[RetrievedChunk] = []
        for index, candidate in enumerate(candidates, start=1):
            score = _debug_score(query, candidate)
            metadata = dict(candidate.metadata)
            metadata["rerank_rank"] = index
            metadata["rerank_score"] = score
            ranked.append(
                replace(
                    candidate,
                    score=score,
                    metadata=metadata,
                )
            )
        ranked.sort(key=lambda item: (-float(item.score or 0.0), item.chunk_id or item.document_id))
        if top_k is not None:
            return tuple(ranked[: max(0, int(top_k))])
        return tuple(ranked)

    def close(self) -> None:
        return None


def _coerce_scores(raw: object, expected: int) -> list[float]:
    if raw is None:
        return [0.0 for _ in range(expected)]
    if hasattr(raw, "tolist"):
        raw = raw.tolist()
    if isinstance(raw, (int, float)):
        return [float(raw)]
    if isinstance(raw, list):
        if raw and isinstance(raw[0], list):
            raw = raw[0]
        return [float(value) for value in raw]
    return [float(raw)]


def _normalize_score(score: float) -> float:
    bounded = max(min(float(score), 20.0), -20.0)
    return 1.0 / (1.0 + math.exp(-bounded))


@dataclass(slots=True)
class FlagEmbeddingReranker:
    """Lazy wrapper around FlagEmbedding reranker models."""

    model_name: str
    device: str = "cpu"
    dtype: str = "float32"
    batch_size: int = 32
    hf_cache: str | Path | None = None
    _model: object | None = field(init=False, repr=False, default=None)
    _lock: object = field(init=False, repr=False, default_factory=threading.RLock)

    def __post_init__(self) -> None:
        return None

    def _ensure_model(self):
        with self._lock:
            if self._model is not None:
                return self._model

            with timed_operation(
                LOGGER,
                "reranker.model_load",
                model_name=self.model_name,
                device=self.device,
                dtype=self.dtype,
            ):
                try:
                    self._model = create_flag_reranker(
                        self.model_name,
                        device=self.device,
                        use_fp16=self.dtype.lower() == "float16",
                        hf_cache=self.hf_cache,
                    )
                except VendorFlagEmbeddingError as exc:  # pragma: no cover - depends on optional dependency
                    raise RetrievalError(f"failed to load reranker model: {self.model_name}") from exc
                return self._model

    def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievedChunk],
        top_k: int | None = None,
    ) -> Sequence[RetrievedChunk]:
        if not candidates:
            return ()

        pairs = [[query, candidate.content] for candidate in candidates]
        score_functions = ("compute_score", "score", "predict")
        scores: list[float] | None = None
        last_error: Exception | None = None

        with timed_operation(
            LOGGER,
            "reranker.score",
            model_name=self.model_name,
            candidate_count=len(candidates),
            batch_size=self.batch_size,
            top_k=top_k,
        ):
            with self._lock:
                model = self._ensure_model()
                for name in score_functions:
                    method = getattr(model, name, None)
                    if not callable(method):
                        continue
                    try:
                        try:
                            raw = method(pairs, batch_size=self.batch_size)
                        except TypeError:
                            raw = method(pairs)
                    except Exception as exc:  # pragma: no cover - depends on optional dependency
                        last_error = exc
                        continue
                    scores = _coerce_scores(raw, len(candidates))
                    if scores:
                        break

        if scores is None:
            raise RetrievalError("reranker model did not expose a usable scoring API") from last_error

        if len(scores) < len(candidates):
            pad_value = scores[-1] if scores else 0.0
            scores.extend([pad_value] * (len(candidates) - len(scores)))
        elif len(scores) > len(candidates):
            scores = scores[: len(candidates)]

        ranked: list[RetrievedChunk] = []
        for index, (candidate, score) in enumerate(zip(candidates, scores, strict=False), start=1):
            metadata = dict(candidate.metadata)
            metadata["rerank_rank"] = index
            metadata["rerank_raw_score"] = float(score)
            metadata["rerank_score"] = _normalize_score(float(score))
            ranked.append(replace(candidate, score=float(metadata["rerank_score"]), metadata=metadata))

        ranked.sort(key=lambda item: (-float(item.score or 0.0), item.chunk_id or item.document_id))
        if top_k is not None:
            return tuple(ranked[: max(0, int(top_k))])
        return tuple(ranked)

    def close(self) -> None:
        with self._lock:
            model = self._model
            self._model = None

        if model is None:
            return

        with timed_operation(LOGGER, "reranker.close", model_name=self.model_name, device=self.device):
            best_effort_close(model)
            best_effort_release_runtime_resources()


def build_reranker(
    model_name: str,
    *,
    device: str = "cpu",
    dtype: str = "float32",
    batch_size: int = 32,
    hf_cache: str | Path | None = None,
) -> RerankerProtocol:
    if _is_debug_model_name(model_name):
        return DebugReranker()
    return FlagEmbeddingReranker(
        model_name,
        device=device,
        dtype=dtype,
        batch_size=batch_size,
        hf_cache=hf_cache,
    )
