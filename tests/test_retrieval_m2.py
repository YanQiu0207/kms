from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from app.config import AppConfig, RetrievalConfig
from app.retrieve import HybridRetrievalService, RetrievedChunk
from app.retrieve.lexical import _build_fts_query, LexicalRetriever
from app.retrieve.semantic import SemanticRetriever
from app.retrieve.rerank import FlagEmbeddingReranker
from app.services.embeddings import EmbeddingService


class _StaticRetriever:
    def __init__(self, results):
        self.results = tuple(results)

    def search(self, query: str, limit: int = 5):
        return self.results[:limit]


@dataclass
class _RecordingReranker:
    queries: list[str] | None = None
    last_candidate_count: int = 0

    def __post_init__(self):
        if self.queries is None:
            self.queries = []

    def rerank(self, query, candidates, top_k=None):
        self.queries.append(query)
        self.last_candidate_count = len(candidates)
        ranked = tuple(candidates)
        if top_k is None:
            return ranked
        return ranked[:top_k]


class _StaticReranker:
    def __init__(self, results):
        self.results = tuple(results)

    def rerank(self, query, candidates, top_k=None):
        ranked = self.results
        if top_k is None:
            return ranked
        return ranked[:top_k]

    def close(self):
        return None


class _PerQueryReranker:
    def rerank(self, query, candidates, top_k=None):
        ranked: list[RetrievedChunk] = []
        for candidate in candidates:
            score = 0.1
            if query == "q1" and candidate.chunk_id == "c1":
                score = 0.9
            elif query == "q2" and candidate.chunk_id == "c2":
                score = 0.95
            ranked.append(
                RetrievedChunk(
                    document_id=candidate.document_id,
                    chunk_id=candidate.chunk_id,
                    content=candidate.content,
                    score=score,
                    metadata={
                        **candidate.metadata,
                        "rerank_raw_score": score,
                        "rerank_score": score,
                    },
                )
            )
        ranked.sort(key=lambda item: (-float(item.score or 0.0), item.chunk_id or item.document_id))
        if top_k is None:
            return tuple(ranked)
        return tuple(ranked[:top_k])

    def close(self):
        return None


@dataclass
class _RecordingEmbedder:
    calls: list[list[str]] | None = None

    def __post_init__(self):
        if self.calls is None:
            self.calls = []

    def embed_texts(self, texts):
        self.calls.append(list(texts))
        return [[float(index + 1)] for index, _ in enumerate(texts)]

    def close(self):
        return None


class _FakeSemanticCollection:
    def query(self, *, query_embeddings, n_results, include):
        assert len(query_embeddings) == 2
        assert n_results == 2
        assert include == ["documents", "metadatas", "distances"]
        return {
            "ids": [["c1", "c2"], ["c3"]],
            "documents": [["alpha", "beta"], ["gamma"]],
            "metadatas": [
                [{"document_id": "doc-1"}, {"document_id": "doc-2"}],
                [{"document_id": "doc-3"}],
            ],
            "distances": [[0.1, 0.2], [0.3]],
        }


@dataclass
class _BatchOnlySemanticRetriever:
    calls: list[tuple[tuple[str, ...], int]] | None = None

    def __post_init__(self):
        if self.calls is None:
            self.calls = []

    def search_many(self, queries, limit=5):
        self.calls.append((tuple(queries), limit))
        return (
            (
                RetrievedChunk(document_id="doc-s1", chunk_id="s1", content="semantic-q1", score=0.9),
            ),
            (
                RetrievedChunk(document_id="doc-s2", chunk_id="s2", content="semantic-q2", score=0.8),
            ),
        )

    def search(self, query, limit=5):
        raise AssertionError("search() should not be used when search_many() is available")

    def close(self):
        return None


@dataclass
class _ClosableResource:
    closed: int = 0

    def close(self):
        self.closed += 1


