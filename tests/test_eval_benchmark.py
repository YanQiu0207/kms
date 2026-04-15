from __future__ import annotations

import json
from pathlib import Path

from app.config import AppConfig, ChunkerConfig, DataConfig, ModelConfig, RetrievalConfig, SourceConfig
from app.services import IndexingService
from eval.benchmark import load_benchmark_cases, run_benchmark


def _build_config(tmp_path: Path, source_dir: Path) -> AppConfig:
    return AppConfig(
        sources=[SourceConfig(path=str(source_dir), excludes=[])],
        data=DataConfig(
            sqlite=str(tmp_path / "data" / "meta.db"),
            chroma=str(tmp_path / "data" / "chroma"),
            hf_cache=str(tmp_path / "data" / "hf-cache"),
        ),
        models=ModelConfig(
            embedding="debug-hash",
            reranker="debug-reranker",
            device="cpu",
            dtype="float32",
        ),
        chunker=ChunkerConfig(
            version="test-v1",
            chunk_size=120,
            chunk_overlap=20,
        ),
        retrieval=RetrievalConfig(
            recall_top_k=8,
            rerank_top_k=4,
            rrf_k=60,
            min_output_score=0.0,
        ),
    )


def test_load_benchmark_cases_supports_enhanced_fields(tmp_path: Path):
    benchmark = tmp_path / "benchmark.jsonl"
    benchmark.write_text(
        json.dumps(
            {
                "id": "case-1",
                "question": "问题",
                "queries": ["问题", "补充"],
                "expected_file_paths": ["a.md"],
                "should_abstain": False,
                "case_type": "rewrite",
                "tags": ["ai", "rewrite"],
                "min_expected_sources": 2,
                "expected_terms": ["术语1", "术语2"],
                "notes": "备注",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    cases = load_benchmark_cases(benchmark)

    assert len(cases) == 1
    assert cases[0].expected_file_paths == ("a.md",)
    assert cases[0].queries == ("问题", "补充")
    assert cases[0].case_type == "rewrite"
    assert cases[0].tags == ("ai", "rewrite")
    assert cases[0].min_expected_sources == 2
    assert cases[0].expected_terms == ("术语1", "术语2")
    assert cases[0].notes == "备注"


def test_run_benchmark_computes_extended_metrics_and_breakdown(tmp_path: Path):
    source_dir = tmp_path / "notes"
    source_dir.mkdir()
    (source_dir / "rag.md").write_text(
        "# RAG\n\n"
        "混合检索结合了词法与语义检索的优势，可以覆盖术语命中和近义表达。\n\n"
        "只做向量检索会漏掉缩写、错误码和配置键名这类更依赖字面匹配的内容。",
        encoding="utf-8",
    )

    benchmark = tmp_path / "benchmark.jsonl"
    benchmark.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "answer-1",
                        "question": "为什么不能只做向量检索？",
                        "queries": ["为什么不能只做向量检索", "混合检索 优势"],
                        "expected_file_paths": [str((source_dir / "rag.md").as_posix())],
                        "should_abstain": False,
                        "case_type": "rewrite",
                        "tags": ["ai", "rewrite"],
                        "min_expected_sources": 1,
                        "expected_terms": ["词法", "语义", "向量检索"],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "id": "abstain-1",
                        "question": "文档里有没有 MCP 自动调用？",
                        "queries": ["MCP 自动调用"],
                        "expected_file_paths": [],
                        "should_abstain": True,
                        "case_type": "abstain",
                        "tags": ["negative"],
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    config = _build_config(tmp_path, source_dir)
    config.abstain.top1_min = 0.0
    config.abstain.top3_avg_min = 0.0
    config.abstain.min_hits = 1
    config.abstain.min_total_chars = 1
    IndexingService(config).index("full")

    summary = run_benchmark(benchmark, config=config)

    assert summary.total_cases == 2
    assert summary.answered_cases == 1
    assert summary.abstain_cases == 1
    assert summary.recall_at_k == 1.0
    assert summary.abstain_accuracy == 1.0
    assert summary.abstain_precision == 1.0
    assert summary.abstain_recall == 1.0
    assert summary.false_abstain_rate == 0.0
    assert summary.false_answer_rate == 0.0
    assert summary.evidence_hit_rate == 1.0
    assert summary.evidence_source_recall == 1.0
    assert summary.source_count_satisfaction_rate == 1.0
    assert summary.expected_term_coverage is not None
    assert summary.expected_term_coverage > 0.0
    assert len(summary.case_results) == 2

    answer_case = next(item for item in summary.case_results if item.id == "answer-1")
    assert answer_case.question == "为什么不能只做向量检索？"
    assert answer_case.case_type == "rewrite"
    assert answer_case.tags == ("ai", "rewrite")
    assert answer_case.search_hit is True
    assert answer_case.rank == 1
    assert answer_case.evidence_hit is True
    assert answer_case.source_count_ok is True
    assert answer_case.top_location
    assert answer_case.expected_term_coverage is not None
    assert answer_case.expected_term_coverage > 0.0

    payload = summary.to_dict()
    assert payload["by_type"]["rewrite"]["total_cases"] == 1
    assert payload["by_type"]["abstain"]["total_cases"] == 1
    assert payload["by_tag"]["ai"]["recall_at_k"] == 1.0
    assert payload["by_tag"]["negative"]["abstain_accuracy"] == 1.0
