from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

from app.config import AppConfig
from app.observability import get_logger, timed_operation
from app.store import SQLiteMetadataStore

from .contracts import RetrievedChunk, RetrievalError, SearchDebug, SearchResultSet
from .lexical import LexicalRetriever
from .rerank import RerankerProtocol, build_reranker
from .semantic import EmbeddingEncoder, SemanticRetriever, build_embedding_encoder

LOGGER = get_logger("kms.retrieval")


@dataclass(slots=True)
class _FusedCandidate:
    chunk: RetrievedChunk
    rrf_score: float = 0.0


def _normalize_queries(queries: Sequence[str] | str) -> tuple[str, ...]:
    if isinstance(queries, str):
        queries = (queries,)
    return tuple(query.strip() for query in queries if query and query.strip())


def _unique_queries(queries: Sequence[str]) -> tuple[str, ...]:
    unique_queries: list[str] = []
    seen: set[str] = set()
    for query in queries:
        if query in seen:
            continue
        seen.add(query)
        unique_queries.append(query)
    return tuple(unique_queries)


def _add_rrf_score(bucket: dict[str, _FusedCandidate], hit: RetrievedChunk, *, rank: int, rrf_k: int, source: str) -> None:
    chunk_id = hit.chunk_id or hit.document_id
    candidate = bucket.get(chunk_id)
    if candidate is None:
        candidate = _FusedCandidate(chunk=hit)
        bucket[chunk_id] = candidate

    candidate.rrf_score += 1.0 / float(rrf_k + rank)

    metadata = dict(candidate.chunk.metadata)
    metadata.setdefault("source_hits", [])
    source_hits = list(metadata["source_hits"]) if isinstance(metadata["source_hits"], list) else []
    source_hits.append(source)
    metadata["source_hits"] = source_hits
    metadata["rrf_score"] = candidate.rrf_score
    if source.startswith("lexical"):
        metadata["lexical_score"] = float(hit.metadata.get("lexical_score", hit.score or 0.0) or 0.0)
    if source.startswith("semantic"):
        metadata["semantic_score"] = float(hit.metadata.get("semantic_score", hit.score or 0.0) or 0.0)
    candidate.chunk = replace(candidate.chunk, metadata=metadata)


def reciprocal_rank_fusion(
    candidate_lists: Sequence[tuple[str, Sequence[RetrievedChunk]]],
    *,
    rrf_k: int = 60,
) -> tuple[RetrievedChunk, ...]:
    bucket: dict[str, _FusedCandidate] = {}
    for source, hits in candidate_lists:
        for rank, hit in enumerate(hits, start=1):
            _add_rrf_score(bucket, hit, rank=rank, rrf_k=rrf_k, source=source)

    ranked = sorted(
        bucket.values(),
        key=lambda item: (
            -item.rrf_score,
            -(float(item.chunk.score or 0.0)),
            item.chunk.chunk_id or item.chunk.document_id,
        ),
    )
    results: list[RetrievedChunk] = []
    for fused in ranked:
        metadata = dict(fused.chunk.metadata)
        metadata["rrf_score"] = fused.rrf_score
        results.append(replace(fused.chunk, score=fused.rrf_score, metadata=metadata))
    return tuple(results)


def _build_lexical_retriever(metadata_store: SQLiteMetadataStore) -> LexicalRetriever:
    return LexicalRetriever(metadata_store.connection)


def _build_semantic_retriever(config: AppConfig, *, embedder: EmbeddingEncoder | None = None) -> SemanticRetriever:
    return SemanticRetriever(
        config.data.chroma,
        embedder=embedder
        or build_embedding_encoder(
            config.models.embedding,
            device=config.models.device,
            dtype=config.models.dtype,
            batch_size=config.models.embedding_batch_size,
            hf_cache=config.data.hf_cache,
        ),
    )


def _build_reranker(config: AppConfig, reranker: RerankerProtocol | None = None) -> RerankerProtocol:
    return reranker or build_reranker(
        config.models.reranker,
        device=config.models.device,
        dtype=config.models.dtype,
        batch_size=config.models.reranker_batch_size,
        hf_cache=config.data.hf_cache,
    )


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
            metadata = dict(chunk.metadata or {})
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


