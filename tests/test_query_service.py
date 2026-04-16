from __future__ import annotations

from pathlib import Path

from app.config import AppConfig
from app.retrieve.contracts import RetrievedChunk, SearchDebug, SearchResultSet
from app.services.querying import QueryService
from app.store import SQLiteMetadataStore, StoredChunk, StoredDocument


class _RecordingRetrieval:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], int | None, int | None]] = []
        self.closed = False

    def search_and_rerank(self, queries, *, recall_top_k=None, rerank_top_k=None):
        key = (tuple(queries), recall_top_k, rerank_top_k)
        self.calls.append(key)
        return SearchResultSet(results=(), debug=SearchDebug(queries_count=len(tuple(queries))))

    def close(self):
        self.closed = True


class _StaticRetrieval:
    def __init__(self, results):
        self.results = tuple(results)

    def search_and_rerank(self, queries, *, recall_top_k=None, rerank_top_k=None):
        return SearchResultSet(results=self.results, debug=SearchDebug(queries_count=len(tuple(queries)), recall_count=len(self.results), rerank_count=len(self.results)))

    def close(self):
        return None


def test_query_service_search_reuses_cached_results():
    service = QueryService(AppConfig())
    fake = _RecordingRetrieval()
    service._retrieval = fake

    first = service.search(["网络同步", "帧同步"], recall_top_k=8, rerank_top_k=4)
    second = service.search(["网络同步", "帧同步"], recall_top_k=8, rerank_top_k=4)

    assert first is second
    assert fake.calls == [(("网络同步", "帧同步"), 8, 4)]


def test_query_service_expands_single_question_into_keywords():
    service = QueryService(AppConfig())

    expanded = service._expand_queries(["共识算法有哪些？各有什么特点？"])

    assert expanded[0] == "共识算法有哪些？各有什么特点？"
    assert "共识算法有哪些 各有什么特点" in expanded
    assert "共识 算法 特点" in expanded


def test_query_service_expands_alias_variants_for_two_phase_commit():
    service = QueryService(AppConfig())

    expanded = service._expand_queries(["两阶段提交的主要问题有哪些？"])

    assert any("2pc" in query.casefold() for query in expanded)


def test_query_service_routes_comparison_queries_to_larger_search_window():
    service = QueryService(AppConfig())
    service.config.retrieval.recall_top_k = 10
    service.config.retrieval.rerank_top_k = 4
    fake = _RecordingRetrieval()
    service._retrieval = fake

    service.search(["HLC 和 TrueTime 的区别是什么？"])

    assert len(fake.calls) == 1
    expanded_queries, recall_top_k, rerank_top_k = fake.calls[0]
    assert recall_top_k == 24
    assert rerank_top_k == 8
    assert any("hlc" in query.casefold() for query in expanded_queries)
    assert any("truetime" in query.casefold() or "true time" in query.casefold() for query in expanded_queries)


def test_query_service_keeps_original_question_for_multi_query_metadata_search():
    service = QueryService(AppConfig())
    service.config.retrieval.recall_top_k = 10
    service.config.retrieval.rerank_top_k = 4
    fake = _RecordingRetrieval()
    service._retrieval = fake

    service.ask(
        "网络编程分类下有没有讲 timerfd？",
        queries=("网络编程 timerfd", "timerfd 定时器"),
    )

    assert len(fake.calls) == 1
    expanded_queries, recall_top_k, rerank_top_k = fake.calls[0]
    assert recall_top_k == 22
    assert rerank_top_k == 8
    assert expanded_queries[0] == "网络编程分类下有没有讲 timerfd？"
    assert "网络编程 timerfd" in expanded_queries
    assert "timerfd 定时器" in expanded_queries


def test_query_service_close_clears_cache_and_closes_retrieval():
    service = QueryService(AppConfig())
    fake = _RecordingRetrieval()
    service._retrieval = fake
    service._search_cache[(("网络同步",), None, None)] = object()

    service.close()

    assert service._search_cache == {}
    assert fake.closed is True


