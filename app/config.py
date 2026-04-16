from __future__ import annotations

from pathlib import Path
import os
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.retrieval_pipeline_config import (
    DEFAULT_RANKING_PIPELINE_STEPS,
    KNOWN_RANKING_PIPELINE_STEPS,
    LIMIT_RERANK_CANDIDATES_STEP,
    METADATA_CONSTRAINTS_POST_RERANK_STEP,
    RERANK_STEP,
    TOP_K_LIMIT_STEP,
)

try:
    from pydantic import ConfigDict
except ImportError:
    ConfigDict = None

try:
    from pydantic import field_validator, model_validator
except ImportError:
    field_validator = None
    model_validator = None
    from pydantic import root_validator, validator
else:
    root_validator = None
    validator = None


class ConfigBaseModel(BaseModel):
    if ConfigDict is None:
        class Config:
            extra = "ignore"
    else:
        model_config = ConfigDict(extra="ignore")


class ServerConfig(ConfigBaseModel):

    host: str = "127.0.0.1"
    port: int = 49153
    warmup_on_startup: bool = False

    if field_validator is not None:

        @field_validator("port")
        @classmethod
        def _validate_port(cls, value: int) -> int:
            if value <= 0 or value > 65535:
                raise ValueError("server.port must be between 1 and 65535")
            return value
    else:

        @validator("port")
        def _validate_port(cls, value: int) -> int:
            if value <= 0 or value > 65535:
                raise ValueError("server.port must be between 1 and 65535")
            return value


class SourceConfig(ConfigBaseModel):

    path: str
    excludes: list[str] = Field(default_factory=list)

    if field_validator is not None:

        @field_validator("path")
        @classmethod
        def _validate_path(cls, value: str) -> str:
            cleaned = value.strip()
            if not cleaned:
                raise ValueError("sources[].path must not be empty")
            return cleaned
    else:

        @validator("path")
        def _validate_path(cls, value: str) -> str:
            cleaned = value.strip()
            if not cleaned:
                raise ValueError("sources[].path must not be empty")
            return cleaned


class DataConfig(ConfigBaseModel):

    sqlite: str = "./data/meta.db"
    chroma: str = "./data/chroma"
    hf_cache: str = "./data/hf-cache"


class ModelConfig(ConfigBaseModel):

    embedding: str = "BAAI/bge-m3"
    reranker: str = "BAAI/bge-reranker-v2-m3"
    device: str = "cuda"
    dtype: str = "float16"
    embedding_batch_size: int = 8
    reranker_batch_size: int = 32

    if field_validator is not None:

        @field_validator("embedding_batch_size", "reranker_batch_size")
        @classmethod
        def _validate_batch_sizes(cls, value: int) -> int:
            if value <= 0:
                raise ValueError("model batch sizes must be positive")
            return value
    else:

        @validator("embedding_batch_size", "reranker_batch_size")
        def _validate_batch_sizes(cls, value: int) -> int:
            if value <= 0:
                raise ValueError("model batch sizes must be positive")
            return value


class ChunkerConfig(ConfigBaseModel):

    version: str = "v1"
    chunk_size: int = 800
    chunk_overlap: int = 100
    contextual_embedding_enabled: bool = True

    if model_validator is not None:

        @model_validator(mode="after")
        def _validate_chunk_window(self) -> "ChunkerConfig":
            if self.chunk_size <= 0:
                raise ValueError("chunker.chunk_size must be positive")
            if self.chunk_overlap < 0:
                raise ValueError("chunker.chunk_overlap must be >= 0")
            if self.chunk_overlap >= self.chunk_size:
                raise ValueError("chunker.chunk_overlap must be smaller than chunker.chunk_size")
            return self
    else:

        @root_validator
        def _validate_chunk_window(cls, values: dict[str, Any]) -> dict[str, Any]:
            chunk_size = int(values.get("chunk_size", 0) or 0)
            chunk_overlap = int(values.get("chunk_overlap", 0) or 0)
            if chunk_size <= 0:
                raise ValueError("chunker.chunk_size must be positive")
            if chunk_overlap < 0:
                raise ValueError("chunker.chunk_overlap must be >= 0")
            if chunk_overlap >= chunk_size:
                raise ValueError("chunker.chunk_overlap must be smaller than chunker.chunk_size")
            return values


