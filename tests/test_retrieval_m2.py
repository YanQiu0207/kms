from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from app.config import AppConfig, RetrievalConfig
from app.retrieve import HybridRetrievalService, RetrievedChunk
from app.retrieve.lexical import _build_fts_query, LexicalRetriever
from app.retrieve.semantic import SemanticRetriever
from app.retrieve.rerank import FlagEmbeddingReranker
from app.services.embeddings import EmbeddingService
from app.store import FTS5Writer, SQLiteMetadataStore, StoredChunk, StoredDocument


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


def test_search_applies_query_type_adaptive_fusion_weights():
    lexical = _StaticRetriever(
        [
            RetrievedChunk(document_id="doc-lex", chunk_id="c-lex", content="lexical-first", score=1.0, metadata={"lexical_score": 1.0}),
            RetrievedChunk(document_id="doc-sem", chunk_id="c-sem", content="semantic-first", score=0.6, metadata={"lexical_score": 0.5}),
        ]
    )
    semantic = _StaticRetriever(
        [
            RetrievedChunk(document_id="doc-sem", chunk_id="c-sem", content="semantic-first", score=1.0, metadata={"semantic_score": 1.0}),
            RetrievedChunk(document_id="doc-lex", chunk_id="c-lex", content="lexical-first", score=0.6, metadata={"semantic_score": 0.5}),
        ]
    )
    service = HybridRetrievalService(
        config=AppConfig(
            retrieval=RetrievalConfig(
                recall_top_k=5,
                rerank_top_k=3,
                rrf_k=60,
                query_type_fusion_weights={
                    "lookup": {"lexical": 2.0, "semantic": 0.5},
                    "definition": {"lexical": 0.5, "semantic": 2.0},
                },
            )
        ),
        lexical_retriever=lexical,
        semantic_retriever=semantic,
    )

    lookup = service.search(["对象池"], query_type="lookup")
    definition = service.search(["对象池"], query_type="definition")

    assert [chunk.chunk_id for chunk in lookup.results[:2]] == ["c-lex", "c-sem"]
    assert [chunk.chunk_id for chunk in definition.results[:2]] == ["c-sem", "c-lex"]
    assert lookup.results[0].metadata["fusion_weights"]["lexical"] == 2.0
    assert definition.results[0].metadata["fusion_weights"]["semantic"] == 2.0


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


def test_lexical_search_indexes_front_matter_metadata_text(tmp_path):
    store = SQLiteMetadataStore(tmp_path / "meta.db")
    writer = FTS5Writer(store.connection)
    store.upsert_documents(
        [
            StoredDocument(
                document_id="doc-1",
                content="对象池文档",
                file_path="E:/github/mykms/data/corpora/e-notes-frontmatter-v1/程序设计/对象池.md",
            )
        ]
    )
    store.upsert_chunks(
        [
            StoredChunk(
                chunk_id="chunk-1",
                document_id="doc-1",
                content="只讲对象复用和池化实现。",
                file_path="E:/github/mykms/data/corpora/e-notes-frontmatter-v1/程序设计/对象池.md",
                title_path=("对象池",),
                metadata={
                    "relative_path": "程序设计/对象池.md",
                    "front_matter_category": "程序设计",
                    "front_matter_tags": ["程序设计", "对象池"],
                },
            )
        ]
    )
    writer.upsert_chunks(list(store.iter_chunks()))

    retriever = LexicalRetriever(store.connection)
    results = retriever.search("程序设计 分类", limit=5)

    assert [item.chunk_id for item in results] == ["chunk-1"]
    retriever.close()
    store.close()


def test_search_and_rerank_prioritizes_candidates_matching_category_constraint():
    candidates = [
        RetrievedChunk(
            document_id="doc-1",
            chunk_id="c1",
            content="对象池用于对象复用。",
            score=0.4,
            metadata={
                "front_matter_category": "程序设计",
                "relative_path": "程序设计/对象池.md",
                "path_segments": ["程序设计", "对象池.md"],
            },
        ),
        RetrievedChunk(
            document_id="doc-2",
            chunk_id="c2",
            content="面对对象程序设计介绍封装继承多态。",
            score=0.9,
            metadata={
                "front_matter_category": "c++最佳实践",
                "relative_path": "c++最佳实践/面对对象程序设计.md",
                "path_segments": ["c++最佳实践", "面对对象程序设计.md"],
            },
        ),
    ]
    lexical = _StaticRetriever(candidates)
    semantic = _StaticRetriever(candidates)
    reranker = _StaticReranker([candidates[1], candidates[0]])
    service = HybridRetrievalService(
        config=AppConfig(retrieval=RetrievalConfig(recall_top_k=5, rerank_top_k=2, rrf_k=60, min_output_score=0.0)),
        lexical_retriever=lexical,
        semantic_retriever=semantic,
        reranker=reranker,
    )

    result = service.search_and_rerank(["程序设计分类里有没有关于对象复用的笔记"], recall_top_k=5, rerank_top_k=2)

    assert [chunk.chunk_id for chunk in result.results] == ["c1"]
    assert result.results[0].metadata["metadata_constraint_passed"] is True
    assert float(result.results[0].score or 0.0) >= 0.3


