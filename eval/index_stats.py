from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median
from typing import Iterable, Sequence

from app.config import AppConfig, load_config
from app.store import SQLiteMetadataStore, StoredChunk, StoredDocument

_WHITESPACE_RE = re.compile(r"\s+")


def _round_float(value: float) -> float:
    return round(float(value), 4)


def _normalize_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def _preview_text(value: str, *, limit: int = 120) -> str:
    preview = _normalize_text(value)
    if len(preview) <= limit:
        return preview
    return f"{preview[: limit - 3]}..."


def _numeric_summary(values: Sequence[int]) -> dict[str, float | int]:
    if not values:
        return {
            "count": 0,
            "min": 0,
            "max": 0,
            "avg": 0.0,
            "median": 0.0,
        }

    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "avg": _round_float(sum(values) / len(values)),
        "median": _round_float(float(median(values))),
    }


@dataclass(slots=True)
class RepeatedSnippet:
    normalized_preview: str
    occurrences: int
    sample_chunk_ids: tuple[str, ...] = ()
    sample_file_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class SourceStats:
    source_id: str
    document_count: int
    chunk_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class IndexStatsSnapshot:
    sqlite_path: str
    document_count: int
    chunk_count: int
    chunk_length_chars: dict[str, float | int]
    chunk_token_count: dict[str, float | int]
    chunks_per_document: dict[str, float | int]
    exact_duplicate_groups: int
    exact_duplicate_chunk_count: int
    exact_duplicate_chunk_ratio: float
    top_repeated_snippets: list[RepeatedSnippet] = field(default_factory=list)
    by_source: list[SourceStats] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["top_repeated_snippets"] = [item.to_dict() for item in self.top_repeated_snippets]
        payload["by_source"] = [item.to_dict() for item in self.by_source]
        return payload


def _build_source_stats(
    documents: Sequence[StoredDocument],
    chunks: Sequence[StoredChunk],
) -> list[SourceStats]:
    document_counts: Counter[str] = Counter()
    chunk_counts: Counter[str] = Counter()
    document_source_map: dict[str, str] = {}

    for document in documents:
        source_id = str(document.metadata.get("source_id") or "")
        if not source_id:
            source_id = "(unknown)"
        document_source_map[document.document_id] = source_id
        document_counts[source_id] += 1

    for chunk in chunks:
        source_id = document_source_map.get(chunk.document_id, "(unknown)")
        chunk_counts[source_id] += 1

    rows = []
    for source_id in sorted(set(document_counts) | set(chunk_counts)):
        rows.append(
            SourceStats(
                source_id=source_id,
                document_count=int(document_counts.get(source_id, 0)),
                chunk_count=int(chunk_counts.get(source_id, 0)),
            )
        )
    return rows


def _build_repeated_snippets(chunks: Sequence[StoredChunk], *, limit: int = 10) -> tuple[int, int, list[RepeatedSnippet]]:
    grouped: dict[str, list[StoredChunk]] = defaultdict(list)
    for chunk in chunks:
        normalized = _normalize_text(chunk.content)
        if not normalized:
            continue
        grouped[normalized].append(chunk)

    repeated_groups = [(text, items) for text, items in grouped.items() if len(items) > 1]
    repeated_groups.sort(key=lambda item: (-len(item[1]), item[0]))

    repeated_snippets: list[RepeatedSnippet] = []
    duplicate_chunk_count = 0
    for normalized, items in repeated_groups[:limit]:
        duplicate_chunk_count += len(items) - 1
        repeated_snippets.append(
            RepeatedSnippet(
                normalized_preview=_preview_text(normalized),
                occurrences=len(items),
                sample_chunk_ids=tuple(chunk.chunk_id for chunk in items[:3]),
                sample_file_paths=tuple(chunk.file_path for chunk in items[:3]),
            )
        )

    if len(repeated_groups) > limit:
        for _, items in repeated_groups[limit:]:
            duplicate_chunk_count += len(items) - 1

    return len(repeated_groups), duplicate_chunk_count, repeated_snippets