@dataclass(slots=True)
class HybridRetrievalService:
    """End-to-end hybrid retrieval pipeline used by `/search`."""

    config: AppConfig
    embedder: EmbeddingEncoder | None = None
    reranker: RerankerProtocol | None = None
    lexical_retriever: LexicalRetriever | None = None
    semantic_retriever: SemanticRetriever | None = None
    rrf_k: int | None = None

    @classmethod
    def from_config(cls, config: AppConfig) -> HybridRetrievalService:
        embedder = build_embedding_encoder(
            config.models.embedding,
            device=config.models.device,
            dtype=config.models.dtype,
            batch_size=config.models.embedding_batch_size,
            hf_cache=config.data.hf_cache,
        )
        semantic_retriever = SemanticRetriever(
            config.data.chroma,
            embedder=embedder,
        )
        reranker = build_reranker(
            config.models.reranker,
            device=config.models.device,
            dtype=config.models.dtype,
            batch_size=config.models.reranker_batch_size,
            hf_cache=config.data.hf_cache,
        )
        return cls(
            config=config,
            embedder=embedder,
            semantic_retriever=semantic_retriever,
            reranker=reranker,
        )

    def search(
        self,
        queries: Sequence[str] | str,
        recall_top_k: int | None = None,
        rerank_top_k: int | None = None,
    ) -> SearchResultSet:
        cleaned_queries = _normalize_queries(queries)
        if not cleaned_queries:
            raise RetrievalError("at least one non-empty query is required")

        recall_top_k = self.config.retrieval.recall_top_k if recall_top_k is None else int(recall_top_k)
        rrf_k = self.config.retrieval.rrf_k if self.rrf_k is None else int(self.rrf_k)

        with timed_operation(
            LOGGER,
            "retrieval.search",
            query_count=len(cleaned_queries),
            recall_top_k=recall_top_k,
            rrf_k=rrf_k,
        ) as span:
            with SQLiteMetadataStore(self.config.data.sqlite) as metadata_store:
                lexical = self.lexical_retriever or _build_lexical_retriever(metadata_store)
                semantic = self.semantic_retriever or _build_semantic_retriever(self.config, embedder=self.embedder)

                candidate_lists: list[tuple[str, Sequence[RetrievedChunk]]] = []
                for query in cleaned_queries:
                    with timed_operation(LOGGER, "retrieval.lexical_stage", query=query, limit=recall_top_k) as lexical_span:
                        lexical_hits = lexical.search(query, limit=recall_top_k)
                        lexical_span.set(hit_count=len(lexical_hits))
                    candidate_lists.append((f"lexical:{query}", lexical_hits))

                if len(cleaned_queries) > 1 and callable(getattr(semantic, "search_many", None)):
                    with timed_operation(
                        LOGGER,
                        "retrieval.semantic_stage",
                        query_count=len(cleaned_queries),
                        limit=recall_top_k,
                        batched=True,
                    ) as semantic_span:
                        semantic_batches = tuple(semantic.search_many(cleaned_queries, limit=recall_top_k))
                        semantic_span.set(
                            hit_count=sum(len(hits) for hits in semantic_batches),
                            per_query_hit_counts=[len(hits) for hits in semantic_batches],
                        )
                    for query, semantic_hits in zip(cleaned_queries, semantic_batches, strict=True):
                        candidate_lists.append((f"semantic:{query}", semantic_hits))
                else:
                    for query in cleaned_queries:
                        with timed_operation(LOGGER, "retrieval.semantic_stage", query=query, limit=recall_top_k) as semantic_span:
                            semantic_hits = semantic.search(query, limit=recall_top_k)
                            semantic_span.set(hit_count=len(semantic_hits))
                        candidate_lists.append((f"semantic:{query}", semantic_hits))

                fused = reciprocal_rank_fusion(candidate_lists, rrf_k=rrf_k)
                span.set(candidate_list_count=len(candidate_lists), fused_count=len(fused))
                debug = SearchDebug(
                    queries_count=len(cleaned_queries),
                    recall_count=len(fused),
                    rerank_count=0,
                )
                return SearchResultSet(results=fused, debug=debug)

    def search_and_rerank(
        self,
        queries: Sequence[str] | str,
        recall_top_k: int | None = None,
        rerank_top_k: int | None = None,
    ) -> SearchResultSet:
        cleaned_queries = _normalize_queries(queries)
        if not cleaned_queries:
            raise RetrievalError("at least one non-empty query is required")

        with timed_operation(
            LOGGER,
            "retrieval.search_and_rerank",
            query_count=len(cleaned_queries),
            recall_top_k=recall_top_k,
            rerank_top_k=rerank_top_k,
        ) as span:
            rerank_top_k = self.config.retrieval.rerank_top_k if rerank_top_k is None else int(rerank_top_k)
            fused = self.search(cleaned_queries, recall_top_k=recall_top_k)
            candidates = _limit_rerank_candidates(
                fused.results,
                candidate_limit=self.config.retrieval.rerank_candidate_limit,
            )
            reranker = _build_reranker(self.config, self.reranker)
            reranked = _rerank_candidates(
                reranker,
                cleaned_queries,
                candidates,
                top_k=rerank_top_k,
            )
            filtered = _filter_low_score_results(
                reranked,
                min_output_score=self.config.retrieval.min_output_score,
            )
            span.set(recall_count=len(fused.results), candidate_count=len(candidates), rerank_count=len(filtered))
            debug = SearchDebug(
                queries_count=fused.debug.queries_count,
                recall_count=fused.debug.recall_count,
                rerank_count=len(filtered),
            )
            return SearchResultSet(results=filtered, debug=debug)

    def retrieve(self, query: str, limit: int = 5) -> Sequence[RetrievedChunk]:
        return self.search_and_rerank(query, recall_top_k=limit, rerank_top_k=limit).results

    def close(self) -> None:
        with timed_operation(LOGGER, "retrieval.close"):
            resources = (
                self.reranker,
                self.semantic_retriever,
                self.lexical_retriever,
                self.embedder,
            )
            seen: set[int] = set()
            for resource in resources:
                if resource is None:
                    continue
                marker = id(resource)
                if marker in seen:
                    continue
                seen.add(marker)
                close = getattr(resource, "close", None)
                if callable(close):
                    close()

            self.reranker = None
            self.semantic_retriever = None
            self.lexical_retriever = None
            self.embedder = None
