from __future__ import annotations

from pathlib import Path

from app.store import SQLiteMetadataStore, StoredChunk, StoredDocument
from eval.index_stats import compare_index_stats_payloads, snapshot_index_stats


def _write_store(path: Path, *, documents: list[StoredDocument], chunks: list[StoredChunk]) -> None:
    with SQLiteMetadataStore(path) as store:
        store.upsert_documents(documents)
        store.upsert_chunks(chunks)


def test_snapshot_index_stats_reports_duplicate_chunks_and_source_breakdown(tmp_path: Path):
    sqlite_path = tmp_path / "meta.db"
    _write_store(
        sqlite_path,
        documents=[
            StoredDocument(
                document_id="doc-1",
                content="doc1",
                file_path="notes/a.md",
                metadata={"source_id": "s1"},
            ),
            StoredDocument(
                document_id="doc-2",
                content="doc2",
                file_path="notes/b.md",
                metadata={"source_id": "s2"},
            ),
        ],
        chunks=[
            StoredChunk(
                chunk_id="c-1",
                document_id="doc-1",
                content="重复 内容",
                file_path="notes/a.md",
                chunk_index=0,
                token_count=2,
            ),
            StoredChunk(
                chunk_id="c-2",
                document_id="doc-1",
                content="重复   内容",
                file_path="notes/a.md",
                chunk_index=1,
                token_count=2,
            ),
            StoredChunk(
                chunk_id="c-3",
                document_id="doc-2",
                content="唯一内容",
                file_path="notes/b.md",
                chunk_index=0,
                token_count=1,
            ),
        ],
    )

    snapshot = snapshot_index_stats(sqlite_path)

    assert snapshot.document_count == 2
    assert snapshot.chunk_count == 3
    assert snapshot.exact_duplicate_groups == 1
    assert snapshot.exact_duplicate_chunk_count == 1
    assert snapshot.exact_duplicate_chunk_ratio == 0.3333
    assert snapshot.chunk_length_chars["count"] == 3
    assert snapshot.chunk_token_count["median"] == 2.0
    assert snapshot.chunks_per_document["max"] == 2
    assert snapshot.top_repeated_snippets[0].occurrences == 2
    assert snapshot.by_source[0].source_id == "s1"
    assert snapshot.by_source[0].chunk_count == 2


def test_compare_index_stats_payloads_reports_metric_deltas(tmp_path: Path):
    baseline_db = tmp_path / "baseline.db"
    candidate_db = tmp_path / "candidate.db"

    _write_store(
        baseline_db,
        documents=[StoredDocument(document_id="doc-1", content="doc", file_path="a.md", metadata={"source_id": "s1"})],
        chunks=[StoredChunk(chunk_id="c-1", document_id="doc-1", content="one", file_path="a.md", chunk_index=0, token_count=1)],
    )
    _write_store(
        candidate_db,
        documents=[StoredDocument(document_id="doc-1", content="doc", file_path="a.md", metadata={"source_id": "s1"})],
        chunks=[
            StoredChunk(chunk_id="c-1", document_id="doc-1", content="one", file_path="a.md", chunk_index=0, token_count=1),
            StoredChunk(chunk_id="c-2", document_id="doc-1", content="two", file_path="a.md", chunk_index=1, token_count=1),
        ],
    )

    diff = compare_index_stats_payloads(
        snapshot_index_stats(baseline_db).to_dict(),
        snapshot_index_stats(candidate_db).to_dict(),
    )

    assert diff["document_count"]["delta"] == 0.0
    assert diff["chunk_count"]["delta"] == 1.0
    assert diff["chunks_per_document"]["max"]["candidate"] == 2.0
    assert diff["by_source"]["s1"]["chunk_count"]["delta"] == 1.0