def test_query_service_ask_abstains_when_query_term_coverage_is_too_low():
    service = QueryService(AppConfig())
    service.config.abstain.top1_min = 0.0
    service.config.abstain.top3_avg_min = 0.0
    service.config.abstain.min_hits = 1
    service.config.abstain.min_total_chars = 1
    service.config.abstain.min_query_term_count = 2
    service.config.abstain.min_query_term_coverage = 0.6
    service._retrieval = _StaticRetrieval(
        [
            RetrievedChunk(
                document_id="doc-1",
                file_path="E:/work/blog/分布式基础/共识/raft_learning_plan.md",
                title_path=("3个月 Raft 学习计划", "第8周：Raft 与其他共识算法的对比"),
                content="ZAB 是 ZooKeeper 的底层协议，介绍了 leader 选举和日志广播，以及同步过程。",
                score=0.48,
            )
        ]
    )

    result = service.ask(
        "文档里有没有介绍 ZooKeeper watch 机制？",
        queries=("ZooKeeper watch 机制", "watch 机制"),
    )

    assert result.abstained is True
    assert result.abstain_reason == "query_term_coverage_below_threshold"


def test_query_service_ask_keeps_answer_when_any_query_variant_is_well_covered():
    service = QueryService(AppConfig())
    service.config.abstain.top1_min = 0.0
    service.config.abstain.top3_avg_min = 0.0
    service.config.abstain.min_hits = 1
    service.config.abstain.min_total_chars = 1
    service.config.abstain.min_query_term_count = 2
    service.config.abstain.min_query_term_coverage = 0.6
    service._retrieval = _StaticRetrieval(
        [
            RetrievedChunk(
                document_id="doc-1",
                file_path="E:/work/blog/分布式基础/事件排序/true-time.md",
                title_path=("TrueTime",),
                content="Google TrueTime 通过提供带误差界限的全局时间，帮助外部一致性落地。",
                score=0.91,
            )
        ]
    )

    result = service.ask(
        "TrueTime 的关键价值是什么？",
        queries=("TrueTime 价值", "Google TrueTime"),
    )

    assert result.abstained is False
    assert result.prompt


def test_query_service_ask_uses_weighted_cross_variant_coverage_for_repeated_anchor_term():
    service = QueryService(AppConfig())
    service.config.abstain.top1_min = 0.0
    service.config.abstain.top3_avg_min = 0.0
    service.config.abstain.min_hits = 1
    service.config.abstain.min_total_chars = 1
    service.config.abstain.min_query_term_count = 2
    service.config.abstain.min_query_term_coverage = 0.6
    service._retrieval = _StaticRetrieval(
        [
            RetrievedChunk(
                document_id="doc-1",
                file_path="E:/work/blog/分布式基础/事件排序/true-time.md",
                title_path=("TrueTime", "实现"),
                content="TrueTime 通过带误差界限的全局时间与 commit wait 支持外部一致性。",
                score=0.91,
            ),
            RetrievedChunk(
                document_id="doc-1",
                file_path="E:/work/blog/分布式基础/事件排序/true-time.md",
                title_path=("TrueTime", "实现"),
                content="TrueTime 的关键价值在于帮助全球部署下的事务维持外部一致性。",
                score=0.87,
            ),
        ]
    )

    result = service.ask(
        "TrueTime 的关键价值是什么？",
        queries=("TrueTime 价值", "Google TrueTime"),
    )

    assert result.abstained is False
    assert result.prompt


def test_query_service_ask_does_not_stitch_weighted_coverage_across_documents():
    service = QueryService(AppConfig())
    service.config.abstain.top1_min = 0.0
    service.config.abstain.top3_avg_min = 0.0
    service.config.abstain.min_hits = 1
    service.config.abstain.min_total_chars = 1
    service.config.abstain.min_query_term_count = 2
    service.config.abstain.min_query_term_coverage = 0.6
    service._retrieval = _StaticRetrieval(
        [
            RetrievedChunk(
                document_id="doc-zk",
                file_path="E:/work/blog/分布式基础/zookeeper.md",
                title_path=("ZooKeeper 简介",),
                content="ZooKeeper 用于协调与配置管理。",
                score=0.91,
            ),
            RetrievedChunk(
                document_id="doc-watch",
                file_path="E:/notes/设计模式/18.0 观察者模式.md",
                title_path=("观察者模式",),
                content="watch 机制会在观察者模式里出现，但这里并不是分布式协调场景。",
                score=0.89,
            ),
        ]
    )

    result = service.ask(
        "文档里有没有介绍 ZooKeeper watch 机制？",
        queries=("ZooKeeper watch 机制", "watch 机制"),
    )

    assert result.abstained is True
    assert result.abstain_reason == "query_term_coverage_below_threshold"


