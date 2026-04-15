from __future__ import annotations

from functools import lru_cache
from os import environ
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Callable


class VendorFlagEmbeddingError(RuntimeError):
    """Raised when the FlagEmbedding vendor adapter cannot satisfy the request."""


@lru_cache(maxsize=2)
def _load_flag_auto_model():
    try:
        from FlagEmbedding import FlagAutoModel  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised only when dependency is absent
        raise VendorFlagEmbeddingError("FlagEmbedding auto model is unavailable") from exc
    return FlagAutoModel


@lru_cache(maxsize=1)
def _load_flag_reranker():
    try:
        from FlagEmbedding import FlagReranker  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised only when dependency is absent
        raise VendorFlagEmbeddingError("FlagEmbedding reranker is unavailable") from exc
    return FlagReranker


def _apply_hf_cache(hf_cache: str | Path | None) -> Path | None:
    if hf_cache is None:
        return None
    cache_path = Path(hf_cache)
    cache_path.mkdir(parents=True, exist_ok=True)
    environ.setdefault("HF_HOME", str(cache_path))
    return cache_path


def _model_cache_key(model_name: str) -> str:
    return f"models--{model_name.replace('/', '--')}"


def _is_complete_snapshot(snapshot_dir: Path) -> bool:
    required = ("config.json",)
    optional_any = ("tokenizer.json", "tokenizer_config.json", "sentencepiece.bpe.model")
    return all((snapshot_dir / name).exists() for name in required) and any(
        (snapshot_dir / name).exists() for name in optional_any
    )


def _candidate_hf_hub_roots(cache_path: Path | None) -> tuple[Path, ...]:
    candidates: list[Path] = []
    if cache_path is not None:
        candidates.append(cache_path / "hub" if cache_path.name != "hub" else cache_path)
    candidates.append(Path.home() / ".cache" / "huggingface" / "hub")

    ordered: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(candidate)
    return tuple(ordered)


def _resolve_local_snapshot_path(model_name: str, cache_path: Path | None) -> Path | None:
    model_dir_name = _model_cache_key(model_name)
    for hub_root in _candidate_hf_hub_roots(cache_path):
        model_root = hub_root / model_dir_name
        if not model_root.exists():
            continue

        ref_file = model_root / "refs" / "main"
        if ref_file.exists():
            revision = ref_file.read_text(encoding="utf-8").strip()
            snapshot_dir = model_root / "snapshots" / revision
            if _is_complete_snapshot(snapshot_dir):
                return snapshot_dir

        snapshots_dir = model_root / "snapshots"
        if not snapshots_dir.exists():
            continue
        for snapshot_dir in sorted(snapshots_dir.iterdir(), reverse=True):
            if snapshot_dir.is_dir() and _is_complete_snapshot(snapshot_dir):
                return snapshot_dir
    return None


def _embedder_model_class_for(model_name: str) -> str | None:
    base_name = PurePosixPath(model_name.replace("\\", "/")).name
    if base_name == "bge-m3":
        return "encoder-only-m3"
    return None


def _invoke_with_fallback(
    factory: Callable[..., object],
    model_source: str,
    *,
    display_name: str,
    base_kwargs: dict[str, Any],
    cache_path: Path | None,
) -> object:
    attempts: list[dict[str, Any]] = []
    if cache_path is not None:
        attempts.append(
            {
                **base_kwargs,
                "cache_dir": str(cache_path),
                "local_files_only": True,
            }
        )
    attempts.append(
        {
            **base_kwargs,
            **({"cache_dir": str(cache_path)} if cache_path is not None else {}),
        }
    )
    attempts.append(
        {
            key: value
            for key, value in attempts[-1].items()
            if key not in {"devices", "local_files_only", "cache_dir"}
        }
    )
    attempts.append({"use_fp16": base_kwargs.get("use_fp16", False)})

    last_error: Exception | None = None
    for kwargs in attempts:
        try:
            return factory(model_source, **kwargs)
        except TypeError as exc:
            last_error = exc
            continue
        except Exception as exc:  # pragma: no cover - depends on optional dependency
            last_error = exc
            if kwargs.get("local_files_only"):
                continue
            break

    raise VendorFlagEmbeddingError(f"failed to load model: {display_name}") from last_error


def create_flag_auto_model(
    model_name: str,
    *,
    device: str = "cpu",
    use_fp16: bool = False,
    hf_cache: str | Path | None = None,
) -> object:
    cache_path = _apply_hf_cache(hf_cache)
    local_snapshot = _resolve_local_snapshot_path(model_name, cache_path)
    model_source = str(local_snapshot or model_name)
    FlagAutoModel = _load_flag_auto_model()
    kwargs = {"use_fp16": use_fp16}
    if device:
        kwargs["devices"] = device
    if local_snapshot is not None:
        model_class = _embedder_model_class_for(model_name)
        if model_class is not None:
            kwargs["model_class"] = model_class
    try:
        return _invoke_with_fallback(
            FlagAutoModel.from_finetuned,
            model_source,
            display_name=model_name,
            base_kwargs=kwargs,
            cache_path=cache_path,
        )
    except VendorFlagEmbeddingError as exc:  # pragma: no cover - depends on optional dependency
        raise VendorFlagEmbeddingError(f"failed to create FlagAutoModel: {model_name}") from exc


def create_flag_reranker(
    model_name: str,
    *,
    device: str = "cpu",
    use_fp16: bool = False,
    hf_cache: str | Path | None = None,
) -> object:
    cache_path = _apply_hf_cache(hf_cache)
    model_source = str(_resolve_local_snapshot_path(model_name, cache_path) or model_name)
    FlagReranker = _load_flag_reranker()
    kwargs = {"use_fp16": use_fp16}
    if device:
        kwargs["devices"] = device
    try:
        return _invoke_with_fallback(
            FlagReranker,
            model_source,
            display_name=model_name,
            base_kwargs=kwargs,
            cache_path=cache_path,
        )
    except VendorFlagEmbeddingError as exc:  # pragma: no cover - depends on optional dependency
        raise VendorFlagEmbeddingError(f"failed to create FlagReranker: {model_name}") from exc
