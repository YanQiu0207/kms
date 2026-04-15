from __future__ import annotations

import gc


def best_effort_close(resource: object | None) -> None:
    if resource is None:
        return

    for method_name in ("close", "shutdown"):
        method = getattr(resource, method_name, None)
        if not callable(method):
            continue
        try:
            method()
        except Exception:
            pass
        return


def best_effort_release_runtime_resources() -> None:
    gc.collect()

    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return

    cuda = getattr(torch, "cuda", None)
    if cuda is None:
        return

    try:
        if not cuda.is_available():
            return
        empty_cache = getattr(cuda, "empty_cache", None)
        if callable(empty_cache):
            empty_cache()
        ipc_collect = getattr(cuda, "ipc_collect", None)
        if callable(ipc_collect):
            ipc_collect()
    except Exception:
        return
