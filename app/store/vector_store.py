from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from app.vendors import VendorChromaError, clear_persistent_client_cache, get_persistent_client

from .contracts import StoreError, VectorChunk


def _sanitize_metadata(metadata: dict[str, object]) -> dict[str, object]:
    sanitized: dict[str, object] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            sanitized[key] = value
        elif isinstance(value, Path):
            sanitized[key] = str(value)
        else:
            sanitized[key] = json.dumps(value, ensure_ascii=False, default=str)
    return sanitized


class ChromaVectorStore:
    """Write-only Chroma wrapper with delayed dependency import."""

    def __init__(
        self,
        persist_directory: str | Path,
        *,
        collection_name: str = "chunks",
        collection_metadata: dict[str, object] | None = None,
        initialize: bool = True,
    ) -> None:
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.collection_metadata = collection_metadata or {"hnsw:space": "cosine"}
        self._client = None
        self._collection = None
        if initialize:
            self._ensure_collection()

    def _ensure_collection(self):
        if self._collection is not None:
            return self._collection

        if self._client is None:
            try:
                self._client = get_persistent_client(str(self.persist_directory))
            except VendorChromaError as exc:
                raise StoreError("chromadb is required for ChromaVectorStore but is not installed") from exc
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata=self.collection_metadata,
        )
        return self._collection

    @property
    def collection(self):
        return self._ensure_collection()

    def upsert(self, records: Sequence[VectorChunk]) -> None:
        if not records:
            return

        collection = self._ensure_collection()
        ids: list[str] = []
        documents: list[str] = []
        embeddings: list[list[float]] = []
        metadatas: list[dict[str, object]] = []

        for record in records:
            if record.embedding is None:
                raise StoreError(f"missing embedding for chunk {record.chunk_id}")
            ids.append(record.chunk_id)
            documents.append(record.content)
            embeddings.append([float(value) for value in record.embedding])

            metadata = dict(record.metadata)
            metadata.setdefault("chunk_id", record.chunk_id)
            metadata.setdefault("document_id", record.document_id)
            metadata.setdefault("file_path", record.file_path)
            metadata.setdefault("title_path", " / ".join(record.title_path))
            metadata.setdefault("title_path_json", json.dumps(list(record.title_path), ensure_ascii=False))
            metadatas.append(_sanitize_metadata(metadata))

        try:
            collection.upsert(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
            )
        except Exception as exc:  # pragma: no cover - depends on optional dependency
            raise StoreError("failed to upsert vectors into chroma") from exc

    def delete(self, chunk_ids: Sequence[str]) -> None:
        if not chunk_ids:
            return

        collection = self._ensure_collection()
        try:
            collection.delete(ids=list(chunk_ids))
        except Exception as exc:  # pragma: no cover - depends on optional dependency
            raise StoreError("failed to delete vectors from chroma") from exc

    def close(self, *, clear_client_cache: bool = False) -> None:
        self._collection = None
        if self._client is not None and clear_client_cache:
            clear_persistent_client_cache()
        self._client = None