def test_search_and_rerank_returns_empty_when_category_constraint_has_no_match():
    candidates = [
        RetrievedChunk(
            document_id="doc-1",
            chunk_id="c1",
            content="分库分表介绍了水平拆分。",
            score=0.95,
            metadata={
                "front_matter_category": "系统架构",
                "relative_path": "系统架构/数据库架构/分库分表.md",
                "path_segments": ["系统架构", "数据库架构", "分库分表.md"],
            },
        )
    ]
    lexical = _StaticRetriever(candidates)
    semantic = _StaticRetriever(candidates)
    reranker = _StaticReranker(candidates)
    service = HybridRetrievalService(
        config=AppConfig(retrieval=RetrievalConfig(recall_top_k=5, rerank_top_k=2, rrf_k=60, min_output_score=0.0)),
        lexical_retriever=lexical,
        semantic_retriever=semantic,
        reranker=reranker,
    )

    result = service.search_and_rerank(["数据库分类下有没有讲分库分表"], recall_top_k=5, rerank_top_k=2)

    assert result.results == ()


def test_search_and_rerank_ignores_generic_knowledge_base_context_prefix():
    candidate = RetrievedChunk(
        document_id="doc-1",
        chunk_id="c1",
        file_path="E:/notes/apue/定时器.md",
        title_path=("定时器", "timerfd 系列函数"),
        content="timerfd 系列函数是 Linux 提供的定时器接口。",
        score=0.42,
        metadata={
            "relative_path": "apue/定时器.md",
            "path_segments": ["apue", "定时器.md"],
            "lexical_score": 0.31,
        },
    )
    lexical = _StaticRetriever([candidate])
    semantic = _StaticRetriever([candidate])
    reranker = _StaticReranker([candidate])
    service = HybridRetrievalService(
        config=AppConfig(retrieval=RetrievalConfig(recall_top_k=5, rerank_top_k=2, rrf_k=60, min_output_score=0.0)),
        lexical_retriever=lexical,
        semantic_retriever=semantic,
        reranker=reranker,
    )

    result = service.search_and_rerank(["知识库里有没有讲 timerfd"], recall_top_k=5, rerank_top_k=2)

    assert [chunk.chunk_id for chunk in result.results] == ["c1"]
    assert "query_metadata_constraints" not in result.results[0].metadata or not result.results[0].metadata["query_metadata_constraints"]


def test_search_and_rerank_prefers_document_with_stronger_metadata_constrained_support():
    doc_primary_a = RetrievedChunk(
        document_id="doc-1",
        chunk_id="c1a",
        content="timerfd系列函数总结",
        score=0.45,
        metadata={
            "front_matter_category": "网络编程",
            "relative_path": "网络编程/网络编程常见问题/定时器.md",
            "path_segments": ["网络编程", "网络编程常见问题", "定时器.md"],
            "lexical_score": 0.33,
        },
    )
    doc_primary_b = RetrievedChunk(
        document_id="doc-1",
        chunk_id="c1b",
        content="创建 timerfd 定时器",
        score=0.44,
        metadata={
            "front_matter_category": "网络编程",
            "relative_path": "网络编程/网络编程常见问题/定时器.md",
            "path_segments": ["网络编程", "网络编程常见问题", "定时器.md"],
            "lexical_score": 0.25,
        },
    )
    doc_secondary = RetrievedChunk(
        document_id="doc-2",
        chunk_id="c2",
        content="muduo 里用 timerfd 处理定时器",
        score=0.46,
        metadata={
            "front_matter_category": "网络编程",
            "relative_path": "网络编程/muduo学习笔记/1.0 Reactor模型.md",
            "path_segments": ["网络编程", "muduo学习笔记", "1.0 Reactor模型.md"],
            "lexical_score": 0.06,
        },
    )
    lexical = _StaticRetriever([doc_primary_a, doc_primary_b, doc_secondary])
    semantic = _StaticRetriever([doc_primary_a, doc_primary_b, doc_secondary])
    reranker = _StaticReranker([doc_secondary, doc_primary_a, doc_primary_b])
    service = HybridRetrievalService(
        config=AppConfig(retrieval=RetrievalConfig(recall_top_k=5, rerank_top_k=3, rrf_k=60, min_output_score=0.0)),
        lexical_retriever=lexical,
        semantic_retriever=semantic,
        reranker=reranker,
    )

    result = service.search_and_rerank(["网络编程分类下有没有讲 timerfd"], recall_top_k=5, rerank_top_k=3)

    assert [chunk.chunk_id for chunk in result.results] == ["c1a", "c1b", "c2"]
    assert result.results[0].metadata["metadata_document_support_count"] == 2
    assert result.results[2].metadata["metadata_document_support_count"] == 1