def test_search_and_rerank_reranks_each_query_individually():
    lexical = _StaticRetriever(
        [
            RetrievedChunk(
                document_id="doc-1",
                chunk_id="c1",
                content="alpha",
                score=0.8,
            )
        ]
    )
    semantic = _StaticRetriever(
        [
            RetrievedChunk(
                document_id="doc-1",
                chunk_id="c1",
                content="alpha",
                score=0.7,
            )
        ]
    )
    reranker = _RecordingReranker()
    service = HybridRetrievalService(
        config=AppConfig(retrieval=RetrievalConfig(recall_top_k=5, rerank_top_k=3, rrf_k=60)),
        lexical_retriever=lexical,
        semantic_retriever=semantic,
        reranker=reranker,
    )

    service.search_and_rerank(["q1", "q2"], recall_top_k=5, rerank_top_k=3)

    assert reranker.queries == ["q1", "q2"]


def test_search_and_rerank_merges_multi_query_scores_by_best_match():
    candidates = [
        RetrievedChunk(document_id="doc-1", chunk_id="c1", content="alpha", score=0.8),
        RetrievedChunk(document_id="doc-2", chunk_id="c2", content="beta", score=0.7),
    ]
    lexical = _StaticRetriever(candidates)
    semantic = _StaticRetriever(candidates)
    reranker = _PerQueryReranker()
    service = HybridRetrievalService(
        config=AppConfig(retrieval=RetrievalConfig(recall_top_k=5, rerank_top_k=2, rrf_k=60, min_output_score=0.0)),
        lexical_retriever=lexical,
        semantic_retriever=semantic,
        reranker=reranker,
    )

    result = service.search_and_rerank(["q1", "q2"], recall_top_k=5, rerank_top_k=2)

    assert [chunk.chunk_id for chunk in result.results] == ["c2", "c1"]
    assert result.results[0].metadata["rerank_query"] == "q2"
    assert result.results[1].metadata["rerank_query"] == "q1"


def test_semantic_search_many_batches_embedding_once():
    embedder = _RecordingEmbedder()
    retriever = SemanticRetriever(
        persist_directory=None,
        embedder=embedder,
        collection=_FakeSemanticCollection(),
        initialize=False,
    )

    result = retriever.search_many(["q1", "q2"], limit=2)

    assert embedder.calls == [["q1", "q2"]]
    assert [[chunk.chunk_id for chunk in per_query] for per_query in result] == [["c1", "c2"], ["c3"]]
    assert result[0][0].metadata["semantic_rank"] == 1
    assert result[1][0].metadata["semantic_rank"] == 1


def test_search_uses_semantic_batch_path_for_multi_query():
    lexical = _StaticRetriever(())
    semantic = _BatchOnlySemanticRetriever()
    service = HybridRetrievalService(
        config=AppConfig(retrieval=RetrievalConfig(recall_top_k=5, rerank_top_k=3, rrf_k=60)),
        lexical_retriever=lexical,
        semantic_retriever=semantic,
    )

    result = service.search(["q1", "q2"], recall_top_k=5)

    assert semantic.calls == [(("q1", "q2"), 5)]
    assert [chunk.chunk_id for chunk in result.results] == ["s1", "s2"]


def test_search_and_rerank_caps_candidates_before_rerank():
    candidates = [
        RetrievedChunk(
            document_id=f"doc-{index}",
            chunk_id=f"c{index}",
            content=f"content-{index}",
            score=1.0 - (index * 0.01),
        )
        for index in range(8)
    ]
    lexical = _StaticRetriever(candidates)
    semantic = _StaticRetriever(candidates)
    reranker = _RecordingReranker()
    service = HybridRetrievalService(
        config=AppConfig(retrieval=RetrievalConfig(recall_top_k=8, rerank_top_k=3, rerank_candidate_limit=4, rrf_k=60)),
        lexical_retriever=lexical,
        semantic_retriever=semantic,
        reranker=reranker,
    )

    service.search_and_rerank(["q1"], recall_top_k=8, rerank_top_k=3)

    assert reranker.last_candidate_count == 4