class SourceCleaningRuleConfig(ConfigBaseModel):

    id: str = ""
    enabled: bool = True
    path_globs: list[str] = Field(default_factory=list)
    source_root_globs: list[str] = Field(default_factory=list)
    drop_line_patterns: list[str] = Field(default_factory=list)
    drop_trailing_heading_titles: list[str] = Field(default_factory=list)


class CleaningConfig(ConfigBaseModel):

    enabled: bool = False
    extract_front_matter: bool = True
    drop_front_matter_from_content: bool = True
    normalize_whitespace: bool = True
    drop_toc_markers: bool = True
    drop_low_value_placeholders: bool = True
    normalize_markdown_tables: bool = True
    dedupe_exact_chunks: bool = True
    source_rules: list[SourceCleaningRuleConfig] = Field(default_factory=list)


class RetrievalConfig(ConfigBaseModel):

    recall_top_k: int = 20
    rerank_top_k: int = 6
    rerank_candidate_limit: int = 24
    semantic_enabled: bool = True
    semantic_batch_enabled: bool = True
    parent_context_enabled: bool = True
    parent_context_max_chunks: int = 3
    rrf_k: int = 60
    min_output_score: float = 0.10
    query_type_fusion_weights: dict[str, dict[str, float]] = Field(
        default_factory=lambda: {
            "definition": {"lexical": 0.85, "semantic": 1.15},
            "lookup": {"lexical": 1.25, "semantic": 0.9},
            "existence": {"lexical": 1.3, "semantic": 0.85},
            "procedure": {"lexical": 0.95, "semantic": 1.1},
            "comparison": {"lexical": 1.0, "semantic": 1.05},
        }
    )
    ranking_pipeline: list[str] = Field(default_factory=lambda: list(DEFAULT_RANKING_PIPELINE_STEPS))

    if model_validator is not None:

        @model_validator(mode="after")
        def _validate_semantics(self) -> "RetrievalConfig":
            if self.recall_top_k <= 0:
                raise ValueError("retrieval.recall_top_k must be positive")
            if self.rerank_top_k <= 0:
                raise ValueError("retrieval.rerank_top_k must be positive")
            if self.rerank_candidate_limit <= 0:
                raise ValueError("retrieval.rerank_candidate_limit must be positive")
            if self.rerank_candidate_limit < self.rerank_top_k:
                raise ValueError("retrieval.rerank_candidate_limit must be >= retrieval.rerank_top_k")
            if self.parent_context_max_chunks <= 0:
                raise ValueError("retrieval.parent_context_max_chunks must be positive")
            if self.rrf_k <= 0:
                raise ValueError("retrieval.rrf_k must be positive")
            if self.min_output_score < 0.0 or self.min_output_score > 1.0:
                raise ValueError("retrieval.min_output_score must be between 0 and 1")
            self.query_type_fusion_weights = _validate_query_type_fusion_weights(self.query_type_fusion_weights)
            self.ranking_pipeline = _validate_ranking_pipeline(self.ranking_pipeline)
            return self
    else:

        @root_validator
        def _validate_semantics(cls, values: dict[str, Any]) -> dict[str, Any]:
            recall_top_k = int(values.get("recall_top_k", 0) or 0)
            rerank_top_k = int(values.get("rerank_top_k", 0) or 0)
            rerank_candidate_limit = int(values.get("rerank_candidate_limit", 0) or 0)
            parent_context_max_chunks = int(values.get("parent_context_max_chunks", 0) or 0)
            rrf_k = int(values.get("rrf_k", 0) or 0)
            min_output_score = float(values.get("min_output_score", 0.0) or 0.0)
            if recall_top_k <= 0:
                raise ValueError("retrieval.recall_top_k must be positive")
            if rerank_top_k <= 0:
                raise ValueError("retrieval.rerank_top_k must be positive")
            if rerank_candidate_limit <= 0:
                raise ValueError("retrieval.rerank_candidate_limit must be positive")
            if rerank_candidate_limit < rerank_top_k:
                raise ValueError("retrieval.rerank_candidate_limit must be >= retrieval.rerank_top_k")
            if parent_context_max_chunks <= 0:
                raise ValueError("retrieval.parent_context_max_chunks must be positive")
            if rrf_k <= 0:
                raise ValueError("retrieval.rrf_k must be positive")
            if min_output_score < 0.0 or min_output_score > 1.0:
                raise ValueError("retrieval.min_output_score must be between 0 and 1")
            values["query_type_fusion_weights"] = _validate_query_type_fusion_weights(
                values.get("query_type_fusion_weights")
            )
            values["ranking_pipeline"] = _validate_ranking_pipeline(values.get("ranking_pipeline"))
            return values


