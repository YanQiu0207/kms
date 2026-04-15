from __future__ import annotations

from functools import lru_cache
from typing import Sequence


@lru_cache(maxsize=1)
def _load_jieba():
    try:
        import jieba  # type: ignore[import-not-found]
    except ImportError:
        return None
    return jieba


def cut_tokens(text: str) -> Sequence[str] | None:
    jieba = _load_jieba()
    if jieba is None:
        return None
    try:
        return jieba.lcut(text, cut_all=False)
    except Exception:
        return None