def snapshot_index_stats(sqlite_path: str | Path) -> IndexStatsSnapshot:
    sqlite_file = Path(sqlite_path)
    with SQLiteMetadataStore(sqlite_file, initialize=False) as store:
        documents = tuple(store.iter_documents())
        chunks = tuple(store.iter_chunks())

    chunk_lengths = [len(chunk.content) for chunk in chunks]
    chunk_tokens = [int(chunk.token_count or 0) for chunk in chunks]

    chunks_per_document_counter: Counter[str] = Counter(chunk.document_id for chunk in chunks)
    chunks_per_document = list(chunks_per_document_counter.values())

    duplicate_groups, duplicate_chunk_count, repeated_snippets = _build_repeated_snippets(chunks)
    duplicate_ratio = 0.0 if not chunks else _round_float(duplicate_chunk_count / len(chunks))

    return IndexStatsSnapshot(
        sqlite_path=str(sqlite_file),
        document_count=len(documents),
        chunk_count=len(chunks),
        chunk_length_chars=_numeric_summary(chunk_lengths),
        chunk_token_count=_numeric_summary(chunk_tokens),
        chunks_per_document=_numeric_summary(chunks_per_document),
        exact_duplicate_groups=duplicate_groups,
        exact_duplicate_chunk_count=duplicate_chunk_count,
        exact_duplicate_chunk_ratio=duplicate_ratio,
        top_repeated_snippets=repeated_snippets,
        by_source=_build_source_stats(documents, chunks),
    )


def snapshot_index_stats_for_config(config: AppConfig | None = None) -> IndexStatsSnapshot:
    settings = config or load_config()
    return snapshot_index_stats(settings.data.sqlite)


def compare_index_stats_payloads(
    baseline: dict[str, object],
    candidate: dict[str, object],
) -> dict[str, object]:
    def metric(name: str, base: float | int, next_value: float | int) -> dict[str, object]:
        delta = _round_float(float(next_value) - float(base))
        return {
            "baseline": base,
            "candidate": next_value,
            "delta": delta,
        }

    baseline_lengths = dict(baseline.get("chunk_length_chars") or {})
    candidate_lengths = dict(candidate.get("chunk_length_chars") or {})
    baseline_tokens = dict(baseline.get("chunk_token_count") or {})
    candidate_tokens = dict(candidate.get("chunk_token_count") or {})
    baseline_per_doc = dict(baseline.get("chunks_per_document") or {})
    candidate_per_doc = dict(candidate.get("chunks_per_document") or {})

    baseline_sources = {str(item.get("source_id") or ""): item for item in baseline.get("by_source") or []}
    candidate_sources = {str(item.get("source_id") or ""): item for item in candidate.get("by_source") or []}
    source_deltas: dict[str, dict[str, object]] = {}
    for source_id in sorted(set(baseline_sources) | set(candidate_sources)):
        base_row = baseline_sources.get(source_id, {})
        next_row = candidate_sources.get(source_id, {})
        source_deltas[source_id] = {
            "document_count": metric(
                "document_count",
                int(base_row.get("document_count", 0) or 0),
                int(next_row.get("document_count", 0) or 0),
            ),
            "chunk_count": metric(
                "chunk_count",
                int(base_row.get("chunk_count", 0) or 0),
                int(next_row.get("chunk_count", 0) or 0),
            ),
        }

    return {
        "document_count": metric(
            "document_count",
            int(baseline.get("document_count", 0) or 0),
            int(candidate.get("document_count", 0) or 0),
        ),
        "chunk_count": metric(
            "chunk_count",
            int(baseline.get("chunk_count", 0) or 0),
            int(candidate.get("chunk_count", 0) or 0),
        ),
        "exact_duplicate_groups": metric(
            "exact_duplicate_groups",
            int(baseline.get("exact_duplicate_groups", 0) or 0),
            int(candidate.get("exact_duplicate_groups", 0) or 0),
        ),
        "exact_duplicate_chunk_count": metric(
            "exact_duplicate_chunk_count",
            int(baseline.get("exact_duplicate_chunk_count", 0) or 0),
            int(candidate.get("exact_duplicate_chunk_count", 0) or 0),
        ),
        "exact_duplicate_chunk_ratio": metric(
            "exact_duplicate_chunk_ratio",
            float(baseline.get("exact_duplicate_chunk_ratio", 0.0) or 0.0),
            float(candidate.get("exact_duplicate_chunk_ratio", 0.0) or 0.0),
        ),
        "chunk_length_chars": {
            key: metric(
                key,
                float(baseline_lengths.get(key, 0.0) or 0.0),
                float(candidate_lengths.get(key, 0.0) or 0.0),
            )
            for key in ("avg", "median", "min", "max")
        },
        "chunk_token_count": {
            key: metric(
                key,
                float(baseline_tokens.get(key, 0.0) or 0.0),
                float(candidate_tokens.get(key, 0.0) or 0.0),
            )
            for key in ("avg", "median", "min", "max")
        },
        "chunks_per_document": {
            key: metric(
                key,
                float(baseline_per_doc.get(key, 0.0) or 0.0),
                float(candidate_per_doc.get(key, 0.0) or 0.0),
            )
            for key in ("avg", "median", "min", "max")
        },
        "by_source": source_deltas,
    }