def test_search_and_rerank_prefers_structured_lookup_chunk_for_mapping_queries():
    structured = RetrievedChunk(
        document_id="doc-1",
        chunk_id="table",
        file_path="E:/notes/第三方软件/gdb/1.0 基础知识.md",
        title_path=("GDB调试", "GDB常用调试命令"),
        content="表格行: 命令名称是 backtrace；命令缩写是 bt；命令说明是 查看当前线程的调用堆栈",
        score=0.87,
        metadata={"lexical_score": 0.5},
    )
    detailed = RetrievedChunk(
        document_id="doc-2",
        chunk_id="detail",
        file_path="E:/notes/第三方软件/gdb/2.0 常用命令详解.md",
        title_path=("常用命令详解", "backtrace与frame命令"),
        content="backtrace 命令（简写为 bt）用来查看当前调用堆栈。",
        score=0.97,
        metadata={"lexical_score": 1.0},
    )
    lexical = _StaticRetriever([structured, detailed])
    semantic = _StaticRetriever([structured, detailed])
    reranker = _StaticReranker([detailed, structured])
    service = HybridRetrievalService(
        config=AppConfig(retrieval=RetrievalConfig(recall_top_k=5, rerank_top_k=2, rrf_k=60, min_output_score=0.0)),
        lexical_retriever=lexical,
        semantic_retriever=semantic,
        reranker=reranker,
    )

    result = service.search_and_rerank(["GDB backtrace 缩写", "backtrace 缩写 bt"], recall_top_k=5, rerank_top_k=2)

    assert [chunk.chunk_id for chunk in result.results] == ["table", "detail"]
    assert result.results[0].metadata["lookup_term_coverage"] == 1.0
    assert result.results[0].metadata["lookup_table_row_count"] == 1


def test_search_and_rerank_respects_configured_ranking_pipeline_steps():
    structured = RetrievedChunk(
        document_id="doc-1",
        chunk_id="table",
        file_path="E:/notes/第三方软件/gdb/1.0 基础知识.md",
        title_path=("GDB调试", "GDB常用调试命令"),
        content="表格行: 命令名称是 backtrace；命令缩写是 bt；命令说明是 查看当前线程的调用堆栈",
        score=0.87,
        metadata={"lexical_score": 0.5},
    )
    detailed = RetrievedChunk(
        document_id="doc-2",
        chunk_id="detail",
        file_path="E:/notes/第三方软件/gdb/2.0 常用命令详解.md",
        title_path=("常用命令详解", "backtrace与frame命令"),
        content="backtrace 命令（简写为 bt）用来查看当前调用堆栈。",
        score=0.97,
        metadata={"lexical_score": 1.0},
    )
    lexical = _StaticRetriever([structured, detailed])
    semantic = _StaticRetriever([structured, detailed])
    reranker = _StaticReranker([detailed, structured])
    service = HybridRetrievalService(
        config=AppConfig(
            retrieval=RetrievalConfig(
                recall_top_k=5,
                rerank_top_k=2,
                rrf_k=60,
                min_output_score=0.0,
                ranking_pipeline=[
                    "limit_rerank_candidates",
                    "rerank",
                    "top_k_limit",
                ],
            )
        ),
        lexical_retriever=lexical,
        semantic_retriever=semantic,
        reranker=reranker,
    )

    result = service.search_and_rerank(["GDB backtrace 缩写", "backtrace 缩写 bt"], recall_top_k=5, rerank_top_k=2)

    assert [chunk.chunk_id for chunk in result.results] == ["detail", "table"]
    assert "lookup_term_coverage" not in result.results[0].metadata