def test_query_service_ask_counts_front_matter_metadata_for_query_term_coverage():
    service = QueryService(AppConfig())
    service.config.abstain.top1_min = 0.0
    service.config.abstain.top3_avg_min = 0.0
    service.config.abstain.min_hits = 1
    service.config.abstain.min_total_chars = 1
    service.config.abstain.min_query_term_count = 2
    service.config.abstain.min_query_term_coverage = 0.6
    service._retrieval = _StaticRetrieval(
        [
            RetrievedChunk(
                document_id="doc-1",
                file_path="E:/github/mykms/data/corpora/e-notes-frontmatter-v1/网络编程/muduo学习笔记/1.0 Reactor模型.md",
                title_path=("muduo中的Reactor",),
                content="Reactor 模型介绍了事件循环与回调分发。",
                score=0.92,
                metadata={
                    "relative_path": "网络编程/muduo学习笔记/1.0 Reactor模型.md",
                    "front_matter_category": "网络编程",
                    "path_segments": ["网络编程", "muduo学习笔记", "1.0 Reactor模型.md"],
                },
            )
        ]
    )

    result = service.ask(
        "muduo学习笔记里哪篇讲 Reactor？",
        queries=("muduo 学习笔记 Reactor",),
    )

    assert result.abstained is False
    assert result.prompt


def test_query_service_ask_relaxes_existence_guardrail_for_single_document_exact_hit():
    service = QueryService(AppConfig())
    service.config.abstain.top1_min = 0.2
    service.config.abstain.top3_avg_min = 0.3
    service.config.abstain.min_hits = 2
    service.config.abstain.min_total_chars = 150
    service.config.abstain.min_query_term_count = 2
    service.config.abstain.min_query_term_coverage = 0.6
    service._retrieval = _StaticRetrieval(
        [
            RetrievedChunk(
                document_id="doc-timerfd",
                file_path="E:/notes/apue/定时器.md",
                title_path=("定时器", "timerfd 系列函数"),
                content="timerfd 系列函数是 Linux 提供的定时器接口。",
                score=0.05,
            )
        ]
    )

    result = service.ask(
        "知识库里有没有讲 timerfd 的笔记？",
        queries=("有没有讲 timerfd 的笔记", "timerfd 定时器"),
    )

    assert result.abstained is False
    assert result.prompt


def test_query_service_ask_does_not_relax_existence_guardrail_for_cross_document_partial_hits():
    service = QueryService(AppConfig())
    service.config.abstain.top1_min = 0.2
    service.config.abstain.top3_avg_min = 0.3
    service.config.abstain.min_hits = 2
    service.config.abstain.min_total_chars = 150
    service.config.abstain.min_query_term_count = 2
    service.config.abstain.min_query_term_coverage = 0.6
    service._retrieval = _StaticRetrieval(
        [
            RetrievedChunk(
                document_id="doc-zk",
                file_path="E:/work/blog/分布式基础/zookeeper.md",
                title_path=("ZooKeeper",),
                content="ZooKeeper 用于分布式协调。",
                score=0.05,
            ),
            RetrievedChunk(
                document_id="doc-watch",
                file_path="E:/notes/设计模式/18.0 观察者模式.md",
                title_path=("观察者模式",),
                content="watch 一词会出现在观察者模式语境里。",
                score=0.04,
            ),
        ]
    )

    result = service.ask(
        "文档里有没有介绍 ZooKeeper watch 机制？",
        queries=("ZooKeeper watch 机制", "watch 机制"),
    )

    assert result.abstained is True
    assert result.abstain_reason == "top1_score_below_threshold"


def test_query_service_ask_abstains_when_markdown_extension_and_toc_comment_are_only_matches():
    service = QueryService(AppConfig())
    service.config.abstain.top1_min = 0.0
    service.config.abstain.top3_avg_min = 0.0
    service.config.abstain.min_hits = 1
    service.config.abstain.min_total_chars = 1
    service.config.abstain.min_query_term_count = 2
    service.config.abstain.min_query_term_coverage = 0.6
    service._retrieval = _StaticRetrieval(
        [
            RetrievedChunk(
                document_id="doc-1",
                file_path="E:/work/blog/分布式基础/事件排序/physical-time.markdown",
                title_path=("物理时间",),
                content="<!-- TOC -->\n目录自动展开的列表。\n<!-- /TOC -->",
                score=0.91,
            )
        ]
    )

    result = service.ask(
        "知识库里有没有专门介绍 Markdown TOC 指令原理？",
        queries=("Markdown TOC 指令 原理", "TOC 指令 原理"),
    )

    assert result.abstained is True
    assert result.abstain_reason == "query_term_coverage_below_threshold"


