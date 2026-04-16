from __future__ import annotations

from pathlib import Path

from app.config import AppConfig, ChunkerConfig, CleaningConfig, DataConfig, ModelConfig, SourceConfig
from app.ingest import MarkdownChunk, MarkdownDocument, MarkdownIngestLoader, SourceSpec
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
        cleaning=CleaningConfig(
            enabled=True,
            extract_front_matter=True,
            drop_front_matter_from_content=True,
            normalize_whitespace=True,
            dedupe_exact_chunks=True,
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


def test_indexing_extracts_front_matter_and_drops_it_from_chunk_content(tmp_path: Path):
    source_dir = tmp_path / "notes"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text(
        "---\n"
        "title: Alpha Title\n"
        "tags:\n"
        "  - rag\n"
        "  - retrieval\n"
        "---\n"
        "# 标题\n\n"
        "正文内容。\n",
        encoding="utf-8",
    )

    config = _build_config(tmp_path, source_dir)
    IndexingService(config).index("full")

    store = SQLiteMetadataStore(config.data.sqlite)
    documents = list(store.iter_documents())
    chunks = list(store.iter_chunks())
    store.close()

    assert len(documents) == 1
    assert documents[0].metadata["front_matter"]["title"] == "Alpha Title"
    assert documents[0].metadata["front_matter"]["tags"] == ["rag", "retrieval"]
    assert documents[0].metadata["cleaning"]["front_matter_extracted"] is True
    assert "---" not in chunks[0].content
    assert "Alpha Title" not in chunks[0].content
    assert "正文内容" in chunks[0].content
    assert chunks[0].metadata["front_matter_title"] == "Alpha Title"
    assert chunks[0].metadata["front_matter_tags"] == ["rag", "retrieval"]
    assert chunks[0].metadata["relative_path"] == "alpha.md"


def test_indexing_dedupes_exact_duplicate_chunks_within_document(tmp_path: Path):
    source_dir = tmp_path / "notes"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text(
        "# 标题\n\n"
        "重复内容。\n\n"
        "# 标题\n\n"
        "重复内容。\n",
        encoding="utf-8",
    )

    config = _build_config(tmp_path, source_dir)
    control_config = config.model_copy(deep=True)
    control_config.cleaning.dedupe_exact_chunks = False

    control_loader = MarkdownIngestLoader(
        (SourceSpec(path=str(source_dir), excludes=tuple()),),
        chunk_size=control_config.chunker.chunk_size,
        chunk_overlap=control_config.chunker.chunk_overlap,
        chunker_version=control_config.chunker.version,
        embedding_model=control_config.models.embedding,
        cleaning=control_config.cleaning,
    )
    dedupe_loader = MarkdownIngestLoader(
        (SourceSpec(path=str(source_dir), excludes=tuple()),),
        chunk_size=config.chunker.chunk_size,
        chunk_overlap=config.chunker.chunk_overlap,
        chunker_version=config.chunker.version,
        embedding_model=config.models.embedding,
        cleaning=config.cleaning,
    )

    control_document = next(control_loader.iter_documents())
    dedupe_document = next(dedupe_loader.iter_documents())
    control_chunks = control_loader.iter_chunks(control_document)
    dedupe_chunks = dedupe_loader.iter_chunks(dedupe_document)

    assert len(dedupe_chunks) < len(control_chunks)
    assert any(chunk.metadata.get("exact_duplicate_group_size") == 2 for chunk in dedupe_chunks)
    assert dedupe_document.metadata["cleaning"]["dropped_exact_duplicate_chunks"] == 1


class _RecordingMetadataStore:
    def upsert_documents(self, records):
        self.documents = list(records)

    def upsert_chunks(self, records):
        self.chunks = list(records)


class _RecordingFtsWriter:
    def upsert_chunks(self, records):
        self.chunks = list(records)


class _RecordingVectorStore:
    def __init__(self) -> None:
        self.records = []

    def upsert(self, records):
        self.records = list(records)


class _RecordingEmbedder:
    def __init__(self) -> None:
        self.calls = []

    def embed_texts(self, texts):
        payload = list(texts)
        self.calls.append(payload)
        return [[0.1, 0.2, 0.3] for _ in payload]


def test_indexing_uses_contextual_embedding_text_but_keeps_vector_document_content_original(tmp_path: Path):
    source_dir = tmp_path / "notes"
    source_dir.mkdir()
    config = _build_config(tmp_path, source_dir)
    service = IndexingService(config)
    metadata_store = _RecordingMetadataStore()
    fts_writer = _RecordingFtsWriter()
    vector_store = _RecordingVectorStore()
    embedder = _RecordingEmbedder()
    document = MarkdownDocument(
        source_id="src",
        source_root=str(source_dir),
        document_id="doc-1",
        file_path=str(source_dir / "raft.md"),
        relative_path="distributed/raft.md",
        file_hash="hash",
        mtime_ns=1,
        size=1,
        text="Leader 会通过心跳维持租约。",
        metadata={},
    )
    chunk = MarkdownChunk(
        chunk_id="chunk-1",
        document_id="doc-1",
        file_path=str(source_dir / "raft.md"),
        file_hash="hash",
        title_path=("Raft", "Leader Election"),
        section_index=1,
        chunk_index=0,
        start_line=10,
        end_line=12,
        text="Leader 会通过心跳维持租约。",
        metadata={
            "relative_path": "distributed/raft.md",
            "front_matter_title": "Raft 学习笔记",
        },
    )

    service._persist_batch(
        metadata_store=metadata_store,
        fts_writer=fts_writer,
        vector_store=vector_store,
        embedder=embedder,
        documents=[document],
        chunks=[chunk],
    )

    assert len(embedder.calls) == 1
    assert "文档标题: Raft 学习笔记" in embedder.calls[0][0]
    assert "章节路径: Raft / Leader Election" in embedder.calls[0][0]
    assert vector_store.records[0].content == "Leader 会通过心跳维持租约。"
