from __future__ import annotations

from app.config import AppConfig, DataConfig
from app.store import SQLiteMetadataStore, StoredChunk, StoredDocument
from eval.source_audit import snapshot_source_audit


def test_snapshot_source_audit_summarizes_sources_and_front_matter(tmp_path):
    sqlite_path = tmp_path / "meta.db"
    with SQLiteMetadataStore(sqlite_path) as store:
        store.upsert_documents(
            [
                StoredDocument(
                    document_id="doc-1",
                    content="doc one",
                    file_path="E:/notes/程序设计/对象池.md",
                    metadata={
                        "source_id": "notes",
                        "relative_path": "程序设计/对象池.md",
                        "front_matter_category": "程序设计",
                        "front_matter_tags": ["对象池"],
                    },
                ),
                StoredDocument(
                    document_id="doc-2",
                    content="doc two",
                    file_path="E:/work/blog/ai/guide.md",
                    metadata={
                        "source_id": "blog",
                        "relative_path": "ai/guide.md",
                        "front_matter_aliases": ["guide"],
                    },
                ),
            ]
        )
        store.upsert_chunks(
            [
                StoredChunk(
                    chunk_id="c1",
                    document_id="doc-1",
                    content="chunk one",
                    file_path="E:/notes/程序设计/对象池.md",
                    metadata={"source_id": "notes", "relative_path": "程序设计/对象池.md"},
                ),
                StoredChunk(
                    chunk_id="c2",
                    document_id="doc-2",
                    content="chunk two",
                    file_path="E:/work/blog/ai/guide.md",
                    metadata={"source_id": "blog", "relative_path": "ai/guide.md"},
                ),
            ]
        )

    snapshot = snapshot_source_audit(AppConfig(data=DataConfig(sqlite=str(sqlite_path))))

    assert snapshot.document_count == 2
    assert snapshot.chunk_count == 2
    assert snapshot.front_matter_docs == 2
    assert snapshot.category_docs == 1
    assert snapshot.tag_docs == 1
    assert snapshot.alias_docs == 1
    assert snapshot.by_source_id[0].name == "blog"
    assert snapshot.by_source_id[1].name == "notes"
    assert snapshot.by_top_level_path[0].name in {"程序设计", "ai"}