def test_query_service_ask_allows_short_metadata_constrained_evidence_when_metadata_support_is_strong():
    service = QueryService(AppConfig())
    service.config.abstain.top1_min = 0.2
    service.config.abstain.top3_avg_min = 0.3
    service.config.abstain.min_hits = 2
    service.config.abstain.min_total_chars = 150
    service.config.abstain.min_query_term_count = 2
    service.config.abstain.min_query_term_coverage = 0.6
    service._retrieval = _StaticRetrieval(
        [
            RetrievedChunk(
                document_id="doc-1",
                file_path="E:/github/mykms/data/corpora/e-notes-frontmatter-v1/程序设计/对象池.md",
                title_path=("对象池",),
                content="# 对象池",
                score=0.3867,
                metadata={
                    "metadata_constraint_passed": True,
                    "metadata_constraint_coverage": 1.0,
                    "relative_path": "程序设计/对象池.md",
                    "front_matter_category": "程序设计",
                    "front_matter_tags": ["程序设计", "对象池"],
                    "path_segments": ["程序设计", "对象池.md"],
                },
            ),
            RetrievedChunk(
                document_id="doc-1",
                file_path="E:/github/mykms/data/corpora/e-notes-frontmatter-v1/程序设计/对象池.md",
                title_path=("对象池", "测试", "malloc"),
                content="### malloc",
                score=0.3839,
                metadata={
                    "metadata_constraint_passed": True,
                    "metadata_constraint_coverage": 1.0,
                    "relative_path": "程序设计/对象池.md",
                    "front_matter_category": "程序设计",
                    "front_matter_tags": ["程序设计", "对象池"],
                    "path_segments": ["程序设计", "对象池.md"],
                },
            ),
            RetrievedChunk(
                document_id="doc-1",
                file_path="E:/github/mykms/data/corpora/e-notes-frontmatter-v1/程序设计/对象池.md",
                title_path=("对象池", "测试", "tcmalloc"),
                content="### tcmalloc",
                score=0.3832,
                metadata={
                    "metadata_constraint_passed": True,
                    "metadata_constraint_coverage": 1.0,
                    "relative_path": "程序设计/对象池.md",
                    "front_matter_category": "程序设计",
                    "front_matter_tags": ["程序设计", "对象池"],
                    "path_segments": ["程序设计", "对象池.md"],
                },
            ),
        ]
    )

    result = service.ask(
        "程序设计分类里有没有关于对象复用的笔记？",
        queries=("程序设计 对象 复用", "程序设计 分类 对象复用"),
    )

    assert result.abstained is False
    assert result.sources


