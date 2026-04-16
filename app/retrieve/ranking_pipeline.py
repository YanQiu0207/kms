from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import re
from typing import Callable, Sequence

from app.config import AppConfig
from app.metadata_utils import (
    CATEGORY_METADATA_MAX_SEQUENCE_ITEMS,
    CATEGORY_METADATA_SCALAR_FIELDS,
    CATEGORY_METADATA_SEQUENCE_FIELDS,
    LOOKUP_QUERY_STOPWORDS,
    METADATA_CONSTRAINT_STOPWORDS,
    chunk_text_values,
    metadata_text_values,
    normalize_metadata,
)
from app.query_understanding import QueryProfile, analyze_query_profile, extract_alias_subject_terms
from app.retrieval_pipeline_config import (
    DEFAULT_RANKING_PIPELINE_STEPS,
    DEFINITION_SUBJECT_STEP,
    LIMIT_RERANK_CANDIDATES_STEP,
    LOOKUP_DIVERSIFICATION_STEP,
    LOOKUP_PRIORITIZATION_STEP,
    METADATA_CONSTRAINTS_POST_RERANK_STEP,
    METADATA_CONSTRAINTS_PRE_RERANK_STEP,
    METADATA_DOCUMENT_SUPPORT_STEP,
    RERANK_STEP,
    SCORE_FILTER_STEP,
    TOP_K_LIMIT_STEP,
)
from app.store import tokenize_fts

from .contracts import RetrievedChunk
from .rerank import RerankerProtocol

_CATEGORY_CONSTRAINT_RE = re.compile(r"(?P<prefix>[\u4e00-\u9fffA-Za-z0-9_./+\-\s]{1,24})\s*分类(?:下|里|中|内)?")
_CONTEXT_CONSTRAINT_RE = re.compile(r"(?P<prefix>[\u4e00-\u9fffA-Za-z0-9_./+\-\s]{1,32})\s*(?:里|里面)")
_LOOKUP_INTENT_HINTS = (
    "缩写",
    "简称",
    "哪个命令",
    "什么命令",
    "命令可以",
    "哪些参数",
    "什么参数",
    "对应哪些宏",
    "什么文件类型",
    "文件类型",
    "缺点",
)
_LOOKUP_GENERIC_PATH_TERMS = {
    "基础知识",
    "常用命令详解",
    "命令详解",
    "常用命令",
    "详解",
    "基础",
    "入门",
}
_LOOKUP_INFO_RE = re.compile(r"查看[\u4e00-\u9fffA-Za-z0-9_/\-+\s]{0,12}信息")


@dataclass(slots=True)
class _LookupIntent:
    enabled: bool = False
    terms: tuple[str, ...] = ()


@dataclass(slots=True)
class RankingPipelineContext:
    config: AppConfig
    queries: tuple[str, ...]
    reranker: RerankerProtocol
    rerank_top_k: int | None
    query_profile: QueryProfile | None = None
    alias_groups: tuple[tuple[str, ...], ...] = ()
    counts: dict[str, int] = field(default_factory=dict)


def _filter_low_score_results(results: Sequence[RetrievedChunk], *, min_output_score: float) -> tuple[RetrievedChunk, ...]:
    threshold = max(0.0, float(min_output_score))
    if threshold <= 0.0:
        return tuple(results)
    return tuple(chunk for chunk in results if float(chunk.score or 0.0) >= threshold)


def _limit_rerank_candidates(results: Sequence[RetrievedChunk], *, candidate_limit: int) -> tuple[RetrievedChunk, ...]:
    limit = max(0, int(candidate_limit))
    if limit <= 0:
        return tuple(results)
    return tuple(results[:limit])


def _limit_output_results(results: Sequence[RetrievedChunk], *, top_k: int | None) -> tuple[RetrievedChunk, ...]:
    if top_k is None:
        return tuple(results)
    limit = max(0, int(top_k))
    if limit <= 0:
        return ()
    return tuple(results[:limit])


