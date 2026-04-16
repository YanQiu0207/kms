from __future__ import annotations

from app.config import CleaningConfig
from app.ingest.cleaner import MarkdownCleaner
from app.ingest.contracts import MarkdownChunk, MarkdownDocument


def _build_document(text: str) -> MarkdownDocument:
    return MarkdownDocument(
        source_id="source-1",
        source_root="E:/notes",
        document_id="doc-1",
        file_path="E:/notes/doc.md",
        relative_path="doc.md",
        file_hash="hash-1",
        mtime_ns=1,
        size=len(text.encode("utf-8")),
        text=text,
    )


def test_cleaner_extracts_front_matter_and_normalizes_trailing_spaces():
    cleaner = MarkdownCleaner(
        CleaningConfig(
            enabled=True,
            extract_front_matter=True,
            drop_front_matter_from_content=True,
            normalize_whitespace=True,
            drop_toc_markers=True,
            drop_low_value_placeholders=True,
            normalize_markdown_tables=True,
            dedupe_exact_chunks=True,
        )
    )

    document = cleaner.clean_document(
        _build_document(
            "---\n"
            "title: Example\n"
            "tags:\n"
            "  - rag\n"
            "---\n"
            "# 标题   \n\n"
            "正文内容。   \n"
        )
    )

    assert document.metadata["front_matter"]["title"] == "Example"
    assert document.metadata["cleaning"]["front_matter_extracted"] is True
    assert document.metadata["cleaning"]["whitespace_normalized"] is True
    assert "---" not in document.text
    assert document.text.rstrip("\n").endswith("正文内容。")


def test_cleaner_dedupes_exact_duplicate_chunks_and_marks_kept_chunk():
    cleaner = MarkdownCleaner(
        CleaningConfig(
            enabled=True,
            extract_front_matter=True,
            drop_front_matter_from_content=True,
            normalize_whitespace=True,
            drop_toc_markers=True,
            drop_low_value_placeholders=True,
            normalize_markdown_tables=True,
            dedupe_exact_chunks=True,
        )
    )
    document = cleaner.clean_document(_build_document("# 标题\n\n正文"))
    chunks = (
        MarkdownChunk(
            chunk_id="c1",
            document_id=document.document_id,
            file_path=document.file_path,
            file_hash=document.file_hash,
            chunk_index=0,
            text="重复 内容",
        ),
        MarkdownChunk(
            chunk_id="c2",
            document_id=document.document_id,
            file_path=document.file_path,
            file_hash=document.file_hash,
            chunk_index=1,
            text="重复   内容",
        ),
    )

    deduped = cleaner.dedupe_exact_chunks(document, chunks)

    assert len(deduped) == 1
    assert deduped[0].metadata["exact_duplicate_group_size"] == 2
    assert document.metadata["cleaning"]["dropped_exact_duplicate_chunks"] == 1


def test_cleaner_drops_standalone_toc_and_placeholder_lines():
    cleaner = MarkdownCleaner(
        CleaningConfig(
            enabled=True,
            extract_front_matter=True,
            drop_front_matter_from_content=True,
            normalize_whitespace=True,
            drop_toc_markers=True,
            drop_low_value_placeholders=True,
            normalize_markdown_tables=True,
            dedupe_exact_chunks=True,
        )
    )

    document = cleaner.clean_document(
        _build_document(
            "# 标题\n"
            "[TOC]\n"
            "\n"
            "正文内容\n"
            "待续\n"
            "TODO\n"
            "还有结论\n"
        )
    )

    assert "[TOC]" not in document.text
    assert "待续" not in document.text
    assert "TODO" not in document.text
    assert "正文内容" in document.text
    assert "还有结论" in document.text
    assert document.metadata["cleaning"]["toc_markers_removed"] == 1
    assert document.metadata["cleaning"]["low_value_placeholders_removed"] == 2


def test_cleaner_normalizes_markdown_tables_into_stable_row_text():
    cleaner = MarkdownCleaner(
        CleaningConfig(
            enabled=True,
            extract_front_matter=True,
            drop_front_matter_from_content=True,
            normalize_whitespace=True,
            drop_toc_markers=True,
            drop_low_value_placeholders=True,
            normalize_markdown_tables=True,
            dedupe_exact_chunks=True,
        )
    )

    document = cleaner.clean_document(
        _build_document(
            "# 表格\n\n"
            "| 文件类型 | 类型参数 |\n"
            "| ---- | ---- |\n"
            "| 普通文件 | f |\n"
            "| 目录 | d |\n"
        )
    )

    assert "表格列: 文件类型 | 类型参数" in document.text
    assert "表格行: 文件类型是 普通文件；类型参数是 f" in document.text
    assert "表格行: 文件类型是 目录；类型参数是 d" in document.text
    assert "| 文件类型 | 类型参数 |" not in document.text
    assert document.metadata["cleaning"]["tables_normalized"] == 1
    assert document.metadata["cleaning"]["normalized_table_rows"] == 2


def test_cleaner_applies_source_specific_rules():
    cleaner = MarkdownCleaner(
        CleaningConfig(
            enabled=True,
            extract_front_matter=True,
            drop_front_matter_from_content=True,
            normalize_whitespace=True,
            drop_toc_markers=True,
            drop_low_value_placeholders=True,
            normalize_markdown_tables=True,
            dedupe_exact_chunks=True,
            source_rules=[
                {
                    "id": "drop-edit-footer",
                    "path_globs": ["第三方软件/brpc/作者/*.md"],
                    "drop_line_patterns": [r"^\[编辑于\s+\d{4}-\d{2}-\d{2}.*\)$"],
                },
                {
                    "id": "drop-reference-tail",
                    "path_globs": ["snmp/*.md"],
                    "drop_trailing_heading_titles": ["参考链接"],
                },
            ],
        )
    )

    author_document = MarkdownDocument(
        source_id="source-1",
        source_root="E:/notes",
        document_id="doc-author",
        file_path="E:/notes/第三方软件/brpc/作者/戈君.md",
        relative_path="第三方软件/brpc/作者/戈君.md",
        file_hash="hash-author",
        mtime_ns=1,
        size=0,
        text="# 标题\n\n正文\n\n[编辑于 2017-09-20](https://example.com)\n",
    )
    cleaned_author = cleaner.clean_document(author_document)
    assert "[编辑于" not in cleaned_author.text
    assert "drop-edit-footer" in cleaned_author.metadata["cleaning"]["source_rules_applied"]
    assert cleaned_author.metadata["cleaning"]["source_rule_dropped_lines"] == 1

    reference_document = MarkdownDocument(
        source_id="source-1",
        source_root="E:/notes",
        document_id="doc-ref",
        file_path="E:/notes/snmp/3.0 snmp使用v3协议.md",
        relative_path="snmp/3.0 snmp使用v3协议.md",
        file_hash="hash-ref",
        mtime_ns=1,
        size=0,
        text="# 标题\n\n正文\n\n## 参考链接\n\n- https://example.com\n",
    )
    cleaned_reference = cleaner.clean_document(reference_document)
    assert "## 参考链接" not in cleaned_reference.text
    assert "drop-reference-tail" in cleaned_reference.metadata["cleaning"]["source_rules_applied"]
    assert cleaned_reference.metadata["cleaning"]["source_rule_dropped_sections"] == 1
