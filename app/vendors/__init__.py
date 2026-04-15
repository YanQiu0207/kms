"""Third-party vendor anti-corruption layer.

This package is the only place where the application should directly depend on
specific external library APIs for retrieval/model/runtime plumbing.
"""

from .chroma import VendorChromaError, clear_persistent_client_cache, get_persistent_client
from .flag_embedding import (
    VendorFlagEmbeddingError,
    create_flag_auto_model,
    create_flag_reranker,
)
from .jieba_tokenizer import cut_tokens

__all__ = [
    "VendorChromaError",
    "VendorFlagEmbeddingError",
    "clear_persistent_client_cache",
    "create_flag_auto_model",
    "create_flag_reranker",
    "cut_tokens",
    "get_persistent_client",
]