def test_search_and_rerank_diversifies_lookup_results_across_documents():
    top_a = RetrievedChunk(
        document_id="doc-a",
        chunk_id="a1",
        file_path="E:/notes/第三方软件/gdb/2.0 常用命令详解.md",
        title_path=("常用命令详解", "info break"),
        content="info break 查看所有断点。",
        score=0.98,
        metadata={"lexical_score": 0.6},
    )
    second_a = RetrievedChunk(
        document_id="doc-a",
        chunk_id="a2",
        file_path="E:/notes/第三方软件/gdb/2.0 常用命令详解.md",
        title_path=("常用命令详解", "info thread"),
        content="info thread 查看线程信息。",
        score=0.97,
        metadata={"lexical_score": 0.55},
    )
    top_b = RetrievedChunk(
        document_id="doc-b",
        chunk_id="b1",
        file_path="E:/notes/第三方软件/gdb/1.0 基础知识.md",
        title_path=("GDB调试", "GDB常用调试命令"),
        content="表格行: 命令名称是 info；命令缩写是 info；命令说明是 查看断点 / 线程等信息",
        score=0.95,
        metadata={"lexical_score": 1.0},
    )
    lexical = _StaticRetriever([top_a, second_a, top_b])
    semantic = _StaticRetriever([top_a, second_a, top_b])
    reranker = _StaticReranker([top_a, second_a, top_b])
    service = HybridRetrievalService(
        config=AppConfig(retrieval=RetrievalConfig(recall_top_k=5, rerank_top_k=3, rrf_k=60, min_output_score=0.0)),
        lexical_retriever=lexical,
        semantic_retriever=semantic,
        reranker=reranker,
    )

    result = service.search_and_rerank(["GDB 查看断点 线程 信息 命令", "GDB info 命令 断点 线程"], recall_top_k=5, rerank_top_k=3)

    assert [chunk.chunk_id for chunk in result.results] == ["b1", "a1", "a2"]


def test_search_and_rerank_applies_lookup_prioritization_before_output_top_k_cut():
    top_a = RetrievedChunk(
        document_id="doc-a",
        chunk_id="a1",
        file_path="E:/notes/第三方软件/gdb/2.0 常用命令详解.md",
        title_path=("常用命令详解", "info break"),
        content="info break 查看所有断点。",
        score=0.98,
        metadata={"lexical_score": 0.6},
    )
    second_a = RetrievedChunk(
        document_id="doc-a",
        chunk_id="a2",
        file_path="E:/notes/第三方软件/gdb/2.0 常用命令详解.md",
        title_path=("常用命令详解", "info thread"),
        content="info thread 查看线程信息。",
        score=0.97,
        metadata={"lexical_score": 0.55},
    )
    table_b = RetrievedChunk(
        document_id="doc-b",
        chunk_id="b1",
        file_path="E:/notes/第三方软件/gdb/1.0 基础知识.md",
        title_path=("GDB调试", "GDB常用调试命令"),
        content="表格行: 命令名称是 info；命令缩写是 info；命令说明是 查看断点 / 线程等信息",
        score=0.95,
        metadata={"lexical_score": 1.0},
    )
    lexical = _StaticRetriever([top_a, second_a, table_b])
    semantic = _StaticRetriever([top_a, second_a, table_b])
    reranker = _StaticReranker([top_a, second_a, table_b])
    service = HybridRetrievalService(
        config=AppConfig(retrieval=RetrievalConfig(recall_top_k=5, rerank_top_k=2, rrf_k=60, min_output_score=0.0)),
        lexical_retriever=lexical,
        semantic_retriever=semantic,
        reranker=reranker,
    )

    result = service.search_and_rerank(["GDB 查看断点 线程 信息 命令", "GDB info 命令 断点 线程"], recall_top_k=5, rerank_top_k=2)

    assert [chunk.chunk_id for chunk in result.results] == ["b1", "a1"]


def test_search_and_rerank_prefers_subject_document_for_problem_queries():
    subject_doc = RetrievedChunk(
        document_id="doc-2pc",
        chunk_id="two-pc",
        file_path="E:/work/blog/分布式基础/共识/2pc.md",
        title_path=("两阶段提交协议", "优缺点"),
        content="2PC 的主要问题包括阻塞时间长以及协调者单点故障风险。",
        score=0.82,
        metadata={"lexical_score": 0.45},
    )
    competing_doc = RetrievedChunk(
        document_id="doc-3pc",
        chunk_id="three-pc",
        file_path="E:/work/blog/分布式基础/共识/3pc.md",
        title_path=("3PC", "背景"),
        content="3PC 背景里会解释 2PC 的阻塞问题与协调者单点故障。",
        score=0.97,
        metadata={"lexical_score": 0.7},
    )
    lexical = _StaticRetriever([subject_doc, competing_doc])
    semantic = _StaticRetriever([subject_doc, competing_doc])
    reranker = _StaticReranker([competing_doc, subject_doc])
    service = HybridRetrievalService(
        config=AppConfig(retrieval=RetrievalConfig(recall_top_k=5, rerank_top_k=2, rrf_k=60, min_output_score=0.0)),
        lexical_retriever=lexical,
        semantic_retriever=semantic,
        reranker=reranker,
    )

    result = service.search_and_rerank(["2PC 问题", "两阶段提交 缺点"], recall_top_k=5, rerank_top_k=2)

    assert [chunk.chunk_id for chunk in result.results] == ["two-pc", "three-pc"]
    assert result.results[0].metadata["lookup_term_coverage"] > result.results[1].metadata["lookup_term_coverage"]


