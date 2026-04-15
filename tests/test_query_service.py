from __future__ import annotations

from app.config import AppConfig
from app.retrieve.contracts import RetrievedChunk, SearchDebug, SearchResultSet
from app.services.querying import QueryService


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

