from __future__ import annotations

from pathlib import Path

from app.config import AppConfig, ChunkerConfig, DataConfig, ModelConfig, SourceConfig
from app.services import IndexingService
from app.store import SQLiteMetadataStore


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


def test_full_index_populates_sqlite_and_stats(tmp_path: Path):
    source_dir = tmp_path / "notes"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# 标题\n\n第一段内容。\n\n第二段内容。", encoding="utf-8")
    (source_dir / "beta.md").write_text("## 小节\n\n这里有另一篇文档。", encoding="utf-8")

    config = _build_config(tmp_path, source_dir)
    summary = IndexingService(config).index("full")

    assert summary.mode == "full"
    assert summary.indexed_documents == 2
    assert summary.indexed_chunks >= 2

    store = SQLiteMetadataStore(config.data.sqlite)
    stats = store.stats()
    store.close()

    assert stats.document_count == 2
    assert stats.chunk_count == summary.indexed_chunks


def test_incremental_index_handles_modify_and_remove(tmp_path: Path):
    source_dir = tmp_path / "notes"
    source_dir.mkdir()
    alpha = source_dir / "alpha.md"
    beta = source_dir / "beta.md"
    alpha.write_text("# 标题\n\n原始内容。", encoding="utf-8")
    beta.write_text("# 保留\n\n这篇会被删除。", encoding="utf-8")

    config = _build_config(tmp_path, source_dir)
    IndexingService(config).index("full")

    alpha.write_text("# 标题\n\n更新后的内容，增加更多文字。", encoding="utf-8")
    beta.unlink()

    summary = IndexingService(config).index("incremental")

    assert summary.mode == "incremental"
    assert summary.indexed_documents == 1
    assert summary.deleted_documents == 1