def test_search_and_rerank_prefers_subject_root_document_for_definition_queries():
    guide = RetrievedChunk(
        document_id="doc-guide",
        chunk_id="guide-section",
        file_path="E:/work/blog/ai/claude-code/guide.md",
        title_path=("Claude Code 使用技巧", "Subagent（自定义子代理）", "创建 Subagent"),
        content="Subagent 是 Claude Code 的一类可配置代理能力。",
        score=0.98,
        metadata={
            "lexical_score": 1.0,
            "relative_path": "ai/claude-code/guide.md",
            "path_segments": ["ai", "claude-code", "guide.md"],
        },
    )
    subject_doc = RetrievedChunk(
        document_id="doc-subagent",
        chunk_id="subject-root",
        file_path="E:/work/blog/ai/claude-code/2-subagent-base.md",
        title_path=("子代理", "什么是子代理"),
        content="子代理相当于一个专职小助手，带着自己的规则、工具权限、上下文窗口去完成任务。",
        score=0.95,
        metadata={
            "lexical_score": 0.2,
            "relative_path": "ai/claude-code/2-subagent-base.md",
            "path_segments": ["ai", "claude-code", "2-subagent-base.md"],
        },
    )
    lexical = _StaticRetriever([guide, subject_doc])
    semantic = _StaticRetriever([guide, subject_doc])
    reranker = _StaticReranker([guide, subject_doc])
    service = HybridRetrievalService(
        config=AppConfig(retrieval=RetrievalConfig(recall_top_k=5, rerank_top_k=2, rrf_k=60, min_output_score=0.0)),
        lexical_retriever=lexical,
        semantic_retriever=semantic,
        reranker=reranker,
    )

    result = service.search_and_rerank(["Claude Code 里 subagent 的基础概念是什么？", "Claude Code subagent"], recall_top_k=5, rerank_top_k=2)

    assert [chunk.chunk_id for chunk in result.results] == ["subject-root", "guide-section"]
    assert result.results[0].metadata["definition_subject_affinity"] == 3
    assert result.results[1].metadata["definition_subject_affinity"] == 1


def test_search_and_rerank_prefers_exact_subject_root_title_over_broader_topic_doc():
    broad = RetrievedChunk(
        document_id="doc-aoi-process",
        chunk_id="aoi-process",
        file_path="E:/work/privy-blog/独立aoi进程.md",
        title_path=("独立aoi进程", "方案设计"),
        content="独立 AOI 进程解释了为什么要把 aoi 从玩家进程分离出来。",
        score=0.98,
        metadata={
            "relative_path": "独立aoi进程.md",
            "path_segments": ["独立aoi进程.md"],
        },
    )
    exact = RetrievedChunk(
        document_id="doc-aoi",
        chunk_id="aoi-root",
        file_path="E:/work/blog/游戏开发/aoi-algo.md",
        title_path=("AOI",),
        content="AOI 是感兴趣区域，用于减少同步消息并提供附近对象集合。",
        score=0.94,
        metadata={
            "relative_path": "游戏开发/aoi-algo.md",
            "path_segments": ["游戏开发", "aoi-algo.md"],
        },
    )
    lexical = _StaticRetriever([exact, broad])
    semantic = _StaticRetriever([exact, broad])
    reranker = _StaticReranker([broad, exact])
    service = HybridRetrievalService(
        config=AppConfig(retrieval=RetrievalConfig(recall_top_k=5, rerank_top_k=2, rrf_k=60, min_output_score=0.0)),
        lexical_retriever=lexical,
        semantic_retriever=semantic,
        reranker=reranker,
    )

    result = service.search_and_rerank(["为什么需要 AOI？", "AOI 作用"], recall_top_k=5, rerank_top_k=2)

    assert [chunk.chunk_id for chunk in result.results] == ["aoi-root", "aoi-process"]
    assert result.results[0].metadata["definition_subject_affinity"] == 3
    assert result.results[1].metadata["definition_subject_affinity"] == 1
