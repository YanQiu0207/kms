from __future__ import annotations

from app.store.contracts import VectorChunk
from app.store.vector_store import ChromaVectorStore


class _FakeCollection:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def upsert(self, *, ids, documents, embeddings, metadatas) -> None:
        self.calls.append(
            {
                "ids": list(ids),
                "documents": list(documents),
                "embeddings": list(embeddings),
                "metadatas": list(metadatas),
            }
        )


class _FakeClient:
    def get_max_batch_size(self) -> int:
        return 2


def _make_chunk(index: int) -> VectorChunk:
    return VectorChunk(
        chunk_id=f"chunk-{index}",
        document_id="doc-1",
        content=f"content-{index}",
        embedding=[float(index)],
        file_path="E:/work/blog/example.md",
        title_path=("Root",),
        metadata={"chunk_index": index},
    )


def test_vector_store_upsert_batches_by_client_limit(tmp_path):
    store = ChromaVectorStore(tmp_path, initialize=False)
    store._client = _FakeClient()
    store._collection = _FakeCollection()

    store.upsert([_make_chunk(1), _make_chunk(2), _make_chunk(3)])

    assert len(store._collection.calls) == 2
    assert store._collection.calls[0]["ids"] == ["chunk-1", "chunk-2"]
    assert store._collection.calls[1]["ids"] == ["chunk-3"]
