from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import AppConfig, ChunkerConfig, DataConfig, ModelConfig, RetrievalConfig, SourceConfig
from app.main import create_app
from app.services import IndexingService


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


def test_search_ask_verify_endpoints(tmp_path: Path):
    source_dir = tmp_path / "notes"
    source_dir.mkdir()
    (source_dir / "rag.md").write_text(
        "# RAG\n\n"
        "混合检索结合了词法与语义检索的优势。它把精确匹配和语义召回结合起来，"
        "在个人知识库场景里可以覆盖标题词命中、术语命中和近义表达检索。"
        "当用户问题里包含原文关键词时，词法检索能稳定召回；当用户换一种表达方式提问时，"
        "语义检索又能补足相关片段，因此整体更稳。\n\n"
        "## 限制\n\n"
        "只做向量检索会漏掉精确匹配场景，尤其是缩写、命令、错误码、专有名词、配置键名。"
        "这些内容往往要求字面匹配，如果只依赖语义相似度，相关片段可能被排到后面，"
        "甚至完全召回不到，所以个人知识库不能只做向量检索。",
        encoding="utf-8",
    )

    config = _build_config(tmp_path, source_dir)
    IndexingService(config).index("full")
    client = TestClient(create_app(config))

    search_response = client.post(
        "/search",
        json={
            "queries": ["为什么个人知识库不能只做向量检索？", "混合检索 优势"],
            "recall_top_k": 6,
            "rerank_top_k": 3,
        },
    )
    assert search_response.status_code == 200
    search_payload = search_response.json()
    assert len(search_payload["results"]) >= 1
    assert search_payload["debug"]["queries_count"] == 2
    assert "location" in search_payload["results"][0]

    ask_response = client.post(
        "/ask",
        json={
            "question": "为什么个人知识库不能只做向量检索？",
            "queries": ["为什么个人知识库不能只做向量检索？", "混合检索 优势"],
            "rerank_top_k": 3,
        },
    )
    assert ask_response.status_code == 200
    ask_payload = ask_response.json()
    assert ask_payload["abstained"] is False
    assert ask_payload["prompt"]
    assert len(ask_payload["sources"]) >= 1
    assert ask_payload["sources"][0]["ref_index"] == 1
    assert "location" in ask_payload["sources"][0]

    first_chunk_id = ask_payload["sources"][0]["chunk_id"]
    verify_response = client.post(
        "/verify",
        json={
            "answer": f"混合检索结合了词法与语义检索的优势 [{first_chunk_id}]。",
            "used_chunk_ids": [first_chunk_id],
        },
    )
    assert verify_response.status_code == 200
    verify_payload = verify_response.json()
    assert verify_payload["coverage"] >= 0.0
    assert len(verify_payload["details"]) == 1


def test_ask_endpoint_abstains_when_evidence_is_too_short(tmp_path: Path):
    source_dir = tmp_path / "notes"
    source_dir.mkdir()
    (source_dir / "short.md").write_text("# 短文\n\n信息太短。", encoding="utf-8")

    config = _build_config(tmp_path, source_dir)
    config.abstain.top1_min = 0.0
    config.abstain.top3_avg_min = 0.0
    config.abstain.min_hits = 1
    IndexingService(config).index("full")
    client = TestClient(create_app(config))

    response = client.post(
        "/ask",
        json={
            "question": "这篇文档说了什么？",
            "queries": ["这篇文档说了什么？"],
            "rerank_top_k": 2,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["abstained"] is True
    assert payload["abstain_reason"] == "evidence_chars_below_threshold"
    assert payload["prompt"] == ""


def test_search_endpoint_rejects_negative_top_k(tmp_path: Path):
    source_dir = tmp_path / "notes"
    source_dir.mkdir()
    (source_dir / "sample.md").write_text("# 标题\n\n内容足够。", encoding="utf-8")

    config = _build_config(tmp_path, source_dir)
    IndexingService(config).index("full")
    client = TestClient(create_app(config))

    response = client.post(
        "/search",
        json={
            "queries": ["测试"],
            "recall_top_k": -1,
            "rerank_top_k": -2,
        },
    )

    assert response.status_code == 422
