from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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


def _build_indexed_client(tmp_path: Path) -> TestClient:
    source_dir = tmp_path / "notes"
    source_dir.mkdir()
    (source_dir / "rag.md").write_text(
        "# RAG\n\n"
        "混合检索结合了词法与语义检索的优势。只做向量检索会漏掉精确匹配场景。",
        encoding="utf-8",
    )
    config = _build_config(tmp_path, source_dir)
    IndexingService(config).index("full")
    return TestClient(create_app(config))


def test_empty_index_search_and_ask_are_safe(tmp_path: Path):
    source_dir = tmp_path / "notes"
    source_dir.mkdir()
    client = TestClient(create_app(_build_config(tmp_path, source_dir)))

    search_response = client.post("/search", json={"queries": ["不存在的问题"]})
    ask_response = client.post("/ask", json={"question": "不存在的问题", "queries": ["不存在的问题"]})

    assert search_response.status_code == 200
    assert search_response.json()["results"] == []
    assert ask_response.status_code == 200
    assert ask_response.json()["abstained"] is True


def test_search_supports_large_top_k_without_failing(tmp_path: Path):
    client = _build_indexed_client(tmp_path)

    response = client.post(
        "/search",
        json={
            "queries": ["混合检索 优势"],
            "recall_top_k": 100,
            "rerank_top_k": 100,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["debug"]["recall_count"] >= len(payload["results"])


def test_search_ask_verify_return_500_when_service_raises(tmp_path: Path):
    source_dir = tmp_path / "notes"
    source_dir.mkdir()
    app = create_app(_build_config(tmp_path, source_dir))

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    app.state.query_service.search = _boom
    app.state.query_service.ask = _boom
    app.state.query_service.verify = _boom

    client = TestClient(app)

    search = client.post("/search", json={"queries": ["x"]})
    ask = client.post("/ask", json={"question": "x", "queries": ["x"]})
    verify = client.post("/verify", json={"answer": "x [c1]", "used_chunk_ids": ["c1"]})

    assert search.status_code == 500
    assert search.json()["detail"] == "boom"
    assert ask.status_code == 500
    assert verify.status_code == 500


def test_parallel_search_and_ask_requests_are_served(tmp_path: Path):
    client = _build_indexed_client(tmp_path)

    def _search():
        return client.post("/search", json={"queries": ["混合检索 优势", "向量检索"]}).status_code

    def _ask():
        return client.post(
            "/ask",
            json={"question": "为什么不能只做向量检索？", "queries": ["为什么不能只做向量检索？", "混合检索 优势"]},
        ).status_code

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(_search if index % 2 == 0 else _ask) for index in range(12)]
        statuses = [future.result() for future in futures]

    assert statuses
    assert all(status == 200 for status in statuses)
