from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

try:
    from pydantic import ConfigDict, field_validator
except ImportError:
    ConfigDict = None
    from pydantic import validator as field_validator


class BaseSchema(BaseModel):
    if ConfigDict is None:
        class Config:
            extra = "ignore"
    else:
        model_config = ConfigDict(extra="ignore")


class ErrorResponse(BaseSchema):
    detail: str
    code: str = "not_implemented"


class HealthResponse(BaseSchema):
    status: Literal["ok"] = "ok"
    service: str = "kms-api"
    version: str
    timestamp: str


class StatsResponse(BaseSchema):
    document_count: int = 0
    chunk_count: int = 0
    source_count: int = 0
    embedding_model: str
    reranker_model: str
    chunker_version: str
    sqlite_path: str
    chroma_path: str
    hf_cache: str
    device: str
    dtype: str
    last_indexed_at: str | None = None


class IndexRequest(BaseSchema):
    mode: Literal["full", "incremental"] = "incremental"


class IndexResponse(BaseSchema):
    mode: Literal["full", "incremental"]
    indexed_documents: int = 0
    indexed_chunks: int = 0
    skipped_documents: int = 0
    deleted_documents: int = 0
    message: str = ""


class SearchRequest(BaseSchema):
    queries: list[str] = Field(default_factory=list)
    recall_top_k: int | None = None
    rerank_top_k: int | None = None

    @field_validator("queries")
    @classmethod
    def _validate_queries(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("queries must contain at least one non-empty string")
        return cleaned

    @field_validator("recall_top_k", "rerank_top_k")
    @classmethod
    def _validate_top_k(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value < 0:
            raise ValueError("top_k values must be non-negative")
        return value


class SearchResult(BaseSchema):
    chunk_id: str
    file_path: str
    location: str = ""
    title_path: list[str] = Field(default_factory=list)
    text: str
    score: float
    doc_id: str | None = None


class SearchDebug(BaseSchema):
    queries_count: int = 0
    recall_count: int = 0
    rerank_count: int = 0


class SearchResponse(BaseSchema):
    results: list[SearchResult] = Field(default_factory=list)
    debug: SearchDebug = Field(default_factory=SearchDebug)


class AskRequest(BaseSchema):
    question: str
    queries: list[str] = Field(default_factory=list)
    recall_top_k: int | None = None
    rerank_top_k: int | None = None

    @field_validator("question")
    @classmethod
    def _validate_question(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("question cannot be empty")
        return stripped

    @field_validator("queries")
    @classmethod
    def _validate_queries(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        return cleaned

    @field_validator("recall_top_k", "rerank_top_k")
    @classmethod
    def _validate_top_k(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value < 0:
            raise ValueError("top_k values must be non-negative")
        return value


class AskSource(BaseSchema):
    ref_index: int = 0
    chunk_id: str
    file_path: str
    location: str = ""
    title_path: list[str] = Field(default_factory=list)
    text: str
    score: float
    doc_id: str | None = None


class AskResponse(BaseSchema):
    abstained: bool
    confidence: float
    prompt: str
    sources: list[AskSource] = Field(default_factory=list)
    abstain_reason: str | None = None


class VerifyRequest(BaseSchema):
    answer: str
    used_chunk_ids: list[str] = Field(default_factory=list)

    @field_validator("answer")
    @classmethod
    def _validate_answer(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("answer cannot be empty")
        return stripped

    @field_validator("used_chunk_ids")
    @classmethod
    def _validate_chunk_ids(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("used_chunk_ids must contain at least one non-empty string")
        return cleaned


class VerifyDetail(BaseSchema):
    chunk_id: str
    matched_ngrams: int
    total_ngrams: int


class VerifyResponse(BaseSchema):
    citation_unverified: bool
    coverage: float
    details: list[VerifyDetail] = Field(default_factory=list)
