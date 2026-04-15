"""M1 索引服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import threading
from typing import Iterable, Sequence

from app.config import AppConfig
from app.ingest import FileState, IngestError, MarkdownChunk, MarkdownDocument, MarkdownIngestLoader, SourceSpec
from app.observability import get_logger, timed_operation
from app.services.embeddings import EmbeddingService
from app.store import (
    ChromaVectorStore,
    FTS5Writer,
    IngestLogEntry,
    SQLiteMetadataStore,
    StoredChunk,
    StoredDocument,
    VectorChunk,
)

LOGGER = get_logger("kms.index")


@dataclass(slots=True)
class IndexingSummary:
    mode: str
    indexed_documents: int = 0
    indexed_chunks: int = 0
    skipped_documents: int = 0
    deleted_documents: int = 0
    message: str = ""


def _document_metadata(document: MarkdownDocument) -> dict[str, object]:
    return {
        "source_id": document.source_id,
        "source_root": document.source_root,
        "relative_path": document.relative_path,
        "file_hash": document.file_hash,
        "mtime_ns": document.mtime_ns,
        "size": document.size,
        "encoding": document.encoding,
    }


def _to_stored_document(document: MarkdownDocument) -> StoredDocument:
    return StoredDocument(
        document_id=document.document_id,
        content=document.text,
        file_path=document.file_path,
        source_path=document.source_root,
        file_hash=document.file_hash,
        updated_at=datetime.now(UTC),
        metadata=_document_metadata(document),
    )


def _to_stored_chunk(chunk: MarkdownChunk, *, stored_chunk_index: int) -> StoredChunk:
    return StoredChunk(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        content=chunk.text,
        file_path=chunk.file_path,
        chunk_index=stored_chunk_index,
        title_path=chunk.title_path,
        token_count=chunk.token_count,
        file_hash=chunk.file_hash,
        chunker_version=chunk.chunker_version,
        embedding_model=chunk.embedding_model,
        updated_at=datetime.now(UTC),
        metadata={
            "section_index": chunk.section_index,
            "file_hash": chunk.file_hash,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
        },
    )


def _to_vector_chunks(chunks: Sequence[MarkdownChunk], embeddings: Sequence[Sequence[float]]) -> list[VectorChunk]:
    vector_chunks: list[VectorChunk] = []
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        vector_chunks.append(
            VectorChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                content=chunk.text,
                embedding=embedding,
                file_path=chunk.file_path,
                title_path=chunk.title_path,
                metadata={
                    "section_index": chunk.section_index,
                    "chunk_index": chunk.chunk_index,
                    "file_hash": chunk.file_hash,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                },
            )
        )
    return vector_chunks


def _build_stored_chunks(chunks: Sequence[MarkdownChunk]) -> list[StoredChunk]:
    stored_chunks: list[StoredChunk] = []
    per_document_index: dict[str, int] = {}
    for chunk in chunks:
        next_index = per_document_index.get(chunk.document_id, 0)
        stored_chunks.append(_to_stored_chunk(chunk, stored_chunk_index=next_index))
        per_document_index[chunk.document_id] = next_index + 1
    return stored_chunks


class IndexingService:
    """将 ingest 与 store 串成 `/index` 的主流程。"""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._index_lock = threading.Lock()

    def index(self, mode: str = "incremental") -> IndexingSummary:
        lock_acquired = self._index_lock.acquire(blocking=False)
        if not lock_acquired:
            with timed_operation(LOGGER, "index.lock_wait", mode=mode):
                self._index_lock.acquire()
            lock_acquired = True
        try:
            with timed_operation(LOGGER, "index.run", mode=mode) as span:
                loader = MarkdownIngestLoader(
                    self._build_sources(),
                    chunk_size=self.config.chunker.chunk_size,
                    chunk_overlap=self.config.chunker.chunk_overlap,
                    chunker_version=self.config.chunker.version,
                    embedding_model=self.config.models.embedding,
                )
                metadata_store = SQLiteMetadataStore(self.config.data.sqlite)
                fts_writer = FTS5Writer(metadata_store.connection)
                vector_store = ChromaVectorStore(
                    self.config.data.chroma,
                    collection_metadata={
                        "embedding_model": self.config.models.embedding,
                        "chunker_version": self.config.chunker.version,
                        "hnsw:space": "cosine",
                    },
                    initialize=False,
                )
                embedder = EmbeddingService(
                    self.config.models.embedding,
                    device=self.config.models.device,
                    dtype=self.config.models.dtype,
                    batch_size=self.config.models.embedding_batch_size,
                    hf_cache=self.config.data.hf_cache,
                )

                try:
                    if mode == "full":
                        summary = self._run_full(loader, metadata_store, fts_writer, vector_store, embedder)
                    elif mode == "incremental":
                        summary = self._run_incremental(loader, metadata_store, fts_writer, vector_store, embedder)
                    else:
                        raise IngestError(f"不支持的索引模式: {mode}")

                    metadata_store.append_ingest_log(
                        IngestLogEntry(
                            source_id="all",
                            mode=summary.mode,
                            status="completed",
                            finished_at=datetime.now(UTC),
                            document_count=summary.indexed_documents,
                            chunk_count=summary.indexed_chunks,
                            message=summary.message,
                            metadata={"deleted_documents": summary.deleted_documents},
                        )
                    )
                    span.set(
                        indexed_documents=summary.indexed_documents,
                        indexed_chunks=summary.indexed_chunks,
                        skipped_documents=summary.skipped_documents,
                        deleted_documents=summary.deleted_documents,
                    )
                    return summary
                finally:
                    vector_store.close(clear_client_cache=True)
                    embedder.close()
                    metadata_store.close()
        finally:
            if lock_acquired:
                self._index_lock.release()

    def _run_full(
        self,
        loader: MarkdownIngestLoader,
        metadata_store: SQLiteMetadataStore,
        fts_writer: FTS5Writer,
        vector_store: ChromaVectorStore,
        embedder: EmbeddingService,
    ) -> IndexingSummary:
        with timed_operation(LOGGER, "index.full.plan"):
            batch = loader.build_batch()
        existing_document_ids = tuple(document.document_id for document in metadata_store.iter_documents())
        existing_chunk_ids = tuple(metadata_store.list_chunk_ids())
        if existing_chunk_ids:
            fts_writer.delete_chunk_ids(existing_chunk_ids)
            vector_store.delete(existing_chunk_ids)
        if existing_document_ids:
            metadata_store.delete_documents(existing_document_ids)

        self._persist_batch(
            metadata_store=metadata_store,
            fts_writer=fts_writer,
            vector_store=vector_store,
            embedder=embedder,
            documents=batch.documents,
            chunks=batch.chunks,
        )
        return IndexingSummary(
            mode="full",
            indexed_documents=len(batch.documents),
            indexed_chunks=len(batch.chunks),
            message="完成全量索引",
        )

    def _run_incremental(
        self,
        loader: MarkdownIngestLoader,
        metadata_store: SQLiteMetadataStore,
        fts_writer: FTS5Writer,
        vector_store: ChromaVectorStore,
        embedder: EmbeddingService,
    ) -> IndexingSummary:
        with timed_operation(LOGGER, "index.incremental.plan"):
            previous_states = self._load_previous_states(metadata_store.list_file_states())
            plan = loader.build_incremental_plan(previous_states)
        changes = tuple(plan["changes"])
        changed_documents = {
            change.document_id
            for change in changes
            if change.status in {"added", "modified"}
        }
        removed_documents = {
            change.document_id
            for change in changes
            if change.status == "removed"
        }
        skipped_documents = sum(1 for change in changes if change.status == "unchanged")

        if not changed_documents and not removed_documents:
            return IndexingSummary(
                mode="incremental",
                skipped_documents=skipped_documents,
                message="没有检测到变更",
            )

        stale_document_ids = tuple(sorted(changed_documents | removed_documents))
        existing_chunk_ids = tuple(metadata_store.list_chunk_ids(stale_document_ids))
        if existing_chunk_ids:
            fts_writer.delete_chunk_ids(existing_chunk_ids)
            vector_store.delete(existing_chunk_ids)
        if stale_document_ids:
            metadata_store.delete_documents(stale_document_ids)

        documents = [document for document in plan["documents"] if document.document_id in changed_documents]
        chunks: list[MarkdownChunk] = []
        for document in documents:
            chunks.extend(loader.iter_chunks(document))

        self._persist_batch(
            metadata_store=metadata_store,
            fts_writer=fts_writer,
            vector_store=vector_store,
            embedder=embedder,
            documents=documents,
            chunks=chunks,
        )
        return IndexingSummary(
            mode="incremental",
            indexed_documents=len(documents),
            indexed_chunks=len(chunks),
            skipped_documents=skipped_documents,
            deleted_documents=len(removed_documents),
            message="完成增量索引",
        )

    def _persist_batch(
        self,
        *,
        metadata_store: SQLiteMetadataStore,
        fts_writer: FTS5Writer,
        vector_store: ChromaVectorStore,
        embedder: EmbeddingService,
        documents: Sequence[MarkdownDocument],
        chunks: Sequence[MarkdownChunk],
    ) -> None:
        with timed_operation(
            LOGGER,
            "index.persist_batch",
            document_count=len(documents),
            chunk_count=len(chunks),
        ):
            stored_documents = [_to_stored_document(document) for document in documents]
            stored_chunks = _build_stored_chunks(chunks)

            with timed_operation(LOGGER, "index.persist.metadata", document_count=len(stored_documents), chunk_count=len(stored_chunks)):
                metadata_store.upsert_documents(stored_documents)
                metadata_store.upsert_chunks(stored_chunks)
            with timed_operation(LOGGER, "index.persist.fts", chunk_count=len(stored_chunks)):
                fts_writer.upsert_chunks(stored_chunks)

            if chunks:
                with timed_operation(LOGGER, "index.persist.vector", chunk_count=len(chunks)):
                    embeddings = embedder.embed_texts([chunk.text for chunk in chunks])
                    vector_store.upsert(_to_vector_chunks(chunks, embeddings))

    def _build_sources(self) -> tuple[SourceSpec, ...]:
        return tuple(
            SourceSpec(
                path=source.path,
                excludes=tuple(source.excludes),
            )
            for source in self.config.sources
        )

    def _load_previous_states(self, records: Iterable[dict[str, object]]) -> dict[str, FileState]:
        states: dict[str, FileState] = {}
        for record in records:
            document_id = str(record.get("document_id") or "")
            if not document_id:
                continue
            states[document_id] = FileState(
                document_id=document_id,
                file_path=str(record.get("file_path") or ""),
                file_hash=str(record.get("file_hash") or ""),
                mtime_ns=int(record.get("mtime_ns") or 0),
                size=int(record.get("size") or 0),
                source_id=str(record.get("source_id") or ""),
            )
        return states
