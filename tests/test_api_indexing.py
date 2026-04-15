from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import AppConfig, ChunkerConfig, DataConfig, ModelConfig, SourceConfig
from app.main import create_app


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
    )


def test_index_and_stats_endpoints(tmp_path: Path):
    source_dir = tmp_path / "notes"
    source_dir.mkdir()
    (source_dir / "sample.md").write_text("# 标题\n\n接口测试内容。", encoding="utf-8")

    client = TestClient(create_app(_build_config(tmp_path, source_dir)))

    index_response = client.post("/index", json={"mode": "full"})
    assert index_response.status_code == 200
    assert index_response.json()["indexed_documents"] == 1

    stats_response = client.get("/stats")
    assert stats_response.status_code == 200
    payload = stats_response.json()
    assert payload["document_count"] == 1
    assert payload["chunk_count"] >= 1


def test_index_endpoint_invalidates_query_cache(tmp_path: Path):
    source_dir = tmp_path / "notes"
    source_dir.mkdir()
    (source_dir / "sample.md").write_text("# 标题\n\n接口测试内容。", encoding="utf-8")

    app = create_app(_build_config(tmp_path, source_dir))
    called = {"count": 0}

    def _invalidate_cache():
        called["count"] += 1

    app.state.query_service.invalidate_cache = _invalidate_cache
    client = TestClient(app)

    response = client.post("/index", json={"mode": "full"})
    assert response.status_code == 200
    assert called["count"] == 1