def _normalize_constraint_tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in tokenize_fts(text).split():
        token = raw.strip()
        if not token or token in METADATA_CONSTRAINT_STOPWORDS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tuple(tokens)


def _collect_query_metadata_constraints(queries: Sequence[str]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    constraints: list[tuple[str, tuple[str, ...]]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for query in queries:
        for match in _CATEGORY_CONSTRAINT_RE.finditer(query):
            tokens = _normalize_constraint_tokens(match.group("prefix"))
            if not tokens:
                continue
            item = ("category", tokens)
            if item not in seen:
                seen.add(item)
                constraints.append(item)
        for match in _CONTEXT_CONSTRAINT_RE.finditer(query):
            prefix = match.group("prefix")
            if "分类" in prefix:
                continue
            tokens = _normalize_constraint_tokens(prefix)
            if not tokens:
                continue
            item = ("context", tokens)
            if item not in seen:
                seen.add(item)
                constraints.append(item)
    return tuple(constraints)


def _metadata_token_set(candidate: RetrievedChunk, *, category_only: bool) -> set[str]:
    values = metadata_text_values(
        candidate.metadata,
        scalar_fields=CATEGORY_METADATA_SCALAR_FIELDS if category_only else (),
        sequence_fields=CATEGORY_METADATA_SEQUENCE_FIELDS if category_only else (),
        max_sequence_items=CATEGORY_METADATA_MAX_SEQUENCE_ITEMS if category_only else None,
    )
    if not category_only:
        values = metadata_text_values(candidate.metadata)
    return {token for token in tokenize_fts(" ".join(values)).split() if token}


def _apply_query_metadata_constraints(
    candidates: Sequence[RetrievedChunk],
    queries: Sequence[str],
) -> tuple[RetrievedChunk, ...]:
    if not candidates:
        return ()

    constraints = _collect_query_metadata_constraints(queries)
    if not constraints:
        return tuple(candidates)

    annotated: list[RetrievedChunk] = []
    for candidate in candidates:
        metadata = normalize_metadata(candidate.metadata)
        coverage_values: list[float] = []
        constraint_records: list[dict[str, object]] = []
        passed = True
        for kind, tokens in constraints:
            token_set = _metadata_token_set(candidate, category_only=(kind == "category"))
            matched = tuple(token for token in tokens if token in token_set)
            coverage = len(matched) / max(len(tokens), 1)
            coverage_values.append(coverage)
            constraint_records.append(
                {
                    "kind": kind,
                    "tokens": list(tokens),
                    "matched": list(matched),
                    "coverage": round(coverage, 4),
                }
            )
            if not matched:
                passed = False

        metadata["query_metadata_constraints"] = constraint_records
        metadata["metadata_constraint_passed"] = passed
        metadata["metadata_constraint_coverage"] = round(
            sum(coverage_values) / max(len(coverage_values), 1),
            4,
        )
        annotated.append(replace(candidate, metadata=metadata))

    matched_candidates = [candidate for candidate in annotated if candidate.metadata.get("metadata_constraint_passed")]
    if not matched_candidates:
        return ()

    prioritized: list[RetrievedChunk] = []
    for candidate in matched_candidates:
        coverage = float(candidate.metadata.get("metadata_constraint_coverage", 0.0) or 0.0)
        base_score = float(candidate.score or 0.0)
        lexical_score = float(candidate.metadata.get("lexical_score", 0.0) or 0.0)
        source_hits = candidate.metadata.get("source_hits")
        query_variant_hits = len(source_hits) if isinstance(source_hits, list) else 0
        metadata_support_score = min(
            0.55,
            0.22
            + (0.12 * coverage)
            + (0.25 * lexical_score)
            + (0.03 * max(query_variant_hits - 1, 0)),
        )
        prioritized.append(replace(candidate, score=max(base_score, metadata_support_score)))

    prioritized.sort(
        key=lambda item: (
            -float(item.metadata.get("metadata_constraint_coverage", 0.0) or 0.0),
            -float(item.score or 0.0),
            item.chunk_id or item.document_id,
        )
    )
    return tuple(prioritized)


def _metadata_document_key(candidate: RetrievedChunk) -> str:
    return candidate.file_path or candidate.document_id or candidate.chunk_id


def _normalize_subject_text(value: str) -> str:
    return value.strip().casefold()


def _candidate_definition_subject_affinity(candidate: RetrievedChunk, *, subject_terms: Sequence[str]) -> int:
    if not subject_terms:
        return 0

    normalized_subjects = tuple(_normalize_subject_text(term) for term in subject_terms if term and term.strip())
    if not normalized_subjects:
        return 0

    title_path = tuple(_normalize_subject_text(title) for title in candidate.title_path if title and title.strip())
    top_title = title_path[0] if title_path else ""
    file_stem = _normalize_subject_text(Path(candidate.file_path).stem) if candidate.file_path else ""
    if any(subject == top_title for subject in normalized_subjects):
        return 3
    if any(subject == title for subject in normalized_subjects for title in title_path[1:]):
        return 2
    if any(subject == file_stem for subject in normalized_subjects):
        return 2
    if any(subject in title for subject in normalized_subjects for title in title_path):
        return 1
    if any(subject in file_stem for subject in normalized_subjects):
        return 1
    return 0


def _prioritize_definition_subject_candidates(
    candidates: Sequence[RetrievedChunk],
    queries: Sequence[str],
    *,
    profile: QueryProfile | None = None,
    alias_groups: Sequence[Sequence[str]] | None = None,
) -> tuple[RetrievedChunk, ...]:
    if not candidates:
        return ()

    profile = profile or analyze_query_profile(queries[0] if queries else None, queries, alias_groups=alias_groups)
    if profile.query_type != "definition":
        return tuple(candidates)

    subject_terms = profile.alias_subject_terms
    if not subject_terms:
        deduped: list[str] = []
        seen: set[str] = set()
        for query in queries:
            for term in extract_alias_subject_terms(query, alias_groups=alias_groups):
                if term in seen:
                    continue
                seen.add(term)
                deduped.append(term)
        subject_terms = tuple(deduped)
    if not subject_terms:
        return tuple(candidates)

    doc_support_counts: dict[str, int] = {}
    doc_best_affinity: dict[str, int] = {}
    annotated: list[RetrievedChunk] = []
    for candidate in candidates:
        document_key = _metadata_document_key(candidate)
        affinity = _candidate_definition_subject_affinity(candidate, subject_terms=subject_terms)
        doc_support_counts[document_key] = doc_support_counts.get(document_key, 0) + 1
        doc_best_affinity[document_key] = max(doc_best_affinity.get(document_key, 0), affinity)
        metadata = normalize_metadata(candidate.metadata)
        metadata["definition_subject_affinity"] = affinity
        annotated.append(replace(candidate, metadata=metadata))

    if max(doc_best_affinity.values(), default=0) <= 0:
        return tuple(candidates)

    annotated.sort(
        key=lambda item: (
            -int(doc_best_affinity.get(_metadata_document_key(item), 0)),
            -int(item.metadata.get("definition_subject_affinity", 0) or 0),
            -int(doc_support_counts.get(_metadata_document_key(item), 0)),
            -float(item.score or 0.0),
            item.chunk_id or item.document_id,
        )
    )
    return tuple(annotated)


def _collect_lookup_intent(queries: Sequence[str]) -> _LookupIntent:
    joined = " ".join(query.strip() for query in queries if query and query.strip())
    normalized = joined.replace("？", "?").replace("，", ",")
    enabled = any(hint in normalized for hint in _LOOKUP_INTENT_HINTS) or bool(_LOOKUP_INFO_RE.search(normalized))
    if not enabled:
        return _LookupIntent()

    terms: list[str] = []
    seen: set[str] = set()
    for token in tokenize_fts(normalized).split():
        cleaned = token.strip()
        if not cleaned or cleaned in LOOKUP_QUERY_STOPWORDS or cleaned in METADATA_CONSTRAINT_STOPWORDS or cleaned in seen:
            continue
        seen.add(cleaned)
        terms.append(cleaned)
    return _LookupIntent(enabled=True, terms=tuple(terms))


def _candidate_lookup_term_set(candidate: RetrievedChunk) -> set[str]:
    parts = chunk_text_values(
        candidate,
        include_content=True,
        include_title_path=True,
        include_file_stem=True,
        include_file_path_parts=4,
    )
    return {token for token in tokenize_fts(" ".join(part for part in parts if part)).split() if token}


def _lookup_path_specificity(candidate: RetrievedChunk) -> float:
    if not candidate.file_path:
        return 0.0
    stem = Path(candidate.file_path).stem.strip()
    if not stem:
        return 0.0
    return 0.0 if stem in _LOOKUP_GENERIC_PATH_TERMS else 1.0


def _prioritize_lookup_candidates(
    candidates: Sequence[RetrievedChunk],
    queries: Sequence[str],
) -> tuple[RetrievedChunk, ...]:
    if not candidates:
        return ()

    intent = _collect_lookup_intent(queries)
    if not intent.enabled or not intent.terms:
        return tuple(candidates)

    annotated: list[RetrievedChunk] = []
    for candidate in candidates:
        metadata = normalize_metadata(candidate.metadata)
        term_set = _candidate_lookup_term_set(candidate)
        matched_terms = tuple(term for term in intent.terms if term in term_set)
        coverage = len(matched_terms) / max(len(intent.terms), 1)
        table_row_count = str(candidate.content or "").count("表格行:")
        metadata["lookup_query_terms"] = list(intent.terms)
        metadata["lookup_matched_terms"] = list(matched_terms)
        metadata["lookup_term_coverage"] = round(coverage, 4)
        metadata["lookup_table_row_count"] = table_row_count
        metadata["lookup_path_specificity"] = _lookup_path_specificity(candidate)
        annotated.append(replace(candidate, metadata=metadata))

    annotated.sort(
        key=lambda item: (
            -float(item.metadata.get("lookup_term_coverage", 0.0) or 0.0),
            -int(item.metadata.get("lookup_table_row_count", 0) or 0),
            -int(len(item.metadata.get("lookup_matched_terms", []) or [])),
            -float(item.metadata.get("lookup_path_specificity", 0.0) or 0.0),
            -float(item.score or 0.0),
            item.chunk_id or item.document_id,
        )
    )
    return tuple(annotated)


def _diversify_lookup_documents(
    candidates: Sequence[RetrievedChunk],
    queries: Sequence[str],
) -> tuple[RetrievedChunk, ...]:
    if not candidates:
        return ()

    intent = _collect_lookup_intent(queries)
    if not intent.enabled:
        return tuple(candidates)

    per_document: dict[str, list[RetrievedChunk]] = {}
    order: list[str] = []
    for candidate in candidates:
        key = _metadata_document_key(candidate)
        if key not in per_document:
            order.append(key)
            per_document[key] = []
        per_document[key].append(candidate)

    if len(order) < 2:
        return tuple(candidates)

    diversified: list[RetrievedChunk] = [candidates[0]]
    leader_key = _metadata_document_key(candidates[0])
    if per_document.get(leader_key):
        per_document[leader_key].pop(0)

    active = True
    while active:
        active = False
        for key in order:
            bucket = per_document[key]
            if not bucket:
                continue
            diversified.append(bucket.pop(0))
            active = True
    return tuple(diversified)


def _prioritize_metadata_document_support(candidates: Sequence[RetrievedChunk]) -> tuple[RetrievedChunk, ...]:
    if not candidates:
        return ()

    constrained = [candidate for candidate in candidates if candidate.metadata.get("metadata_constraint_passed")]
    if len(constrained) < 2:
        return tuple(candidates)

    doc_support_counts: dict[str, int] = {}
    doc_best_lexical_scores: dict[str, float] = {}
    for candidate in constrained:
        document_key = _metadata_document_key(candidate)
        doc_support_counts[document_key] = doc_support_counts.get(document_key, 0) + 1
        lexical_score = float(candidate.metadata.get("lexical_score", 0.0) or 0.0)
        doc_best_lexical_scores[document_key] = max(doc_best_lexical_scores.get(document_key, 0.0), lexical_score)

    if len(doc_support_counts) < 2:
        return tuple(candidates)

    annotated: list[RetrievedChunk] = []
    for candidate in constrained:
        document_key = _metadata_document_key(candidate)
        metadata = normalize_metadata(candidate.metadata)
        metadata["metadata_document_support_count"] = doc_support_counts.get(document_key, 0)
        metadata["metadata_document_lexical_max"] = round(doc_best_lexical_scores.get(document_key, 0.0), 4)
        annotated.append(replace(candidate, metadata=metadata))

    annotated.sort(
        key=lambda item: (
            -float(item.metadata.get("metadata_constraint_coverage", 0.0) or 0.0),
            -int(item.metadata.get("metadata_document_support_count", 0) or 0),
            -float(item.metadata.get("metadata_document_lexical_max", 0.0) or 0.0),
            -float(item.score or 0.0),
            item.chunk_id or item.document_id,
        )
    )
    return tuple(annotated)


def _unique_queries(queries: Sequence[str]) -> tuple[str, ...]:
    unique_queries: list[str] = []
    seen: set[str] = set()
    for query in queries:
        if query in seen:
            continue
        seen.add(query)
        unique_queries.append(query)
    return tuple(unique_queries)


def _rerank_candidates(
    reranker: RerankerProtocol,
    queries: Sequence[str],
    candidates: Sequence[RetrievedChunk],
    *,
    top_k: int | None = None,
) -> tuple[RetrievedChunk, ...]:
    if not candidates:
        return ()

    unique_queries = _unique_queries(queries)
    if not unique_queries:
        return ()

    if len(unique_queries) == 1:
        return tuple(reranker.rerank(unique_queries[0], candidates, top_k=top_k))

    best_by_chunk_id: dict[str, RetrievedChunk] = {}
    for query in unique_queries:
        reranked = reranker.rerank(query, candidates, top_k=None)
        for rank, chunk in enumerate(reranked, start=1):
            chunk_id = chunk.chunk_id or chunk.document_id
            metadata = normalize_metadata(chunk.metadata)
            metadata["rerank_query"] = query
            metadata["rerank_query_rank"] = rank
            reranked_chunk = replace(chunk, metadata=metadata)
            current = best_by_chunk_id.get(chunk_id)
            if current is None or float(reranked_chunk.score or 0.0) > float(current.score or 0.0):
                best_by_chunk_id[chunk_id] = reranked_chunk

    merged = sorted(
        best_by_chunk_id.values(),
        key=lambda item: (-float(item.score or 0.0), item.chunk_id or item.document_id),
    )
    if top_k is not None:
        return tuple(merged[: max(0, int(top_k))])
    return tuple(merged)


def _step_limit_rerank_candidates(candidates: Sequence[RetrievedChunk], context: RankingPipelineContext) -> tuple[RetrievedChunk, ...]:
    limited = _limit_rerank_candidates(
        candidates,
        candidate_limit=context.config.retrieval.rerank_candidate_limit,
    )
    context.counts["candidate_count"] = len(limited)
    return limited


def _step_metadata_constraints_pre(candidates: Sequence[RetrievedChunk], context: RankingPipelineContext) -> tuple[RetrievedChunk, ...]:
    constrained = _apply_query_metadata_constraints(candidates, context.queries)
    context.counts["constrained_candidate_count"] = len(constrained)
    return constrained


def _step_rerank(candidates: Sequence[RetrievedChunk], context: RankingPipelineContext) -> tuple[RetrievedChunk, ...]:
    reranked = _rerank_candidates(
        context.reranker,
        context.queries,
        candidates,
        top_k=None,
    )
    context.counts["reranked_candidate_count"] = len(reranked)
    return reranked


def _step_metadata_constraints_post(candidates: Sequence[RetrievedChunk], context: RankingPipelineContext) -> tuple[RetrievedChunk, ...]:
    constrained = _apply_query_metadata_constraints(candidates, context.queries)
    context.counts["post_constraint_count"] = len(constrained)
    return constrained


def _step_lookup_prioritization(candidates: Sequence[RetrievedChunk], context: RankingPipelineContext) -> tuple[RetrievedChunk, ...]:
    return _prioritize_lookup_candidates(candidates, context.queries)


def _step_metadata_document_support(candidates: Sequence[RetrievedChunk], context: RankingPipelineContext) -> tuple[RetrievedChunk, ...]:
    return _prioritize_metadata_document_support(candidates)


def _step_definition_subject(candidates: Sequence[RetrievedChunk], context: RankingPipelineContext) -> tuple[RetrievedChunk, ...]:
    return _prioritize_definition_subject_candidates(
        candidates,
        context.queries,
        profile=context.query_profile,
        alias_groups=context.alias_groups,
    )


def _step_lookup_diversification(candidates: Sequence[RetrievedChunk], context: RankingPipelineContext) -> tuple[RetrievedChunk, ...]:
    return _diversify_lookup_documents(candidates, context.queries)


def _step_score_filter(candidates: Sequence[RetrievedChunk], context: RankingPipelineContext) -> tuple[RetrievedChunk, ...]:
    return _filter_low_score_results(
        candidates,
        min_output_score=context.config.retrieval.min_output_score,
    )


def _step_top_k_limit(candidates: Sequence[RetrievedChunk], context: RankingPipelineContext) -> tuple[RetrievedChunk, ...]:
    return _limit_output_results(candidates, top_k=context.rerank_top_k)


RANKING_STEP_REGISTRY: dict[str, Callable[[Sequence[RetrievedChunk], RankingPipelineContext], tuple[RetrievedChunk, ...]]] = {
    LIMIT_RERANK_CANDIDATES_STEP: _step_limit_rerank_candidates,
    METADATA_CONSTRAINTS_PRE_RERANK_STEP: _step_metadata_constraints_pre,
    RERANK_STEP: _step_rerank,
    METADATA_CONSTRAINTS_POST_RERANK_STEP: _step_metadata_constraints_post,
    LOOKUP_PRIORITIZATION_STEP: _step_lookup_prioritization,
    METADATA_DOCUMENT_SUPPORT_STEP: _step_metadata_document_support,
    DEFINITION_SUBJECT_STEP: _step_definition_subject,
    LOOKUP_DIVERSIFICATION_STEP: _step_lookup_diversification,
    SCORE_FILTER_STEP: _step_score_filter,
    TOP_K_LIMIT_STEP: _step_top_k_limit,
}


def run_ranking_pipeline(
    candidates: Sequence[RetrievedChunk],
    *,
    context: RankingPipelineContext,
    steps: Sequence[str] | None = None,
) -> tuple[RetrievedChunk, ...]:
    active_steps = tuple(steps or DEFAULT_RANKING_PIPELINE_STEPS)
    current = tuple(candidates)
    for step_name in active_steps:
        current = RANKING_STEP_REGISTRY[step_name](current, context)
    return current
