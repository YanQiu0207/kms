from __future__ import annotations

from contextlib import asynccontextmanager
import time
from urllib.parse import parse_qsl
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request

from . import __version__
from .config import AppConfig, load_config
from .observability import (
    bind_request_id,
    bind_span,
    configure_logging,
    duration_fields,
    get_logger,
    log_event,
    reset_request_id,
    reset_span,
    timed_operation,
)
from .services import EmbeddingServiceError, IndexingService, QueryService
from .schemas import (
    AskRequest,
    AskResponse,
    AskSource,
    ErrorResponse,
    HealthResponse,
    IndexRequest,
    IndexResponse,
    SearchRequest,
    SearchResponse,
    StatsResponse,
    VerifyDetail,
    VerifyRequest,
    VerifyResponse,
)
from .store import SQLiteMetadataStore
from .timefmt import format_local_datetime

APP_TITLE = "kms-api"
APP_DESCRIPTION = "FastAPI scaffold for the personal knowledge base service."
LOGGER = get_logger("kms.api")

NOT_IMPLEMENTED_RESPONSE = {
    501: {
        "model": ErrorResponse,
        "description": "Endpoint scaffold only; implementation will land in later milestones.",
    }
}


def _query_log_summary(query: str) -> dict[str, int]:
    if not query:
        return {"query_len": 0, "query_param_count": 0}
    return {
        "query_len": len(query),
        "query_param_count": len(parse_qsl(query, keep_blank_values=True)),
    }