def test_flag_reranker_normalizes_raw_scores():
    candidate = RetrievedChunk(
        document_id="doc-1",
        chunk_id="c1",
        content="alpha",
        score=0.1,
    )
    reranker = FlagEmbeddingReranker("mock-reranker")
    reranker._model = SimpleNamespace(compute_score=lambda pairs: [-3.0])

    ranked = reranker.rerank("query", [candidate], top_k=1)

    assert len(ranked) == 1
    assert 0.0 < ranked[0].score < 1.0
    assert ranked[0].metadata["rerank_raw_score"] == -3.0


def test_flag_reranker_uses_configured_batch_size_when_supported():
    candidate = RetrievedChunk(
        document_id="doc-1",
        chunk_id="c1",
        content="alpha",
        score=0.1,
    )
    recorded: list[int] = []

    def _compute_score(pairs, batch_size=None):
        recorded.append(batch_size)
        return [0.5]

    reranker = FlagEmbeddingReranker("mock-reranker", batch_size=7)
    reranker._model = SimpleNamespace(compute_score=_compute_score)

    ranked = reranker.rerank("query", [candidate], top_k=1)

    assert len(ranked) == 1
    assert recorded == [7]


def test_search_and_rerank_filters_low_score_results():
    low = RetrievedChunk(document_id="doc-low", chunk_id="c-low", content="low", score=0.05)
    high = RetrievedChunk(document_id="doc-high", chunk_id="c-high", content="high", score=0.25)
    lexical = _StaticRetriever([low, high])
    semantic = _StaticRetriever([low, high])
    reranker = _StaticReranker([low, high])
    service = HybridRetrievalService(
        config=AppConfig(retrieval=RetrievalConfig(recall_top_k=5, rerank_top_k=3, rrf_k=60, min_output_score=0.1)),
        lexical_retriever=lexical,
        semantic_retriever=semantic,
        reranker=reranker,
    )

    result = service.search_and_rerank(["q1"], recall_top_k=5, rerank_top_k=3)

    assert [chunk.chunk_id for chunk in result.results] == ["c-high"]
    assert result.debug.rerank_count == 1


def test_flag_reranker_close_releases_cached_model():
    calls: list[str] = []
    reranker = FlagEmbeddingReranker("mock-reranker")
    reranker._model = SimpleNamespace(close=lambda: calls.append("closed"))

    reranker.close()

    assert reranker._model is None
    assert calls == ["closed"]


def test_embedding_service_close_releases_cached_model():
    calls: list[str] = []
    embedder = EmbeddingService("mock-embedding")
    embedder._model = SimpleNamespace(close=lambda: calls.append("closed"))

    embedder.close()

    assert embedder._model is None
    assert calls == ["closed"]


def test_hybrid_retrieval_close_closes_all_components_once():
    embedder = _ClosableResource()
    reranker = _ClosableResource()
    lexical = _ClosableResource()
    semantic = _ClosableResource()
    service = HybridRetrievalService(
        config=AppConfig(),
        embedder=embedder,
        reranker=reranker,
        lexical_retriever=lexical,
        semantic_retriever=semantic,
    )

    service.close()

    assert embedder.closed == 1
    assert reranker.closed == 1
    assert lexical.closed == 1
    assert semantic.closed == 1
    assert service.embedder is None
    assert service.reranker is None
    assert service.lexical_retriever is None
    assert service.semantic_retriever is None


def test_build_fts_query_ignores_invalid_operator_tokens():
    assert _build_fts_query("Few-Shot 是 什么") == "few OR shot OR 是 OR 什么"


def test_lexical_search_returns_empty_when_fts_table_is_missing(tmp_path):
    retriever = LexicalRetriever(tmp_path / "missing.db")

    results = retriever.search("不存在的问题", limit=5)

    assert results == ()
    retriever.close()
