from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from app.store import tokenize_fts

_LOW_SIGNAL_TOKENS = {
    "什么",
    "哪些",
    "哪种",
    "哪几种",
    "为何",
    "为什么",
    "如何",
    "怎么",
    "有没有",
    "介绍",
    "一下",
    "一下子",
    "请问",
    "的",
    "了",
    "吗",
    "呢",
    "各",
    "各有",
    "有",
    "有什么",
    "是",
    "包括",
    "机制",
    "价值",
    "作用",
    "问题",
    "优点",
    "缺点",
    "改进",
    "思路",
    "场景",
    "概念",
    "原理",
    "基础",
    "核心",
    "关键",
    "详细",
    "常见",
    "主要",
    "相比",
    "区别",
    "不同",
    "比较",
    "对比",
    "步骤",
    "安装",
    "配置",
    "使用",
}
_EXISTENCE_HINTS = ("有没有", "有无", "是否有", "哪篇", "哪条", "哪一篇")
_COMPARISON_HINTS = ("相比", "区别", "不同", "优缺点", "优点", "缺点", "比较", "对比")
_PROCEDURE_HINTS = ("如何", "怎么", "步骤", "安装", "配置", "使用", "做法")
_LOOKUP_HINTS = (
    "缩写",
    "简称",
    "哪个命令",
    "什么命令",
    "命令可以",
    "哪些参数",
    "什么参数",
    "对应哪些宏",
    "什么文件类型",
    "文件类型",
)
_METADATA_HINTS = ("分类", "目录", "专题", "哪篇", "里有没有", "里面有没有", "集合", "笔记里")
_PUNCT_RE = re.compile(r"[\s\u3000,，.。!！?？:：;；、'\"“”‘’()\[\]{}<>《》]+")
_TOKEN_SIGNAL_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9_]+")
DEFAULT_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("2pc", "两阶段提交", "两阶段提交协议"),
    ("3pc", "三阶段提交"),
    ("hlc", "hybrid logical clock", "混合逻辑时钟"),
    ("aoi", "area of interest", "感兴趣的区域"),
    ("gdb", "gnu debugger", "调试器"),
    ("subagent", "sub agent", "子代理"),
)


@dataclass(slots=True)
class QueryProfile:
    canonical_query: str = ""
    query_type: str = "definition"
    route_policy: str = "balanced"
    metadata_focus: bool = False
    requires_multi_source: bool = False
    anchor_terms: tuple[str, ...] = ()
    comparison_terms: tuple[str, ...] = ()
    alias_subject_terms: tuple[str, ...] = ()


def _normalize_text(value: str) -> str:
    return value.strip().casefold()


def _dedupe_texts(values: Sequence[str], *, limit: int) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        marker = cleaned.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(cleaned)
        if len(unique) >= limit:
            break
    return tuple(unique)


def normalize_alias_groups(alias_groups: Sequence[Sequence[str]] | None = None) -> tuple[tuple[str, ...], ...]:
    groups = alias_groups or DEFAULT_ALIAS_GROUPS
    normalized_groups: list[tuple[str, ...]] = []
    seen_groups: set[tuple[str, ...]] = set()
    for group in groups:
        if not isinstance(group, Sequence) or isinstance(group, str):
            continue
        deduped: list[str] = []
        seen_items: set[str] = set()
        for alias in group:
            cleaned = str(alias).strip().casefold()
            marker = cleaned
            if not cleaned or marker in seen_items:
                continue
            seen_items.add(marker)
            deduped.append(cleaned)
        if len(deduped) < 2:
            continue
        deduped_key = tuple(sorted(alias.casefold() for alias in deduped))
        if deduped_key in seen_groups:
            continue
        seen_groups.add(deduped_key)
        normalized_groups.append(tuple(deduped))
    return tuple(normalized_groups)


def build_alias_groups_from_front_matter(document_metadatas: Sequence[dict[str, object]]) -> tuple[tuple[str, ...], ...]:
    dynamic_groups: list[tuple[str, ...]] = []
    for metadata in document_metadatas:
        if not isinstance(metadata, dict):
            continue
        front_matter = metadata.get("front_matter")
        if not isinstance(front_matter, dict):
            continue
        aliases = front_matter.get("aliases")
        if isinstance(aliases, str):
            aliases = [aliases]
        if not isinstance(aliases, Sequence):
            continue
        dynamic_groups.append(tuple(str(alias).strip() for alias in aliases if str(alias).strip()))
    return normalize_alias_groups((*DEFAULT_ALIAS_GROUPS, *dynamic_groups))


def _extract_anchor_terms(text: str, *, limit: int = 4) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for token in tokenize_fts(text).split():
        cleaned = token.strip()
        if not cleaned or not _TOKEN_SIGNAL_RE.fullmatch(cleaned) or cleaned in _LOW_SIGNAL_TOKENS or cleaned in seen:
            continue
        seen.add(cleaned)
        terms.append(cleaned)
        if len(terms) >= limit:
            break
    return tuple(terms)


