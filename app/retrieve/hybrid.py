from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from app.config import AppConfig
from app.observability import get_logger, timed_operation
from app.query_understanding import QueryProfile
from app.store import SQLiteMetadataStore

from .contracts import RetrievedChunk, RetrievalError, SearchDebug, SearchResultSet
from .lexical import LexicalRetriever
from .ranking_pipeline import RankingPipelineContext, run_ranking_pipeline
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


def _source_type(source: str) -> str:
    return source.split(":", 1)[0].strip().casefold()


def _fusion_weights_for_query_type(config: AppConfig, query_type: str | None) -> dict[str, float]:
    weights = dict(config.retrieval.query_type_fusion_weights.get((query_type or "").strip(), {}))
    return {
        "lexical": float(weights.get("lexical", 1.0) or 1.0),
        "semantic": float(weights.get("semantic", 1.0) or 1.0),
    }


def _add_rrf_score(
    bucket: dict[str, _FusedCandidate],
    hit: RetrievedChunk,
    *,
    rank: int,
    rrf_k: int,
    source: str,
    source_weights: dict[str, float],
) -> None:
    chunk_id = hit.chunk_id or hit.document_id
    candidate = bucket.get(chunk_id)
    if candidate is None:
        candidate = _FusedCandidate(chunk=hit)
        bucket[chunk_id] = candidate

    source_type = _source_type(source)
    source_weight = float(source_weights.get(source_type, 1.0) or 1.0)
    candidate.rrf_score += source_weight * (1.0 / float(rrf_k + rank))

    metadata = dict(candidate.chunk.metadata)
    metadata.setdefault("source_hits", [])
    source_hits = list(metadata["source_hits"]) if isinstance(metadata["source_hits"], list) else []
    source_hits.append(source)
    metadata["source_hits"] = source_hits
    metadata["rrf_score"] = candidate.rrf_score
    metadata.setdefault("fusion_weights", {})
    fusion_weights = dict(metadata["fusion_weights"]) if isinstance(metadata["fusion_weights"], dict) else {}
    fusion_weights[source_type] = source_weight
    metadata["fusion_weights"] = fusion_weights
    if source.startswith("lexical"):
        metadata["lexical_score"] = float(hit.metadata.get("lexical_score", hit.score or 0.0) or 0.0)
    if source.startswith("semantic"):
        metadata["semantic_score"] = float(hit.metadata.get("semantic_score", hit.score or 0.0) or 0.0)
    candidate.chunk = replace(candidate.chunk, metadata=metadata)


def reciprocal_rank_fusion(
    candidate_lists: Sequence[tuple[str, Sequence[RetrievedChunk]]],
    *,
    rrf_k: int = 60,
    source_weights: dict[str, float] | None = None,
) -> tuple[RetrievedChunk, ...]:
    bucket: dict[str, _FusedCandidate] = {}
    source_weights = dict(source_weights or {})
    for source, hits in candidate_lists:
        for rank, hit in enumerate(hits, start=1):
            _add_rrf_score(bucket, hit, rank=rank, rrf_k=rrf_k, source=source, source_weights=source_weights)

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
        query_type: str | None = None,
    ) -> SearchResultSet:
        cleaned_queries = _normalize_queries(queries)
        if not cleaned_queries:
            raise RetrievalError("at least one non-empty query is required")

        recall_top_k = self.config.retrieval.recall_top_k if recall_top_k is None else int(recall_top_k)
        rrf_k = self.config.retrieval.rrf_k if self.rrf_k is None else int(self.rrf_k)

        fusion_weights = _fusion_weights_for_query_type(self.config, query_type)

        with timed_operation(
            LOGGER,
            "retrieval.search",
            query_count=len(cleaned_queries),
            recall_top_k=recall_top_k,
            rrf_k=rrf_k,
            query_type=query_type,
            fusion_weights=fusion_weights,
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

                if self.config.retrieval.semantic_enabled and (
                    self.config.retrieval.semantic_batch_enabled
                    and len(cleaned_queries) > 1
                    and callable(getattr(semantic, "search_many", None))
                ):
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
                elif self.config.retrieval.semantic_enabled:
                    for query in cleaned_queries:
                        with timed_operation(LOGGER, "retrieval.semantic_stage", query=query, limit=recall_top_k) as semantic_span:
                            semantic_hits = semantic.search(query, limit=recall_top_k)
                            semantic_span.set(hit_count=len(semantic_hits))
                        candidate_lists.append((f"semantic:{query}", semantic_hits))

                fused = reciprocal_rank_fusion(candidate_lists, rrf_k=rrf_k, source_weights=fusion_weights)
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
        query_profile: QueryProfile | None = None,
        alias_groups: Sequence[Sequence[str]] | None = None,
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
            fused = self.search(
                cleaned_queries,
                recall_top_k=recall_top_k,
                query_type=query_profile.query_type if query_profile is not None else None,
            )
            reranker = _build_reranker(self.config, self.reranker)
            ranking_context = RankingPipelineContext(
                config=self.config,
                queries=tuple(cleaned_queries),
                reranker=reranker,
                rerank_top_k=rerank_top_k,
                query_profile=query_profile,
                alias_groups=tuple(tuple(group) for group in (alias_groups or ())),
            )
            ranked = run_ranking_pipeline(
                fused.results,
                context=ranking_context,
                steps=self.config.retrieval.ranking_pipeline,
            )
            span.set(
                recall_count=len(fused.results),
                candidate_count=ranking_context.counts.get("candidate_count", len(fused.results)),
                constrained_candidate_count=ranking_context.counts.get("constrained_candidate_count", len(ranked)),
                rerank_count=len(ranked),
            )
            debug = SearchDebug(
                queries_count=fused.debug.queries_count,
                recall_count=fused.debug.recall_count,
                rerank_count=len(ranked),
            )
            return SearchResultSet(results=ranked, debug=debug)

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