def test_query_service_ask_allows_metadata_supported_semantic_hits_from_single_document():
    service = QueryService(AppConfig())
    service.config.abstain.top1_min = 0.2
    service.config.abstain.top3_avg_min = 0.3
    service.config.abstain.min_hits = 2
    service.config.abstain.min_total_chars = 150
    service.config.abstain.min_query_term_count = 2
    service.config.abstain.min_query_term_coverage = 0.6
    service._retrieval = _StaticRetrieval(
        [
            RetrievedChunk(
                document_id="doc-1",
                file_path="E:/github/mykms/data/corpora/e-notes-frontmatter-v1/程序设计/对象池.md",
                title_path=("对象池",),
                content="# 对象池",
                score=0.4167,
                metadata={
                    "metadata_constraint_passed": True,
                    "metadata_constraint_coverage": 1.0,
                    "relative_path": "程序设计/对象池.md",
                    "front_matter_category": "程序设计",
                    "front_matter_tags": ["程序设计", "对象池"],
                    "path_segments": ["程序设计", "对象池.md"],
                    "semantic_score": 0.5773,
                    "source_hits": [
                        "lexical:程序设计 对象 复用",
                        "lexical:程序设计 分类 对象复用",
                        "semantic:程序设计 对象 复用",
                    ],
                },
            ),
            RetrievedChunk(
                document_id="doc-1",
                file_path="E:/github/mykms/data/corpora/e-notes-frontmatter-v1/程序设计/对象池.md",
                title_path=("对象池", "适用场景"),
                content="对象池适合对构造成本高且可复位的对象做统一复用与回收。",
                score=0.4012,
                metadata={
                    "metadata_constraint_passed": True,
                    "metadata_constraint_coverage": 1.0,
                    "relative_path": "程序设计/对象池.md",
                    "front_matter_title": "程序设计中的对象池与对象复用实践",
                    "front_matter_category": "程序设计",
                    "front_matter_aliases": ["对象复用", "对象缓存", "池化分配"],
                    "front_matter_tags": ["程序设计", "对象池", "对象复用", "内存池"],
                    "path_segments": ["程序设计", "对象池.md"],
                    "source_hits": [
                        "lexical:程序设计 对象 复用",
                        "semantic:程序设计 对象 复用",
                    ],
                },
            ),
            RetrievedChunk(
                document_id="doc-1",
                file_path="E:/github/mykms/data/corpora/e-notes-frontmatter-v1/程序设计/对象池.md",
                title_path=("对象池", "测试", "malloc"),
                content="在等长对象场景里，池化可以减少频繁 malloc 与 free 带来的碎片和锁竞争。",
                score=0.3921,
                metadata={
                    "metadata_constraint_passed": True,
                    "metadata_constraint_coverage": 1.0,
                    "relative_path": "程序设计/对象池.md",
                    "front_matter_title": "程序设计中的对象池与对象复用实践",
                    "front_matter_category": "程序设计",
                    "front_matter_aliases": ["对象复用", "对象缓存", "池化分配"],
                    "front_matter_tags": ["程序设计", "对象池", "对象复用", "内存池"],
                    "path_segments": ["程序设计", "对象池.md"],
                    "source_hits": [
                        "lexical:程序设计 分类 对象复用",
                        "semantic:程序设计 对象 复用",
                    ],
                },
            ),
            RetrievedChunk(
                document_id="doc-1",
                file_path="E:/github/mykms/data/corpora/e-notes-frontmatter-v1/程序设计/对象池.md",
                title_path=("对象池", "测试", "tcmalloc"),
                content="测试部分对 malloc、tcmalloc、jemalloc 做了对比，关注对象复用与分配性能。",
                score=0.3886,
                metadata={
                    "metadata_constraint_passed": True,
                    "metadata_constraint_coverage": 1.0,
                    "relative_path": "程序设计/对象池.md",
                    "front_matter_title": "程序设计中的对象池与对象复用实践",
                    "front_matter_category": "程序设计",
                    "front_matter_aliases": ["对象复用", "对象缓存", "池化分配"],
                    "front_matter_tags": ["程序设计", "对象池", "对象复用", "内存池"],
                    "path_segments": ["程序设计", "对象池.md"],
                    "source_hits": [
                        "lexical:程序设计 分类 对象复用",
                        "semantic:程序设计 分类 对象复用",
                    ],
                },
            ),
        ]
    )

    result = service.ask(
        "程序设计分类里有没有关于对象复用的笔记？",
        queries=("程序设计分类里有没有关于对象复用的笔记？", "程序设计 对象 复用", "程序设计 分类 对象复用"),
    )

    assert result.abstained is False
    assert result.sources


