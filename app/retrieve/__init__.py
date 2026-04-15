"""Retrieval package skeleton."""

from .contracts import (
    PlaceholderRetrievalService,
    RetrievalError,
    RetrievalService,
    RetrievedChunk,
    SearchDebug,
    SearchResultSet,
)
from .hybrid import HybridRetrievalService, reciprocal_rank_fusion
from .lexical import LexicalRetriever
from .rerank import DebugReranker, FlagEmbeddingReranker, build_reranker
from .semantic import DebugEmbeddingEncoder, SemanticRetriever, build_embedding_encoder

__all__ = [
    "DebugEmbeddingEncoder",
    "DebugReranker",
    "FlagEmbeddingReranker",
    "HybridRetrievalService",
    "LexicalRetriever",
    "PlaceholderRetrievalService",
    "RetrievedChunk",
    "RetrievalError",
    "RetrievalService",
    "SearchDebug",
    "SearchResultSet",
    "SemanticRetriever",
    "build_embedding_encoder",
    "build_reranker",
    "reciprocal_rank_fusion",
]