class AbstainConfig(ConfigBaseModel):

    top1_min: float = 0.20
    top3_avg_min: float = 0.30
    min_hits: int = 2
    min_total_chars: int = 150
    min_query_term_count: int = 2
    min_query_term_coverage: float = 0.60

    if model_validator is not None:

        @model_validator(mode="after")
        def _validate_semantics(self) -> "AbstainConfig":
            if self.top1_min < 0.0 or self.top1_min > 1.0:
                raise ValueError("abstain.top1_min must be between 0 and 1")
            if self.top3_avg_min < 0.0 or self.top3_avg_min > 1.0:
                raise ValueError("abstain.top3_avg_min must be between 0 and 1")
            if self.min_hits <= 0:
                raise ValueError("abstain.min_hits must be positive")
            if self.min_total_chars <= 0:
                raise ValueError("abstain.min_total_chars must be positive")
            if self.min_query_term_count <= 0:
                raise ValueError("abstain.min_query_term_count must be positive")
            if self.min_query_term_coverage < 0.0 or self.min_query_term_coverage > 1.0:
                raise ValueError("abstain.min_query_term_coverage must be between 0 and 1")
            return self
    else:

        @root_validator
        def _validate_semantics(cls, values: dict[str, Any]) -> dict[str, Any]:
            top1_min = float(values.get("top1_min", 0.0) or 0.0)
            top3_avg_min = float(values.get("top3_avg_min", 0.0) or 0.0)
            min_hits = int(values.get("min_hits", 0) or 0)
            min_total_chars = int(values.get("min_total_chars", 0) or 0)
            min_query_term_count = int(values.get("min_query_term_count", 0) or 0)
            min_query_term_coverage = float(values.get("min_query_term_coverage", 0.0) or 0.0)
            if top1_min < 0.0 or top1_min > 1.0:
                raise ValueError("abstain.top1_min must be between 0 and 1")
            if top3_avg_min < 0.0 or top3_avg_min > 1.0:
                raise ValueError("abstain.top3_avg_min must be between 0 and 1")
            if min_hits <= 0:
                raise ValueError("abstain.min_hits must be positive")
            if min_total_chars <= 0:
                raise ValueError("abstain.min_total_chars must be positive")
            if min_query_term_count <= 0:
                raise ValueError("abstain.min_query_term_count must be positive")
            if min_query_term_coverage < 0.0 or min_query_term_coverage > 1.0:
                raise ValueError("abstain.min_query_term_coverage must be between 0 and 1")
            return values


class VerifyConfig(ConfigBaseModel):

    min_ngram_len: int = 8
    coverage_threshold: float = 0.50

    if model_validator is not None:

        @model_validator(mode="after")
        def _validate_semantics(self) -> "VerifyConfig":
            if self.min_ngram_len <= 0:
                raise ValueError("verify.min_ngram_len must be positive")
            if self.coverage_threshold < 0.0 or self.coverage_threshold > 1.0:
                raise ValueError("verify.coverage_threshold must be between 0 and 1")
            return self
    else:

        @root_validator
        def _validate_semantics(cls, values: dict[str, Any]) -> dict[str, Any]:
            min_ngram_len = int(values.get("min_ngram_len", 0) or 0)
            coverage_threshold = float(values.get("coverage_threshold", 0.0) or 0.0)
            if min_ngram_len <= 0:
                raise ValueError("verify.min_ngram_len must be positive")
            if coverage_threshold < 0.0 or coverage_threshold > 1.0:
                raise ValueError("verify.coverage_threshold must be between 0 and 1")
            return values