def test_query_service_ask_expands_prompt_evidence_with_same_section_parent_context(tmp_path: Path):
    sqlite_path = tmp_path / "meta.db"
    store = SQLiteMetadataStore(sqlite_path)
    try:
        store.upsert_documents(
            [
                StoredDocument(
                    document_id="doc-1",
                    content="Raft 文档",
                    file_path="E:/notes/distributed/raft.md",
                )
            ]
        )
        store.upsert_chunks(
            [
                StoredChunk(
                    chunk_id="chunk-1",
                    document_id="doc-1",
                    content="Raft 的 leader 负责处理客户端写入。",
                    file_path="E:/notes/distributed/raft.md",
                    chunk_index=0,
                    title_path=("Raft", "Leader Election"),
                    metadata={"section_index": 1, "start_line": 10, "end_line": 12},
                ),
                StoredChunk(
                    chunk_id="chunk-2",
                    document_id="doc-1",
                    content="candidate 会在超时后发起选举并请求投票。",
                    file_path="E:/notes/distributed/raft.md",
                    chunk_index=1,
                    title_path=("Raft", "Leader Election"),
                    metadata={"section_index": 1, "start_line": 13, "end_line": 16},
                ),
                StoredChunk(
                    chunk_id="chunk-3",
                    document_id="doc-1",
                    content="日志复制会在选举完成后继续推进。",
                    file_path="E:/notes/distributed/raft.md",
                    chunk_index=2,
                    title_path=("Raft", "Log Replication"),
                    metadata={"section_index": 2, "start_line": 20, "end_line": 24},
                ),
            ]
        )
    finally:
        store.close()

    service = QueryService(AppConfig())
    service.config.data.sqlite = str(sqlite_path)
    service.config.abstain.top1_min = 0.0
    service.config.abstain.top3_avg_min = 0.0
    service.config.abstain.min_hits = 1
    service.config.abstain.min_total_chars = 1
    service.config.abstain.min_query_term_count = 1
    service.config.abstain.min_query_term_coverage = 0.0
    service.config.retrieval.parent_context_enabled = True
    service.config.retrieval.parent_context_max_chunks = 2
    service._retrieval = _StaticRetrieval(
        [
            RetrievedChunk(
                document_id="doc-1",
                chunk_id="chunk-2",
                file_path="E:/notes/distributed/raft.md",
                title_path=("Raft", "Leader Election"),
                content="candidate 会在超时后发起选举并请求投票。",
                score=0.91,
                metadata={"section_index": 1, "start_line": 13, "end_line": 16},
            )
        ]
    )

    result = service.ask(
        "Raft 怎么发起 leader 选举？",
        queries=("Raft leader 选举",),
    )

    assert result.abstained is False
    assert result.sources
    assert "Raft 的 leader 负责处理客户端写入。" in str(result.sources[0]["text"])
    assert "candidate 会在超时后发起选举并请求投票。" in str(result.sources[0]["text"])
    assert "日志复制会在选举完成后继续推进。" not in str(result.sources[0]["text"])
    assert result.sources[0]["location"] == "raft.md:10-16"


def test_query_service_verify_uses_expanded_parent_context_for_citation_matching(tmp_path: Path):
    sqlite_path = tmp_path / "meta.db"
    store = SQLiteMetadataStore(sqlite_path)
    try:
        store.upsert_documents(
            [
                StoredDocument(
                    document_id="doc-1",
                    content="Raft 文档",
                    file_path="E:/notes/distributed/raft.md",
                )
            ]
        )
        store.upsert_chunks(
            [
                StoredChunk(
                    chunk_id="chunk-1",
                    document_id="doc-1",
                    content="Raft 的 leader 负责处理客户端写入。",
                    file_path="E:/notes/distributed/raft.md",
                    chunk_index=0,
                    title_path=("Raft", "Leader Election"),
                    metadata={"section_index": 1, "start_line": 10, "end_line": 12},
                ),
                StoredChunk(
                    chunk_id="chunk-2",
                    document_id="doc-1",
                    content="candidate 会在超时后发起选举并请求投票。",
                    file_path="E:/notes/distributed/raft.md",
                    chunk_index=1,
                    title_path=("Raft", "Leader Election"),
                    metadata={"section_index": 1, "start_line": 13, "end_line": 16},
                ),
            ]
        )
    finally:
        store.close()

    service = QueryService(AppConfig())
    service.config.data.sqlite = str(sqlite_path)
    service.config.retrieval.parent_context_enabled = True
    service.config.retrieval.parent_context_max_chunks = 2

    result = service.verify(
        "candidate 会在超时后发起选举并请求投票。[chunk-1]",
        ["chunk-1"],
    )

    assert result.citation_unverified is False
    assert "chunk-1" in result.matched_chunk_ids


def test_query_service_loads_dynamic_alias_groups_from_sqlite_documents(tmp_path: Path):
    sqlite_path = tmp_path / "meta.db"
    store = SQLiteMetadataStore(sqlite_path)
    try:
        store.upsert_documents(
            [
                StoredDocument(
                    document_id="doc-1",
                    content="对象池文档",
                    file_path="E:/notes/programming/object-pool.md",
                    metadata={
                        "front_matter": {
                            "aliases": ["对象复用", "对象缓存", "池化分配"],
                        }
                    },
                )
            ]
        )
    finally:
        store.close()

    service = QueryService(AppConfig())
    service.config.data.sqlite = str(sqlite_path)

    expanded = service._expand_queries(
        ("对象复用 好处",),
        alias_groups=service._load_alias_groups(),
    )

    assert any("对象缓存" in query for query in expanded)
    assert any("池化分配" in query for query in expanded)
