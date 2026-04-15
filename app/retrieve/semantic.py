from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

from app.observability import get_logger, timed_operation
from app.vendors import VendorChromaError, clear_persistent_client_cache, get_persistent_client

from .contracts import RetrievedChunk, RetrievalError

LOGGER = get_logger("kms.semantic")


class EmbeddingEncoder(Protocol):
    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


def _debug_hash_embedding(text: str, *, dimensions: int = 32) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    while len(values) < dimensions:
        for byte in digest:
            values.append((byte / 255.0) * 2.0 - 1.0)
            if len(values) >= dimensions:
                break
        digest = hashlib.sha256(digest).digest()
    return values


class DebugEmbeddingEncoder:
    """Deterministic embedding fallback for tests and offline runs."""

    def __init__(self, *, dimensions: int = 32) -> None:
        self.dimensions = dimensions

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [_debug_hash_embedding(text, dimensions=self.dimensions) for text in texts]

    def close(self) -> None:
        return None


def build_embedding_encoder(
    model_name: str,
    *,
    device: str = "cpu",
    dtype: str = "float32",
    batch_size: int = 8,
    hf_cache: str | Path | None = None,
) -> EmbeddingEncoder:
    model_name = (model_name or "").strip()
    if not model_name or model_name.startswith("debug-"):
        return DebugEmbeddingEncoder()

    from app.services.embeddings import EmbeddingService

    return EmbeddingService(
        model_name,
        device=device,
        dtype=dtype,
        batch_size=batch_size,
        hf_cache=hf_cache,
    )


def _parse_title_path(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    if isinstance(value, str) and value.strip():
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError:
                raw = None
            else:
                if isinstance(raw, list):
                    return tuple(str(item) for item in raw)
        return tuple(segment.strip() for segment in value.split(" / ") if segment.strip())
    return ()


def _safe_text(value: object) -> str:
    return "" if value is None else str(value)


@dataclass(slots=True)
class SemanticRetriever:
    """Chroma-backed semantic retriever with delayed dependency loading."""

    persist_directory: str | Path | None
    collection_name: str = "chunks"
    embedder: EmbeddingEncoder | None = None
    collection: object | None = None
    initialize: bool = True
    _client: object | None = field(init=False, repr=False, default=None)
    _collection: object | None = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        if self.embedder is None:
            self.embedder = DebugEmbeddingEncoder()
        self._client = None
        self._collection = self.collection
        if initialize := self.initialize:
            if initialize and self._collection is None and self.persist_directory is not None:
                self._ensure_collection()

    def _ensure_collection(self):
        if self._collection is not None:
            return self._collection

        if self.persist_directory is None:
            raise RetrievalError("semantic retriever requires a Chroma collection")

        if self._client is None:
            with timed_operation(LOGGER, "semantic.client_load", persist_directory=str(self.persist_directory)):
                try:
                    self._client = get_persistent_client(str(Path(self.persist_directory)))
                except VendorChromaError as exc:
                    raise RetrievalError("chromadb is required for semantic retrieval") from exc
        self._collection = self._client.get_or_create_collection(name=self.collection_name)
        return self._collection

    @property
    def collection_handle(self):
        return self._ensure_collection()

    def search(self, query: str, limit: int = 5) -> Sequence[RetrievedChunk]:
        query = query.strip()
        limit = max(0, int(limit))
        if not query or limit <= 0:
            return ()

        with timed_operation(LOGGER, "semantic.search", query=query, limit=limit):
            collection = self._ensure_collection()
            embedding = self.embedder.embed_texts([query])[0]
            try:
                raw = collection.query(
                    query_embeddings=[embedding],
                    n_results=limit,
                    include=["documents", "metadatas", "distances"],
                )
            except Exception as exc:  # pragma: no cover - depends on optional dependency
                raise RetrievalError("semantic retrieval failed") from exc

        return self._build_results(raw, query_index=0)

    def search_many(self, queries: Sequence[str], limit: int = 5) -> tuple[tuple[RetrievedChunk, ...], ...]:
        cleaned_queries = tuple(query.strip() for query in queries if query and query.strip())
        limit = max(0, int(limit))
        if not cleaned_queries or limit <= 0:
            return ()

        with timed_operation(LOGGER, "semantic.search_many", query_count=len(cleaned_queries), limit=limit):
            collection = self._ensure_collection()
            embeddings = self.embedder.embed_texts(cleaned_queries)
            try:
                raw = collection.query(
                    query_embeddings=embeddings,
                    n_results=limit,
                    include=["documents", "metadatas", "distances"],
                )
            except Exception as exc:  # pragma: no cover - depends on optional dependency
                raise RetrievalError("semantic retrieval failed") from exc

        return tuple(self._build_results(raw, query_index=index) for index in range(len(cleaned_queries)))

    def close(self) -> None:
        with timed_operation(LOGGER, "semantic.close", collection_name=self.collection_name):
            self.collection = None
            self._collection = None
            if self._client is not None:
                clear_persistent_client_cache()
            self._client = None

    @staticmethod
    def _unpack_batch(value: object, *, query_index: int) -> list[object]:
        if value is None:
            return []
        if isinstance(value, list):
            if value and isinstance(value[0], list):
                if query_index >= len(value) or not isinstance(value[query_index], list):
                    return []
                return list(value[query_index])
            if query_index == 0:
                return list(value)
            return []
        if query_index == 0:
            return [value]
        return []

    def _build_results(self, raw: dict[str, object], *, query_index: int) -> tuple[RetrievedChunk, ...]:
        ids = self._unpack_batch(raw.get("ids"), query_index=query_index)
        documents = self._unpack_batch(raw.get("documents"), query_index=query_index)
        metadatas = self._unpack_batch(raw.get("metadatas"), query_index=query_index)
        distances = self._unpack_batch(raw.get("distances"), query_index=query_index)

        results: list[RetrievedChunk] = []
        for index, chunk_id in enumerate(ids, start=1):
            metadata = dict(metadatas[index - 1]) if index - 1 < len(metadatas) and isinstance(metadatas[index - 1], dict) else {}
            distance = distances[index - 1] if index - 1 < len(distances) else None
            distance_value = float(distance) if isinstance(distance, (int, float)) else 0.0
            metadata["semantic_rank"] = index
            metadata["semantic_distance"] = distance_value
            metadata["semantic_score"] = 1.0 / (1.0 + max(0.0, distance_value))
            document_id = str(metadata.get("document_id") or metadata.get("doc_id") or chunk_id)
            file_path = _safe_text(metadata.get("file_path"))
            title_path = _parse_title_path(metadata.get("title_path_json") or metadata.get("title_path"))
            score = 1.0 / (1.0 + max(0.0, distance_value))
            content = _safe_text(documents[index - 1]) if index - 1 < len(documents) else ""
            results.append(
                RetrievedChunk(
                    document_id=document_id,
                    content=content,
                    chunk_id=str(chunk_id),
                    file_path=file_path,
                    title_path=title_path,
                    score=score,
                    metadata=metadata,
                )
            )
        return tuple(results)
