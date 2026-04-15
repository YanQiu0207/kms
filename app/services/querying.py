"""M2/M3 查询服务。"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import PurePath
import re
from typing import Sequence

from app.answer import build_evidence_sources, build_prompt_package, evaluate_abstain, verify_citations
from app.config import AppConfig
from app.observability import get_logger, timed_operation
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


class QueryService:
    """封装 `/search`、`/ask`、`/verify` 所需的查询流程。"""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._retrieval = HybridRetrievalService.from_config(config)
        self._search_cache: OrderedDict[tuple[tuple[str, ...], int | None, int | None], object] = OrderedDict()
        self._search_cache_limit = 64

    def search(
        self,
        queries: Sequence[str],
        *,
        recall_top_k: int | None = None,
        rerank_top_k: int | None = None,
    ):
        with timed_operation(
            LOGGER,
            "query.search",
            input_query_count=len(tuple(queries)),
            recall_top_k=recall_top_k,
            rerank_top_k=rerank_top_k,
        ) as span:
            normalized_queries = self._expand_queries(queries)
            span.set(expanded_query_count=len(normalized_queries))
            cache_key = (normalized_queries, recall_top_k, rerank_top_k)
            cached = self._search_cache.get(cache_key)
            if cached is not None:
                self._search_cache.move_to_end(cache_key)
                span.set(cache_hit=True, result_count=len(cached.results))
                return cached

            result = self._retrieval.search_and_rerank(
                normalized_queries,
                recall_top_k=recall_top_k,
                rerank_top_k=rerank_top_k,
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
            effective_queries = self._expand_queries(tuple(query.strip() for query in queries if query.strip()) or (question.strip(),))
            span.set(expanded_query_count=len(effective_queries))
            result_set = self.search(
                effective_queries,
                recall_top_k=recall_top_k,
                rerank_top_k=rerank_top_k,
            )
            decision = self._evaluate_ask_decision(
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
                package = build_prompt_package(
                    question,
                    result_set.results,
                    thresholds=self.config.abstain,
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

    def _load_chunk_texts(self, chunk_ids: Sequence[str]) -> dict[str, str]:
        if not chunk_ids:
            return {}

        chunk_texts: dict[str, str] = {}
        store = SQLiteMetadataStore(self.config.data.sqlite)
        try:
            for chunk_id in chunk_ids:
                chunk = store.get_chunk(chunk_id)
                if chunk is None:
                    continue
                chunk_texts[chunk_id] = chunk.content
        finally:
            store.close()
        return chunk_texts

    def _evaluate_ask_decision(self, effective_queries: Sequence[str], results: Sequence[RetrievedChunk], *, event_name: str):
        with timed_operation(LOGGER, event_name, result_count=len(results)):
            decision = evaluate_abstain(results, self.config.abstain)
        if not decision.abstained:
            coverage_decision = self._evaluate_query_term_coverage(effective_queries, results)
            if not coverage_decision["passed"]:
                decision = coverage_decision["decision"]
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
    def _expand_queries(queries: Sequence[str]) -> tuple[str, ...]:
        normalized = tuple(query.strip() for query in queries if query and query.strip())
        if not normalized:
            return ()
        if len(normalized) > 1:
            return normalized

        base = normalized[0]
        variants: list[str] = [base]

        compact = " ".join(part for part in _PUNCT_RE.split(base) if part)
        if compact and compact not in variants:
            variants.append(compact)

        keyword_tokens: list[str] = []
        seen: set[str] = set()
        for token in tokenize_fts(base).split():
            cleaned = token.strip()
            if (
                not cleaned
                or not _TOKEN_SIGNAL_RE.fullmatch(cleaned)
                or cleaned in _LOW_SIGNAL_QUERY_TOKENS
                or cleaned in seen
            ):
                continue
            seen.add(cleaned)
            keyword_tokens.append(cleaned)

        keyword_query = " ".join(keyword_tokens)
        if keyword_query and keyword_query not in variants:
            variants.append(keyword_query)

        return tuple(variants[:3])

    def _evaluate_query_term_coverage(self, queries: Sequence[str], chunks: Sequence[RetrievedChunk]) -> dict[str, object]:
        min_term_count = max(0, int(getattr(self.config.abstain, "min_query_term_count", 0) or 0))
        min_term_coverage = max(0.0, float(getattr(self.config.abstain, "min_query_term_coverage", 0.0) or 0.0))
        if min_term_count <= 0 or min_term_coverage <= 0.0:
            return {"passed": True}

        query_term_sets = self._build_query_term_sets(queries, min_term_count=min_term_count)
        if not query_term_sets:
            return {"passed": True}

        evidence_terms = self._build_evidence_term_set(chunks)
        best_total = 0
        best_matched = 0
        best_coverage = 0.0
        for terms in query_term_sets:
            matched = sum(1 for term in terms if term in evidence_terms)
            coverage = matched / max(len(terms), 1)
            if coverage > best_coverage or (coverage == best_coverage and matched > best_matched):
                best_total = len(terms)
                best_matched = matched
                best_coverage = coverage

        if best_coverage >= min_term_coverage:
            return {
                "passed": True,
                "matched_terms": best_matched,
                "total_terms": best_total,
                "coverage": round(best_coverage, 4),
            }

        decision = replace(
            evaluate_abstain(chunks, self.config.abstain),
            abstained=True,
            reason="query_term_coverage_below_threshold",
        )
        return {
            "passed": False,
            "matched_terms": best_matched,
            "total_terms": best_total,
            "coverage": round(best_coverage, 4),
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
    def _build_evidence_term_set(chunks: Sequence[RetrievedChunk]) -> set[str]:
        evidence_terms: set[str] = set()
        for chunk in chunks:
            parts = [chunk.content]
            if chunk.title_path:
                parts.extend(chunk.title_path)
            if chunk.file_path:
                parts.append(PurePath(chunk.file_path).stem)
            for token in tokenize_fts(" ".join(part for part in parts if part)).split():
                cleaned = token.strip()
                if cleaned:
                    evidence_terms.add(cleaned)
        return evidence_terms
