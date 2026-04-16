"""M2/M3 查询服务。"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
import inspect
from pathlib import Path, PurePath
import re
from typing import Sequence

from app.answer import build_evidence_sources, build_prompt_package, evaluate_abstain, verify_citations
from app.config import AppConfig
from app.observability import get_logger, timed_operation
from app.query_understanding import (
    QueryProfile,
    analyze_query_profile,
    build_alias_groups_from_front_matter,
    build_query_variants,
    route_retrieval,
)
from app.retrieve import HybridRetrievalService, RetrievedChunk
from app.store import SQLiteMetadataStore, tokenize_fts

LOGGER = get_logger("kms.query")


_LOW_SIGNAL_QUERY_TOKENS = {
    "什么",
    "哪些",
    "哪种",
    "哪几种",
    "为何",
    "为什么",
    "如何",
    "怎么",
    "有没有",
    "介绍",
    "一下",
    "一下子",
    "请问",
    "的",
    "了",
    "吗",
    "呢",
    "各",
    "各有",
    "有",
    "有什么",
    "是",
    "包括",
    "一下",
    "一下子",
    "一下啊",
    "一下呢",
}
_QUERY_COVERAGE_LOW_SIGNAL_TOKENS = _LOW_SIGNAL_QUERY_TOKENS | {
    "机制",
    "价值",
    "作用",
    "问题",
    "优点",
    "缺点",
    "改进",
    "特点",
    "思路",
    "场景",
    "概念",
    "原理",
    "基础",
    "核心",
    "关键",
    "详细",
    "常见",
    "主要",
    "相比",
    "什么",
    "哪些",
    "知识库",
    "文档",
    "笔记",
    "资料",
    "讲",
    "里",
    "里面",
    "下",
    "中",
    "内",
}
_PUNCT_RE = re.compile(r"[\s\u3000,，.。!！?？:：;；、'\"“”‘’()\[\]{}<>《》]+")
_TOKEN_SIGNAL_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9_]+")


@dataclass(slots=True)
class AskServiceResult:
    abstained: bool
    confidence: float
    prompt: str
    sources: Sequence[dict[str, object]]
    abstain_reason: str | None = None


@dataclass(slots=True)
class _EvidenceDocumentProfile:
    document_key: str
    terms: set[str]
    hit_count: int


def _append_path_terms(parts: list[str], value: str) -> None:
    cleaned = value.strip()
    if not cleaned:
        return
    path = PurePath(cleaned.replace("\\", "/"))
    for segment in path.parts:
        normalized = segment.strip()
        if not normalized or normalized in {"/", "\\"}:
            continue
        if "." in normalized:
            stem = PurePath(normalized).stem.strip()
            if stem:
                parts.append(stem)
                continue
        parts.append(normalized)


class QueryService:
    """封装 `/search`、`/ask`、`/verify` 所需的查询流程。"""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._retrieval = HybridRetrievalService.from_config(config)
        self._search_cache: OrderedDict[tuple[tuple[str, ...], int | None, int | None], object] = OrderedDict()
        self._search_cache_limit = 64
        self._alias_groups_cache: tuple[tuple[str, ...], ...] | None = None

    def search(
        self,
        queries: Sequence[str],
        *,
        recall_top_k: int | None = None,
        rerank_top_k: int | None = None,
        query_profile: QueryProfile | None = None,
        expanded_queries: Sequence[str] | None = None,
    ):
        alias_groups = self._load_alias_groups()
        profile = query_profile or analyze_query_profile(None, queries, alias_groups=alias_groups)
        normalized_queries = (
            tuple(expanded_queries)
            if expanded_queries is not None
            else self._expand_queries(queries, profile=profile, alias_groups=alias_groups)
        )
        routed_recall_top_k, routed_rerank_top_k = route_retrieval(
            profile,
            default_recall_top_k=self.config.retrieval.recall_top_k,
            default_rerank_top_k=self.config.retrieval.rerank_top_k,
            recall_top_k=recall_top_k,
            rerank_top_k=rerank_top_k,
        )
        with timed_operation(
            LOGGER,
            "query.search",
            input_query_count=len(tuple(queries)),
            recall_top_k=routed_recall_top_k,
            rerank_top_k=routed_rerank_top_k,
            query_type=profile.query_type,
            route_policy=profile.route_policy,
        ) as span:
            span.set(expanded_query_count=len(normalized_queries))
            cache_key = (normalized_queries + (f"query_type:{profile.query_type}",), routed_recall_top_k, routed_rerank_top_k)
            cached = self._search_cache.get(cache_key)
            if cached is not None:
                self._search_cache.move_to_end(cache_key)
                span.set(cache_hit=True, result_count=len(cached.results))
                return cached

            result = self._search_and_rerank(
                normalized_queries,
                recall_top_k=routed_recall_top_k,
                rerank_top_k=routed_rerank_top_k,
                query_profile=profile,
                alias_groups=alias_groups,
            )
            self._search_cache[cache_key] = result
            self._search_cache.move_to_end(cache_key)
            while len(self._search_cache) > self._search_cache_limit:
                self._search_cache.popitem(last=False)
            span.set(cache_hit=False, result_count=len(result.results))
            return result

    def ask(
        self,
        question: str,
        *,
        queries: Sequence[str],
        recall_top_k: int | None = None,
        rerank_top_k: int | None = None,
    ) -> AskServiceResult:
        with timed_operation(
            LOGGER,
            "query.ask",
            question=question,
            recall_top_k=recall_top_k,
            rerank_top_k=rerank_top_k,
        ) as span:
            raw_queries = tuple(query.strip() for query in queries if query.strip()) or (question.strip(),)
            alias_groups = self._load_alias_groups()
            profile = analyze_query_profile(question, raw_queries, alias_groups=alias_groups)
            effective_queries = self._expand_queries(raw_queries, profile=profile, alias_groups=alias_groups)
            span.set(expanded_query_count=len(effective_queries))
            result_set = self.search(
                raw_queries,
                recall_top_k=recall_top_k,
                rerank_top_k=rerank_top_k,
                query_profile=profile,
                expanded_queries=effective_queries,
            )
            decision = self._evaluate_ask_decision(
                profile,
                effective_queries,
                result_set.results,
                event_name="query.ask.abstain",
            )

            if decision.abstained:
                span.set(
                    result_count=len(result_set.results),
                    source_count=0,
                    abstained=True,
                    confidence=decision.confidence,
                )
                return AskServiceResult(
                    abstained=True,
                    confidence=decision.confidence,
                    prompt="",
                    sources=[],
                    abstain_reason=decision.reason,
                )

            with timed_operation(LOGGER, "query.ask.prompt_build", result_count=len(result_set.results)):
                prompt_chunks = self._expand_prompt_evidence(result_set.results)
                package = build_prompt_package(
                    question,
                    prompt_chunks,
                    thresholds=self.config.abstain,
                    decision=decision,
                )
            sources = [
                {
                    "ref_index": source.ref_index,
                    "chunk_id": source.chunk_id,
                    "file_path": source.file_path,
                    "location": self._render_location(source.file_path, source.start_line, source.end_line),
                    "title_path": list(source.title_path),
                    "text": source.text,
                    "score": source.score,
                    "doc_id": source.doc_id,
                }
                for source in build_evidence_sources(package.chunks)
            ]
            span.set(
                result_count=len(result_set.results),
                source_count=len(sources),
                abstained=package.abstained,
                confidence=decision.confidence,
            )
            return AskServiceResult(
                abstained=package.abstained,
                confidence=decision.confidence,
                prompt=package.prompt,
                sources=sources,
                abstain_reason=package.abstain_reason,
            )

    def verify(self, answer: str, used_chunk_ids: Sequence[str]):
        with timed_operation(LOGGER, "query.verify", chunk_id_count=len(tuple(used_chunk_ids))):
            chunk_texts = self._load_chunk_texts(used_chunk_ids)
            return verify_citations(answer, used_chunk_ids, chunk_texts, self.config.verify)

    def warmup(self) -> None:
        with timed_operation(LOGGER, "query.warmup"):
            dummy = RetrievedChunk(
                document_id="warmup",
                chunk_id="warmup",
                content="warmup",
                score=1.0,
                metadata={"rrf_score": 1.0, "lexical_score": 1.0, "semantic_score": 1.0},
            )
            if self._retrieval.embedder is not None:
                self._retrieval.embedder.embed_texts(["warmup"])
            if self._retrieval.reranker is not None:
                self._retrieval.reranker.rerank("warmup", [dummy], top_k=1)
            tokenize_fts("warmup")

    def close(self) -> None:
        with timed_operation(LOGGER, "query.close", cache_size=len(self._search_cache)):
            self._search_cache.clear()
            close = getattr(self._retrieval, "close", None)
            if callable(close):
                close()

    def invalidate_cache(self) -> None:
        self._search_cache.clear()
        self._alias_groups_cache = None

    def _load_chunk_texts(self, chunk_ids: Sequence[str]) -> dict[str, str]:
        if not chunk_ids:
            return {}

        chunk_texts: dict[str, str] = {}
        sqlite_path = Path(self.config.data.sqlite)
        if not sqlite_path.exists():
            return chunk_texts

        store = SQLiteMetadataStore(self.config.data.sqlite)
        try:
            document_chunks_cache: dict[str, Sequence[object]] = {}
            for chunk_id in chunk_ids:
                chunk = store.get_chunk(chunk_id)
                if chunk is None:
                    continue
                expanded = self._expand_chunk_with_parent_context(
                    RetrievedChunk(
                        document_id=chunk.document_id,
                        content=chunk.content,
                        chunk_id=chunk.chunk_id,
                        file_path=chunk.file_path,
                        title_path=chunk.title_path,
                        metadata=dict(chunk.metadata),
                    ),
                    store=store,
                    document_chunks_cache=document_chunks_cache,
                )
                chunk_texts[chunk_id] = expanded.content
        finally:
            store.close()
        return chunk_texts

    def _expand_prompt_evidence(self, chunks: Sequence[RetrievedChunk]) -> tuple[RetrievedChunk, ...]:
        if not chunks or not self.config.retrieval.parent_context_enabled:
            return tuple(chunks)

        sqlite_path = Path(self.config.data.sqlite)
        if not sqlite_path.exists():
            return tuple(chunks)

        expanded: list[RetrievedChunk] = []
        store = SQLiteMetadataStore(self.config.data.sqlite)
        document_chunks_cache: dict[str, Sequence[object]] = {}
        try:
            for chunk in chunks:
                expanded.append(
                    self._expand_chunk_with_parent_context(
                        chunk,
                        store=store,
                        document_chunks_cache=document_chunks_cache,
                    )
                )
        finally:
            store.close()
        return tuple(expanded)

    def _expand_chunk_with_parent_context(
        self,
        chunk: RetrievedChunk,
        *,
        store: SQLiteMetadataStore,
        document_chunks_cache: dict[str, Sequence[object]],
    ) -> RetrievedChunk:
        if not self.config.retrieval.parent_context_enabled or not chunk.chunk_id:
            return chunk

        anchor = store.get_chunk(chunk.chunk_id)
        if anchor is None:
            return chunk

        cached_document_chunks = document_chunks_cache.get(anchor.document_id)
        if cached_document_chunks is None:
            cached_document_chunks = store.list_chunks_by_document(anchor.document_id)
            document_chunks_cache[anchor.document_id] = cached_document_chunks
        if not cached_document_chunks:
            return chunk

        max_chunks = max(1, int(self.config.retrieval.parent_context_max_chunks))
        selected = self._select_parent_context_chunks(cached_document_chunks, anchor_chunk=anchor, max_chunks=max_chunks)
        if not selected:
            return chunk

        merged_parts = [stored_chunk.content.strip() for stored_chunk in selected if stored_chunk.content.strip()]
        if not merged_parts:
            return chunk

        start_line = min(int(stored_chunk.metadata.get("start_line", 0) or 0) for stored_chunk in selected)
        end_line = max(int(stored_chunk.metadata.get("end_line", 0) or 0) for stored_chunk in selected)
        merged_text = "\n\n".join(merged_parts)
        metadata = dict(chunk.metadata or {})
        metadata["start_line"] = start_line
        metadata["end_line"] = end_line
        metadata["parent_context_applied"] = len(selected) > 1
        metadata["parent_context_chunk_ids"] = [stored_chunk.chunk_id for stored_chunk in selected]
        metadata["parent_context_chunk_count"] = len(selected)
        metadata["parent_context_anchor_chunk_id"] = anchor.chunk_id
        return replace(chunk, content=merged_text, text=merged_text, metadata=metadata)

    @staticmethod
    def _select_parent_context_chunks(document_chunks: Sequence[object], *, anchor_chunk: object, max_chunks: int) -> tuple[object, ...]:
        if max_chunks <= 1:
            return (anchor_chunk,)

        anchor_chunk_index = int(getattr(anchor_chunk, "chunk_index", 0) or 0)
        anchor_section_index = int(getattr(anchor_chunk, "metadata", {}).get("section_index", -1) or -1)
        same_section = tuple(
            stored_chunk
            for stored_chunk in document_chunks
            if int(getattr(stored_chunk, "metadata", {}).get("section_index", -1) or -1) == anchor_section_index
        )

        selected_ids: set[str] = set()
        selected: list[object] = []
        for candidate in QueryService._rank_parent_context_candidates(same_section or document_chunks, anchor_chunk_index):
            chunk_id = str(getattr(candidate, "chunk_id", "") or "")
            if chunk_id in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(chunk_id)
            if len(selected) >= max_chunks:
                break

        if len(selected) < max_chunks:
            for candidate in QueryService._rank_parent_context_candidates(document_chunks, anchor_chunk_index):
                chunk_id = str(getattr(candidate, "chunk_id", "") or "")
                if chunk_id in selected_ids:
                    continue
                selected.append(candidate)
                selected_ids.add(chunk_id)
                if len(selected) >= max_chunks:
                    break

        return tuple(
            sorted(
                selected,
                key=lambda item: (
                    int(getattr(item, "chunk_index", 0) or 0),
                    str(getattr(item, "chunk_id", "") or ""),
                ),
            )
        )

    @staticmethod
    def _rank_parent_context_candidates(document_chunks: Sequence[object], anchor_chunk_index: int) -> tuple[object, ...]:
        return tuple(
            sorted(
                document_chunks,
                key=lambda item: (
                    abs(int(getattr(item, "chunk_index", 0) or 0) - anchor_chunk_index),
                    int(getattr(item, "chunk_index", 0) or 0),
                    str(getattr(item, "chunk_id", "") or ""),
                ),
            )
        )

    def _evaluate_ask_decision(
        self,
        profile: QueryProfile,
        effective_queries: Sequence[str],
        results: Sequence[RetrievedChunk],
        *,
        event_name: str,
    ):
        with timed_operation(LOGGER, event_name, result_count=len(results)):
            decision = evaluate_abstain(results, self.config.abstain)
        decision = self._relax_query_profile_guardrail(profile, effective_queries, results, decision)
        if not decision.abstained:
            coverage_decision = self._evaluate_query_term_coverage(effective_queries, results)
            if not coverage_decision["passed"]:
                decision = coverage_decision["decision"]
        if not decision.abstained:
            profile_decision = self._evaluate_query_profile_guardrail(profile, effective_queries, results)
            if profile_decision is not None:
                decision = profile_decision
        return decision

    @staticmethod
    def _render_location(file_path: str, start_line: int, end_line: int) -> str:
        file_name = PurePath(file_path).name if file_path else ""
        file_name = file_name or file_path or "(无文件名)"
        if start_line <= 0:
            return file_name
        if end_line > start_line:
            return f"{file_name}:{start_line}-{end_line}"
        return f"{file_name}:{start_line}"

    @staticmethod
    def _expand_queries(
        queries: Sequence[str],
        *,
        profile: QueryProfile | None = None,
        alias_groups: Sequence[Sequence[str]] | None = None,
    ) -> tuple[str, ...]:
        normalized = tuple(query.strip() for query in queries if query and query.strip())
        if not normalized:
            return ()
        resolved_profile = profile or analyze_query_profile(None, normalized, alias_groups=alias_groups)
        return build_query_variants(resolved_profile, normalized, alias_groups=alias_groups)

    def _load_alias_groups(self) -> tuple[tuple[str, ...], ...]:
        if self._alias_groups_cache is not None:
            return self._alias_groups_cache

        sqlite_path = Path(self.config.data.sqlite)
        if not sqlite_path.exists():
            self._alias_groups_cache = build_alias_groups_from_front_matter(())
            return self._alias_groups_cache

        store = SQLiteMetadataStore(self.config.data.sqlite)
        try:
            document_metadatas = [dict(document.metadata) for document in store.iter_documents()]
        finally:
            store.close()
        self._alias_groups_cache = build_alias_groups_from_front_matter(document_metadatas)
        return self._alias_groups_cache

    def _search_and_rerank(
        self,
        queries: Sequence[str],
        *,
        recall_top_k: int | None,
        rerank_top_k: int | None,
        query_profile: QueryProfile,
        alias_groups: Sequence[Sequence[str]],
    ):
        search_and_rerank = self._retrieval.search_and_rerank
        kwargs: dict[str, object] = {
            "recall_top_k": recall_top_k,
            "rerank_top_k": rerank_top_k,
        }
        try:
            signature = inspect.signature(search_and_rerank)
        except (TypeError, ValueError):
            signature = None

        accepts_var_kwargs = False
        if signature is not None:
            accepts_var_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
            )
        if accepts_var_kwargs or (signature is not None and "query_profile" in signature.parameters):
            kwargs["query_profile"] = query_profile
        if accepts_var_kwargs or (signature is not None and "alias_groups" in signature.parameters):
            kwargs["alias_groups"] = alias_groups
        return search_and_rerank(queries, **kwargs)

    def _evaluate_query_term_coverage(self, queries: Sequence[str], chunks: Sequence[RetrievedChunk]) -> dict[str, object]:
        min_term_count = max(0, int(getattr(self.config.abstain, "min_query_term_count", 0) or 0))
        min_term_coverage = max(0.0, float(getattr(self.config.abstain, "min_query_term_coverage", 0.0) or 0.0))
        if min_term_count <= 0 or min_term_coverage <= 0.0:
            return {"passed": True}

        query_term_sets = self._build_query_term_sets(queries, min_term_count=min_term_count)
        evidence_profiles = self._build_evidence_term_profiles_by_document(chunks)
        best_total = 0
        best_matched = 0
        best_coverage = 0.0
        for terms in query_term_sets:
            for evidence_terms, _ in evidence_profiles:
                matched = sum(1 for term in terms if term in evidence_terms)
                coverage = matched / max(len(terms), 1)
                if coverage > best_coverage or (coverage == best_coverage and matched > best_matched):
                    best_total = len(terms)
                    best_matched = matched
                    best_coverage = coverage

        weighted_summary = self._build_weighted_query_terms(queries)
        weighted_matched = 0
        weighted_total = 0
        weighted_coverage = 0.0
        if weighted_summary:
            weighted_total = int(weighted_summary["total"])
            weighted_terms = weighted_summary["terms"]
            for evidence_terms, hit_count in evidence_profiles:
                if hit_count < 2:
                    continue
                matched = sum(weight for term, weight in weighted_terms.items() if term in evidence_terms)
                coverage = matched / max(weighted_total, 1)
                if coverage > weighted_coverage or (coverage == weighted_coverage and matched > weighted_matched):
                    weighted_matched = matched
                    weighted_coverage = coverage

        effective_matched = best_matched
        effective_total = best_total
        effective_coverage = best_coverage
        if weighted_coverage > effective_coverage or (
            weighted_coverage == effective_coverage and weighted_matched > effective_matched
        ):
            effective_matched = weighted_matched
            effective_total = weighted_total
            effective_coverage = weighted_coverage

        if effective_coverage >= min_term_coverage:
            return {
                "passed": True,
                "matched_terms": effective_matched,
                "total_terms": effective_total,
                "coverage": round(effective_coverage, 4),
            }

        decision = replace(
            evaluate_abstain(chunks, self.config.abstain),
            abstained=True,
            reason="query_term_coverage_below_threshold",
        )
        return {
            "passed": False,
            "matched_terms": effective_matched,
            "total_terms": effective_total,
            "coverage": round(effective_coverage, 4),
            "decision": decision,
        }

    @staticmethod
    def _build_query_term_sets(queries: Sequence[str], *, min_term_count: int) -> tuple[tuple[str, ...], ...]:
        term_sets: list[tuple[str, ...]] = []
        seen: set[tuple[str, ...]] = set()
        for query in queries:
            terms: list[str] = []
            term_seen: set[str] = set()
            for token in tokenize_fts(query).split():
                cleaned = token.strip()
                if (
                    not cleaned
                    or not _TOKEN_SIGNAL_RE.fullmatch(cleaned)
                    or cleaned in _QUERY_COVERAGE_LOW_SIGNAL_TOKENS
                    or cleaned in term_seen
                ):
                    continue
                term_seen.add(cleaned)
                terms.append(cleaned)
            if len(terms) < min_term_count:
                continue
            key = tuple(terms)
            if key in seen:
                continue
            seen.add(key)
            term_sets.append(key)
        return tuple(term_sets)

    @staticmethod
    def _build_weighted_query_terms(queries: Sequence[str]) -> dict[str, object] | None:
        weighted_terms: dict[str, int] = {}
        query_count = 0
        for query in queries:
            terms: list[str] = []
            seen: set[str] = set()
            for token in tokenize_fts(query).split():
                cleaned = token.strip()
                if (
                    not cleaned
                    or not _TOKEN_SIGNAL_RE.fullmatch(cleaned)
                    or cleaned in _QUERY_COVERAGE_LOW_SIGNAL_TOKENS
                    or cleaned in seen
                ):
                    continue
                seen.add(cleaned)
                terms.append(cleaned)
            if not terms:
                continue
            query_count += 1
            for term in terms:
                weighted_terms[term] = weighted_terms.get(term, 0) + 1

        if query_count < 2 or len(weighted_terms) < 2:
            return None
        return {
            "terms": weighted_terms,
            "total": sum(weighted_terms.values()),
        }

    def _relax_query_profile_guardrail(
        self,
        profile: QueryProfile,
        queries: Sequence[str],
        chunks: Sequence[RetrievedChunk],
        decision,
    ):
        if not decision.abstained:
            return decision
        if profile.query_type != "existence":
            return decision
        if not chunks:
            return decision
        if decision.reason not in {
            "top1_score_below_threshold",
            "recall_hits_below_threshold",
            "evidence_chars_below_threshold",
        }:
            return decision
        if not self._has_strong_existence_evidence(queries, chunks):
            return decision

        return replace(
            decision,
            abstained=False,
            reason=None,
            confidence=max(float(getattr(decision, "confidence", 0.0) or 0.0), 0.35),
        )

    def _evaluate_query_profile_guardrail(
        self,
        profile: QueryProfile,
        queries: Sequence[str],
        chunks: Sequence[RetrievedChunk],
    ):
        if profile.query_type != "comparison" or len(profile.comparison_terms) < 2:
            return None

        evidence_profiles = self._build_evidence_term_profiles_by_document(chunks)
        covered_by_doc = [
            {term for term in profile.comparison_terms if term in evidence_terms}
            for evidence_terms, _ in evidence_profiles
        ]
        has_single_doc_full_coverage = any(len(covered) >= 2 for covered in covered_by_doc)
        total_covered_terms = set().union(*covered_by_doc) if covered_by_doc else set()
        docs_with_coverage = sum(1 for covered in covered_by_doc if covered)
        if has_single_doc_full_coverage or (len(total_covered_terms) >= 2 and docs_with_coverage >= 2):
            return None

        return replace(
            evaluate_abstain(chunks, self.config.abstain),
            abstained=True,
            reason="comparison_evidence_incomplete",
        )

    def _has_strong_existence_evidence(self, queries: Sequence[str], chunks: Sequence[RetrievedChunk]) -> bool:
        min_term_count = max(2, int(getattr(self.config.abstain, "min_query_term_count", 0) or 0))
        term_sets = self._build_query_term_sets(queries, min_term_count=min_term_count)
        if not term_sets:
            return False

        profiles = self._build_evidence_document_profiles(chunks)
        if not profiles:
            return False

        top_document_key = chunks[0].file_path or chunks[0].document_id or chunks[0].chunk_id
        min_coverage = max(0.6, float(getattr(self.config.abstain, "min_query_term_coverage", 0.0) or 0.0))
        for terms in term_sets:
            if not terms:
                continue
            for profile in profiles:
                matched = sum(1 for term in terms if term in profile.terms)
                coverage = matched / max(len(terms), 1)
                if matched < 1 or coverage < min_coverage:
                    continue
                if profile.document_key != top_document_key and coverage < 1.0:
                    continue
                return True
        return False

    @staticmethod
    def _build_evidence_term_set(chunks: Sequence[RetrievedChunk]) -> set[str]:
        evidence_profiles = QueryService._build_evidence_term_profiles_by_document(chunks)
        evidence_terms: set[str] = set()
        for terms, _ in evidence_profiles:
            evidence_terms.update(terms)
        return evidence_terms

    @staticmethod
    def _build_evidence_document_profiles(chunks: Sequence[RetrievedChunk]) -> tuple[_EvidenceDocumentProfile, ...]:
        grouped_parts: OrderedDict[str, list[str]] = OrderedDict()
        grouped_counts: OrderedDict[str, int] = OrderedDict()
        for chunk in chunks:
            document_key = chunk.file_path or chunk.document_id or chunk.chunk_id
            grouped_parts.setdefault(document_key, [])
            grouped_counts[document_key] = grouped_counts.get(document_key, 0) + 1
            parts = grouped_parts[document_key]
            parts.append(chunk.content)
            if chunk.title_path:
                parts.extend(chunk.title_path)
            if chunk.file_path:
                parts.append(PurePath(chunk.file_path).stem)
            metadata = chunk.metadata if isinstance(chunk.metadata, dict) else {}
            for key in ("relative_path", "front_matter_origin_path"):
                value = metadata.get(key)
                if value is None:
                    continue
                _append_path_terms(parts, str(value))
            for key in ("front_matter_title", "front_matter_category"):
                value = metadata.get(key)
                if value is None:
                    continue
                cleaned = str(value).strip()
                if cleaned:
                    parts.append(cleaned)
            for key in ("front_matter_aliases", "front_matter_tags", "path_segments"):
                raw = metadata.get(key)
                if isinstance(raw, str):
                    if key == "path_segments":
                        _append_path_terms(parts, raw)
                    else:
                        cleaned = raw.strip()
                        if cleaned:
                            parts.append(cleaned)
                    continue
                if not isinstance(raw, Sequence):
                    continue
                for item in raw:
                    cleaned = str(item).strip()
                    if not cleaned:
                        continue
                    if key == "path_segments":
                        _append_path_terms(parts, cleaned)
                    else:
                        parts.append(cleaned)

        evidence_profiles: list[_EvidenceDocumentProfile] = []
        for document_key, parts in grouped_parts.items():
            evidence_terms: set[str] = set()
            for token in tokenize_fts(" ".join(part for part in parts if part)).split():
                cleaned = token.strip()
                if cleaned:
                    evidence_terms.add(cleaned)
            if evidence_terms:
                evidence_profiles.append(
                    _EvidenceDocumentProfile(
                        document_key=document_key,
                        terms=evidence_terms,
                        hit_count=grouped_counts.get(document_key, 0),
                    )
                )
        return tuple(evidence_profiles)

    @staticmethod
    def _build_evidence_term_profiles_by_document(chunks: Sequence[RetrievedChunk]) -> tuple[tuple[set[str], int], ...]:
        profiles = QueryService._build_evidence_document_profiles(chunks)
        if not profiles:
            return ((set(), 0),)
        return tuple((profile.terms, profile.hit_count) for profile in profiles)
