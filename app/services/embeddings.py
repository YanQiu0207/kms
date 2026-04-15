"""本地 embedding 服务。"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Sequence

from app.observability import get_logger, timed_operation
from app.runtime_cleanup import best_effort_close, best_effort_release_runtime_resources
from app.vendors import VendorFlagEmbeddingError, create_flag_auto_model

LOGGER = get_logger("kms.embedding")


class EmbeddingServiceError(RuntimeError):
    """Embedding 计算失败。"""


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


class EmbeddingService:
    """封装调试 embedding 和 FlagEmbedding 模型。"""

    def __init__(
        self,
        model_name: str,
        *,
        device: str = "cpu",
        dtype: str = "float32",
        batch_size: int = 8,
        hf_cache: str | Path | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.dtype = dtype
        self.batch_size = max(1, int(batch_size))
        self.hf_cache = None if hf_cache is None else Path(hf_cache)
        self._model = None
        self._lock = threading.RLock()

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        if self.model_name == "debug-hash":
            return [_debug_hash_embedding(text) for text in texts]

        with timed_operation(
            LOGGER,
            "embedding.encode",
            model_name=self.model_name,
            text_count=len(texts),
            batch_size=self.batch_size,
            device=self.device,
            dtype=self.dtype,
        ):
            with self._lock:
                model = self._ensure_model()
                try:
                    try:
                        raw = model.encode(list(texts), batch_size=self.batch_size)
                    except TypeError:
                        raw = model.encode(list(texts))
                except Exception as exc:  # pragma: no cover - 依赖模型时触发
                    raise EmbeddingServiceError(f"embedding 编码失败: {self.model_name}") from exc

        if isinstance(raw, dict):
            dense = raw.get("dense_vecs")
            if dense is None:
                raise EmbeddingServiceError("embedding 返回值缺少 dense_vecs")
            raw = dense

        if hasattr(raw, "tolist"):
            raw = raw.tolist()

        return [[float(value) for value in row] for row in raw]

    def _ensure_model(self):
        with self._lock:
            if self._model is not None:
                return self._model

            with timed_operation(
                LOGGER,
                "embedding.model_load",
                model_name=self.model_name,
                device=self.device,
                dtype=self.dtype,
            ):
                try:
                    self._model = create_flag_auto_model(
                        self.model_name,
                        device=self.device,
                        use_fp16=self.dtype.lower() == "float16",
                        hf_cache=self.hf_cache,
                    )
                except VendorFlagEmbeddingError as exc:  # pragma: no cover - 依赖模型时触发
                    raise EmbeddingServiceError(f"加载 embedding 模型失败: {self.model_name}") from exc
                return self._model

    def close(self) -> None:
        with self._lock:
            model = self._model
            self._model = None

        if model is None:
            return

        with timed_operation(LOGGER, "embedding.close", model_name=self.model_name, device=self.device):
            best_effort_close(model)
            best_effort_release_runtime_resources()