def create_app(config: AppConfig | None = None) -> FastAPI:
    settings = config or load_config()
    configure_logging()
    indexing_service = IndexingService(settings)
    query_service = QueryService(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with timed_operation(
            LOGGER,
            "app.startup",
            host=settings.server.host,
            port=settings.server.port,
            warmup_on_startup=settings.server.warmup_on_startup,
        ):
            if settings.server.warmup_on_startup:
                query_service.warmup()
        try:
            yield
        finally:
            with timed_operation(LOGGER, "app.shutdown", host=settings.server.host, port=settings.server.port):
                query_service.close()

    app = FastAPI(title=APP_TITLE, version=__version__, description=APP_DESCRIPTION, lifespan=lifespan)
    app.state.config = settings
    app.state.indexing_service = indexing_service
    app.state.query_service = query_service

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        request_id = uuid4().hex[:12]
        request_token = bind_request_id(request_id)
        request_span, span_token = bind_span("http.request", kind="server")
        started_at = time.perf_counter()
        status = "ok"
        status_code: int | None = None
        error_type: str | None = None
        log_event(
            LOGGER,
            "start",
            request_id=request_id,
            trace_id=request_id,
            span_name=request_span.span_name,
            span_id=request_span.span_id,
            kind=request_span.kind,
            method=request.method,
            path=request.url.path,
            **_query_log_summary(request.url.query),
            client=request.client.host if request.client else None,
        )
        try:
            response = await call_next(request)
            status_code = response.status_code
            if response.status_code >= 400:
                status = "error"
        except Exception as exc:
            status = "error"
            status_code = getattr(exc, "status_code", 500)
            error_type = type(exc).__name__
            LOGGER.exception(
                "error",
                extra={
                    "context": {
                        "event": "error",
                        "request_id": request_id,
                        "trace_id": request_id,
                        "span_name": request_span.span_name,
                        "span_id": request_span.span_id,
                        "kind": request_span.kind,
                        "method": request.method,
                        "path": request.url.path,
                        "status": "error",
                        "status_code": status_code,
                        "error_type": error_type,
                        **duration_fields((time.perf_counter() - started_at) * 1000.0),
                    }
                },
            )
            raise
        else:
            return response
        finally:
            log_event(
                LOGGER,
                "end",
                request_id=request_id,
                trace_id=request_id,
                span_name=request_span.span_name,
                span_id=request_span.span_id,
                kind=request_span.kind,
                method=request.method,
                path=request.url.path,
                status=status,
                status_code=status_code,
                error_type=error_type,
                **duration_fields((time.perf_counter() - started_at) * 1000.0),
            )
            reset_span(span_token)
            reset_request_id(request_token)

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(
            version=__version__,
            timestamp=format_local_datetime(),
        )

    @app.get("/stats", response_model=StatsResponse, tags=["system"])
    def stats() -> StatsResponse:
        with timed_operation(LOGGER, "api.stats"):
            with SQLiteMetadataStore(settings.data.sqlite) as store:
                store_stats = store.stats()
            return StatsResponse(
                document_count=store_stats.document_count,
                chunk_count=store_stats.chunk_count,
                source_count=len(settings.sources),
                embedding_model=settings.models.embedding,
                reranker_model=settings.models.reranker,
                chunker_version=settings.chunker.version,
                sqlite_path=settings.data.sqlite,
                chroma_path=settings.data.chroma,
                hf_cache=settings.data.hf_cache,
                device=settings.models.device,
                dtype=settings.models.dtype,
                last_indexed_at=format_local_datetime(store_stats.last_indexed_at) if store_stats.last_indexed_at else None,
            )

    @app.post("/index", response_model=IndexResponse, tags=["ingest"])
    def index(request: IndexRequest) -> IndexResponse:
        with timed_operation(LOGGER, "api.index", mode=request.mode):
            try:
                summary = app.state.indexing_service.index(request.mode)
            except (EmbeddingServiceError, RuntimeError) as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            app.state.query_service.invalidate_cache()
            return IndexResponse(
                mode=request.mode,
                indexed_documents=summary.indexed_documents,
                indexed_chunks=summary.indexed_chunks,
                skipped_documents=summary.skipped_documents,
                deleted_documents=summary.deleted_documents,
                message=summary.message,
            )

    @app.post("/search", response_model=SearchResponse, tags=["retrieve"])
    def search(request: SearchRequest) -> SearchResponse:
        with timed_operation(LOGGER, "api.search", query_count=len(request.queries)):
            try:
                result_set = app.state.query_service.search(
                    request.queries,
                    recall_top_k=request.recall_top_k,
                    rerank_top_k=request.rerank_top_k,
                )
            except RuntimeError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            return SearchResponse.model_validate(result_set.to_payload())

    @app.post("/ask", response_model=AskResponse, tags=["answer"])
    def ask(request: AskRequest) -> AskResponse:
        with timed_operation(LOGGER, "api.ask", question=request.question):
            try:
                result = app.state.query_service.ask(
                    request.question,
                    queries=request.queries,
                    recall_top_k=request.recall_top_k,
                    rerank_top_k=request.rerank_top_k,
                )
            except RuntimeError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            return AskResponse(
                abstained=result.abstained,
                confidence=result.confidence,
                prompt=result.prompt,
                sources=[
                    AskSource(
                        ref_index=int(source["ref_index"]),
                        chunk_id=str(source["chunk_id"]),
                        file_path=str(source["file_path"]),
                        location=str(source["location"]),
                        title_path=list(source["title_path"]),
                        text=str(source["text"]),
                        score=float(source["score"]),
                        doc_id=str(source["doc_id"]) if source["doc_id"] is not None else None,
                    )
                    for source in result.sources
                ],
                abstain_reason=result.abstain_reason,
            )

    @app.post("/verify", response_model=VerifyResponse, tags=["answer"])
    def verify(request: VerifyRequest) -> VerifyResponse:
        with timed_operation(LOGGER, "api.verify", chunk_id_count=len(request.used_chunk_ids)):
            try:
                result = app.state.query_service.verify(request.answer, request.used_chunk_ids)
            except RuntimeError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            return VerifyResponse(
                citation_unverified=result.citation_unverified,
                coverage=result.coverage,
                details=[
                    VerifyDetail(
                        chunk_id=detail.chunk_id,
                        matched_ngrams=detail.matched_ngrams,
                        total_ngrams=detail.total_ngrams,
                    )
                    for detail in result.details
                ],
            )

    return app


def run() -> None:
    import uvicorn

    app = create_app(load_config())
    configure_logging()
    log_event(
        LOGGER,
        "server.run",
        host=app.state.config.server.host,
        port=app.state.config.server.port,
    )
    uvicorn.run(
        app,
        host=app.state.config.server.host,
        port=app.state.config.server.port,
        reload=False,
        log_config=None,
    )


if __name__ == "__main__":
    run()
