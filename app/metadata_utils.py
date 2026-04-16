from __future__ import annotations

from pathlib import PurePath
from typing import Mapping, Sequence

COMMON_QUERY_STOPWORDS = frozenset(
    {
        "什么",
        "哪些",
        "哪种",
        "哪几种",
        "哪个",
        "知识库",
        "笔记",
        "分类",
        "目录",
        "专题",
        "文档",
        "资料",
        "内容",
        "文章",
        "里",
        "里面",
        "中",
        "内",
        "下",
        "的",
    }
)

METADATA_CONSTRAINT_STOPWORDS = COMMON_QUERY_STOPWORDS | {
    "哪篇",
    "有没有",
    "有没",
    "讲",
    "介绍",
}

LOOKUP_QUERY_STOPWORDS = COMMON_QUERY_STOPWORDS | {
    "查看",
    "支持",
    "对应",
    "相关",
    "可以",
    "用于",
    "表示",
    "命令",
    "参数",
    "宏",
    "文件类型",
    "类型",
    "信息",
    "当前",
    "常用",
    "调试",
    "问题",
    "缺点",
    "优点",
    "价值",
    "作用",
}

DEFAULT_METADATA_SCALAR_FIELDS = (
    "relative_path",
    "front_matter_title",
    "front_matter_category",
    "front_matter_origin_path",
)
DEFAULT_METADATA_SEQUENCE_FIELDS = (
    "front_matter_aliases",
    "front_matter_tags",
    "path_segments",
)
FTS_METADATA_EXTRA_SCALAR_FIELDS = ("front_matter_corpus",)
CATEGORY_METADATA_SCALAR_FIELDS = ("front_matter_category",)
CATEGORY_METADATA_SEQUENCE_FIELDS = ("path_segments",)
CATEGORY_METADATA_MAX_SEQUENCE_ITEMS = {"path_segments": 1}


def normalize_metadata(metadata: Mapping[str, object] | object | None) -> dict[str, object]:
    if isinstance(metadata, Mapping):
        return dict(metadata)
    return {}


def _append_cleaned_value(parts: list[str], value: object, *, seen: set[str] | None = None) -> None:
    cleaned = str(value).strip()
    if not cleaned:
        return
    if seen is not None:
        if cleaned in seen:
            return
        seen.add(cleaned)
    parts.append(cleaned)


def metadata_text_values(
    metadata: Mapping[str, object] | object | None,
    *,
    scalar_fields: Sequence[str] = DEFAULT_METADATA_SCALAR_FIELDS,
    sequence_fields: Sequence[str] = DEFAULT_METADATA_SEQUENCE_FIELDS,
    extra_scalar_fields: Sequence[str] = (),
    max_sequence_items: Mapping[str, int] | None = None,
    dedupe: bool = False,
) -> tuple[str, ...]:
    normalized = normalize_metadata(metadata)
    parts: list[str] = []
    seen = set() if dedupe else None

    for key in tuple(scalar_fields) + tuple(extra_scalar_fields):
        value = normalized.get(key)
        if value is None:
            continue
        _append_cleaned_value(parts, value, seen=seen)

    for key in sequence_fields:
        raw = normalized.get(key)
        if isinstance(raw, str):
            _append_cleaned_value(parts, raw, seen=seen)
            continue
        if not isinstance(raw, Sequence):
            continue
        limit = None if max_sequence_items is None else max_sequence_items.get(key)
        items = raw if limit is None else raw[:limit]
        for item in items:
            _append_cleaned_value(parts, item, seen=seen)

    return tuple(parts)


def chunk_text_values(
    chunk: object,
    *,
    include_content: bool = False,
    include_title_path: bool = False,
    include_file_path: bool = False,
    include_file_stem: bool = False,
    include_file_path_parts: int = 0,
    scalar_fields: Sequence[str] = DEFAULT_METADATA_SCALAR_FIELDS,
    sequence_fields: Sequence[str] = DEFAULT_METADATA_SEQUENCE_FIELDS,
    extra_scalar_fields: Sequence[str] = (),
    max_sequence_items: Mapping[str, int] | None = None,
    dedupe: bool = False,
) -> tuple[str, ...]:
    parts: list[str] = []
    seen = set() if dedupe else None

    if include_content:
        _append_cleaned_value(parts, getattr(chunk, "content", ""), seen=seen)

    if include_title_path:
        for title in getattr(chunk, "title_path", ()) or ():
            _append_cleaned_value(parts, title, seen=seen)

    file_path = str(getattr(chunk, "file_path", "") or "").strip()
    if include_file_path and file_path:
        _append_cleaned_value(parts, file_path, seen=seen)

    if file_path:
        pure_path = PurePath(file_path.replace("\\", "/"))
        if include_file_stem:
            _append_cleaned_value(parts, pure_path.stem, seen=seen)
        if include_file_path_parts > 0:
            for segment in pure_path.parts[-include_file_path_parts:]:
                if segment in {"/", "\\"}:
                    continue
                _append_cleaned_value(parts, segment, seen=seen)

    metadata_values = metadata_text_values(
        getattr(chunk, "metadata", None),
        scalar_fields=scalar_fields,
        sequence_fields=sequence_fields,
        extra_scalar_fields=extra_scalar_fields,
        max_sequence_items=max_sequence_items,
        dedupe=False,
    )
    for value in metadata_values:
        _append_cleaned_value(parts, value, seen=seen)

    return tuple(parts)