class AppConfig(ConfigBaseModel):

    server: ServerConfig = Field(default_factory=ServerConfig)
    sources: list[SourceConfig] = Field(default_factory=list)
    data: DataConfig = Field(default_factory=DataConfig)
    models: ModelConfig = Field(default_factory=ModelConfig)
    chunker: ChunkerConfig = Field(default_factory=ChunkerConfig)
    cleaning: CleaningConfig = Field(default_factory=CleaningConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    abstain: AbstainConfig = Field(default_factory=AbstainConfig)
    verify: VerifyConfig = Field(default_factory=VerifyConfig)


def _validate_query_type_fusion_weights(raw: Any) -> dict[str, dict[str, float]]:
    normalized: dict[str, dict[str, float]] = {}
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("retrieval.query_type_fusion_weights must be a mapping")

    for query_type, weights in raw.items():
        query_type_key = str(query_type).strip()
        if not query_type_key:
            raise ValueError("retrieval.query_type_fusion_weights contains an empty query type key")
        if not isinstance(weights, dict):
            raise ValueError(f"retrieval.query_type_fusion_weights.{query_type_key} must be a mapping")
        lexical = float(weights.get("lexical", 1.0) or 0.0)
        semantic = float(weights.get("semantic", 1.0) or 0.0)
        if lexical <= 0.0:
            raise ValueError(f"retrieval.query_type_fusion_weights.{query_type_key}.lexical must be positive")
        if semantic <= 0.0:
            raise ValueError(f"retrieval.query_type_fusion_weights.{query_type_key}.semantic must be positive")
        normalized[query_type_key] = {
            "lexical": lexical,
            "semantic": semantic,
        }
    return normalized


def _validate_ranking_pipeline(steps: Any) -> list[str]:
    normalized_steps = [str(step).strip() for step in (steps or DEFAULT_RANKING_PIPELINE_STEPS) if str(step).strip()]
    if not normalized_steps:
        raise ValueError("retrieval.ranking_pipeline must not be empty")

    unknown = [step for step in normalized_steps if step not in KNOWN_RANKING_PIPELINE_STEPS]
    if unknown:
        raise ValueError(f"retrieval.ranking_pipeline contains unknown steps: {unknown}")

    duplicates = [step for index, step in enumerate(normalized_steps) if step in normalized_steps[:index]]
    if duplicates:
        raise ValueError(f"retrieval.ranking_pipeline contains duplicate steps: {duplicates}")

    if RERANK_STEP not in normalized_steps:
        raise ValueError("retrieval.ranking_pipeline must include 'rerank'")

    rerank_index = normalized_steps.index(RERANK_STEP)
    if LIMIT_RERANK_CANDIDATES_STEP in normalized_steps and normalized_steps.index(LIMIT_RERANK_CANDIDATES_STEP) > rerank_index:
        raise ValueError("'limit_rerank_candidates' must run before 'rerank'")
    if METADATA_CONSTRAINTS_POST_RERANK_STEP in normalized_steps and normalized_steps.index(METADATA_CONSTRAINTS_POST_RERANK_STEP) < rerank_index:
        raise ValueError("'metadata_constraints_post_rerank' must run after 'rerank'")
    if TOP_K_LIMIT_STEP in normalized_steps and normalized_steps[-1] != TOP_K_LIMIT_STEP:
        raise ValueError("'top_k_limit' must be the last ranking step")

    return normalized_steps


DEFAULT_CONFIG_PATH = Path("config.yaml")
PROJECT_ROOT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
CONFIG_ENV_VAR = "KMS_CONFIG_PATH"
SERVER_HOST_ENV_VAR = "KMS_HOST"
SERVER_PORT_ENV_VAR = "KMS_PORT"


def resolve_config_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)

    env_path = os.getenv(CONFIG_ENV_VAR)
    if env_path:
        return Path(env_path)

    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH

    if PROJECT_ROOT_CONFIG_PATH.exists():
        return PROJECT_ROOT_CONFIG_PATH

    return DEFAULT_CONFIG_PATH


def _load_raw_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"Config file {path} must contain a YAML mapping at the top level.")

    return raw


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = resolve_config_path(path)
    raw_config = _load_raw_config(config_path)
    if hasattr(AppConfig, "model_validate"):
        config = AppConfig.model_validate(raw_config)
    else:
        config = AppConfig.parse_obj(raw_config)

    host = os.getenv(SERVER_HOST_ENV_VAR)
    if host:
        config.server.host = host

    port = os.getenv(SERVER_PORT_ENV_VAR)
    if port:
        config.server.port = int(port)

    return config
