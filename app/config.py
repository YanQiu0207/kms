from __future__ import annotations

from pathlib import Path
import os
from typing import Any

import yaml
from pydantic import BaseModel, Field

try:
    from pydantic import ConfigDict
except ImportError:
    ConfigDict = None


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


class SourceConfig(ConfigBaseModel):

    path: str
    excludes: list[str] = Field(default_factory=list)


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


class ChunkerConfig(ConfigBaseModel):

    version: str = "v1"
    chunk_size: int = 800
    chunk_overlap: int = 100


class RetrievalConfig(ConfigBaseModel):

    recall_top_k: int = 20
    rerank_top_k: int = 6
    rerank_candidate_limit: int = 24
    rrf_k: int = 60
    min_output_score: float = 0.10


class AbstainConfig(ConfigBaseModel):

    top1_min: float = 0.20
    top3_avg_min: float = 0.30
    min_hits: int = 2
    min_total_chars: int = 150
    min_query_term_count: int = 2
    min_query_term_coverage: float = 0.60


class VerifyConfig(ConfigBaseModel):

    min_ngram_len: int = 8
    coverage_threshold: float = 0.50


class AppConfig(ConfigBaseModel):

    server: ServerConfig = Field(default_factory=ServerConfig)
    sources: list[SourceConfig] = Field(default_factory=list)
    data: DataConfig = Field(default_factory=DataConfig)
    models: ModelConfig = Field(default_factory=ModelConfig)
    chunker: ChunkerConfig = Field(default_factory=ChunkerConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    abstain: AbstainConfig = Field(default_factory=AbstainConfig)
    verify: VerifyConfig = Field(default_factory=VerifyConfig)


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