def _detect_query_type(text: str) -> str:
    normalized = _normalize_text(text)
    if any(hint in normalized for hint in _COMPARISON_HINTS):
        return "comparison"
    if any(hint in normalized for hint in _EXISTENCE_HINTS):
        return "existence"
    if any(hint in normalized for hint in _PROCEDURE_HINTS):
        return "procedure"
    if any(hint in normalized for hint in _LOOKUP_HINTS):
        return "lookup"
    return "definition"


def _expand_alias_variants(query: str, *, alias_groups: Sequence[Sequence[str]] | None = None) -> tuple[str, ...]:
    normalized = _normalize_text(query)
    variants: list[str] = []
    for group in normalize_alias_groups(alias_groups):
        matched = next((alias for alias in group if alias in normalized), None)
        if not matched:
            continue
        for alias in group:
            if alias == matched:
                continue
            candidate = re.sub(re.escape(matched), alias, normalized, count=1)
            if candidate and candidate != normalized:
                variants.append(candidate)
    return _dedupe_texts(variants, limit=4)


def extract_alias_subject_terms(text: str, alias_groups: Sequence[Sequence[str]] | None = None) -> tuple[str, ...]:
    normalized = _normalize_text(text)
    matched: list[str] = []
    seen: set[str] = set()
    for group in normalize_alias_groups(alias_groups):
        if not any(alias in normalized for alias in group):
            continue
        for alias in group:
            if alias in seen:
                continue
            seen.add(alias)
            matched.append(alias)
    return tuple(matched)


def analyze_query_profile(
    question: str | None,
    queries: Sequence[str],
    *,
    alias_groups: Sequence[Sequence[str]] | None = None,
) -> QueryProfile:
    normalized_queries = tuple(query.strip() for query in queries if query and query.strip())
    primary = (question or "").strip() or (normalized_queries[0] if normalized_queries else "")
    joined = " ".join((primary, *normalized_queries))
    query_type = _detect_query_type(primary)
    metadata_focus = any(hint in primary for hint in _METADATA_HINTS)
    anchor_terms = _extract_anchor_terms(joined)
    comparison_terms = anchor_terms[: min(4, len(anchor_terms))] if query_type == "comparison" else ()
    route_policy = {
        "comparison": "comparison-diverse",
        "existence": "existence-precise",
        "procedure": "procedure-semantic",
        "lookup": "lookup-precise",
    }.get(query_type, "balanced")
    return QueryProfile(
        canonical_query=primary,
        query_type=query_type,
        route_policy=route_policy,
        metadata_focus=metadata_focus,
        requires_multi_source=(query_type == "comparison"),
        anchor_terms=anchor_terms,
        comparison_terms=comparison_terms,
        alias_subject_terms=extract_alias_subject_terms(joined, alias_groups=alias_groups),
    )


def build_query_variants(
    profile: QueryProfile,
    queries: Sequence[str],
    *,
    alias_groups: Sequence[Sequence[str]] | None = None,
) -> tuple[str, ...]:
    normalized = tuple(query.strip() for query in queries if query and query.strip())
    if not normalized:
        return ()

    variants: list[str] = []
    if profile.canonical_query.strip():
        variants.append(profile.canonical_query.strip())
    variants.extend(normalized)
    if len(normalized) == 1:
        query = normalized[0]
        compact = " ".join(part for part in _PUNCT_RE.split(query) if part)
        if compact:
            variants.append(compact)
        keywords = " ".join(_extract_anchor_terms(query, limit=6))
        if keywords:
            variants.append(keywords)
    for query in normalized:
        variants.extend(_expand_alias_variants(query, alias_groups=alias_groups))

    if profile.query_type == "comparison":
        if profile.comparison_terms:
            variants.append(" ".join(profile.comparison_terms))
            variants.extend(profile.comparison_terms)
    elif profile.query_type in {"existence", "procedure"} and profile.anchor_terms:
        variants.append(" ".join(profile.anchor_terms))

    limit = 7 if profile.query_type in {"comparison", "procedure"} or profile.metadata_focus else 5
    return _dedupe_texts(variants, limit=limit)


def route_retrieval(
    profile: QueryProfile,
    *,
    default_recall_top_k: int,
    default_rerank_top_k: int,
    recall_top_k: int | None = None,
    rerank_top_k: int | None = None,
) -> tuple[int, int]:
    routed_recall = default_recall_top_k if recall_top_k is None else int(recall_top_k)
    routed_rerank = default_rerank_top_k if rerank_top_k is None else int(rerank_top_k)

    if profile.query_type == "comparison":
        routed_recall = max(routed_recall, 24)
        routed_rerank = max(routed_rerank, 8)
    elif profile.query_type == "procedure":
        routed_recall = max(routed_recall, 22)
        routed_rerank = max(routed_rerank, 8)
    elif profile.metadata_focus:
        routed_recall = max(routed_recall, 22)
        routed_rerank = max(routed_rerank, 8)

    return routed_recall, routed_rerank
