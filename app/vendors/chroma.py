from __future__ import annotations

from functools import lru_cache


class VendorChromaError(RuntimeError):
    """Raised when the Chroma vendor adapter cannot satisfy the request."""


@lru_cache(maxsize=1)
def _load_chromadb():
    try:
        import chromadb  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised only when dependency is absent
        raise VendorChromaError("chromadb is not installed") from exc
    return chromadb


@lru_cache(maxsize=4)
def get_persistent_client(persist_directory: str) -> object:
    chromadb = _load_chromadb()
    try:
        from chromadb.config import Settings  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - optional dependency surface
        raise VendorChromaError("chromadb Settings is unavailable") from exc

    try:
        return chromadb.Client(
            Settings(
                is_persistent=True,
                persist_directory=persist_directory,
            )
        )
    except Exception as exc:  # pragma: no cover - depends on optional dependency
        raise VendorChromaError("failed to create chromadb persistent client") from exc


def clear_persistent_client_cache() -> None:
    get_persistent_client.cache_clear()
