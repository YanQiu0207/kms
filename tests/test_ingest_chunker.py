from __future__ import annotations

from app.ingest import MarkdownChunk, MarkdownChunker, MarkdownSection, build_contextual_chunk_text, build_chunk_id


def test_build_chunk_id_includes_section_index():
    left = build_chunk_id(
        document_id="doc-1",
        title_path=("same",),
        section_index=0,
        chunk_index=0,
        text="hello",
    )
    right = build_chunk_id(
        document_id="doc-1",
        title_path=("same",),
        section_index=1,
        chunk_index=0,
        text="hello",
    )

    assert left != right


def test_markdown_chunker_keeps_duplicate_sections_distinguishable():
    chunker = MarkdownChunker(chunk_size=200, chunk_overlap=20, chunker_version="test", embedding_model="mock")
    section_a = MarkdownSection(
        document_id="doc-1",
        file_path="E:/notes/sample.md",
        file_hash="hash",
        title_path=("same",),
        section_index=0,
        start_line=1,
        end_line=2,
        text="重复内容",
    )
    section_b = MarkdownSection(
        document_id="doc-1",
        file_path="E:/notes/sample.md",
        file_hash="hash",
        title_path=("same",),
        section_index=1,
        start_line=4,
        end_line=5,
        text="重复内容",
    )

    first = chunker.chunk(section_a)
    second = chunker.chunk(section_b)

    assert len(first) == 1
    assert len(second) == 1
    assert first[0].chunk_id != second[0].chunk_id


def test_build_contextual_chunk_text_prefixes_document_context_without_mutating_body():
    chunk = MarkdownChunk(
        chunk_id="chunk-1",
        document_id="doc-1",
        file_path="E:/notes/distributed/raft.md",
        file_hash="hash",
        title_path=("Raft", "Leader Election"),
        text="Leader 会通过心跳维持租约。",
        metadata={
            "relative_path": "distributed/raft.md",
            "front_matter_title": "Raft 学习笔记",
        },
    )

    contextual = build_contextual_chunk_text(chunk)

    assert "文档标题: Raft 学习笔记" in contextual
    assert "文档路径: distributed/raft.md" in contextual
    assert "章节路径: Raft / Leader Election" in contextual
    assert contextual.endswith("Leader 会通过心跳维持租约。")
    assert chunk.text == "Leader 会通过心跳维持租约。"
