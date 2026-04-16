from __future__ import annotations

from app.query_understanding import (
    analyze_query_profile,
    build_alias_groups_from_front_matter,
    build_query_variants,
    route_retrieval,
)


def test_query_understanding_detects_comparison_and_route_policy():
    profile = analyze_query_profile("HLC 和 TrueTime 的区别是什么？", ("HLC 和 TrueTime 的区别是什么？",))

    assert profile.canonical_query == "HLC 和 TrueTime 的区别是什么？"
    assert profile.query_type == "comparison"
    assert profile.route_policy == "comparison-diverse"
    assert profile.requires_multi_source is True
    assert "hlc" in profile.comparison_terms
    assert "truetime" in profile.comparison_terms


def test_query_understanding_builds_alias_variants_for_two_phase_commit():
    profile = analyze_query_profile("两阶段提交的主要问题有哪些？", ("两阶段提交的主要问题有哪些？",))

    variants = build_query_variants(profile, ("两阶段提交的主要问题有哪些？",))

    assert "两阶段提交的主要问题有哪些？" in variants
    assert any("2pc" in variant.casefold() for variant in variants)


def test_query_understanding_builds_chinese_alias_variant_for_subagent():
    profile = analyze_query_profile("Claude Code 里 subagent 的基础概念是什么？", ("subagent 基础 概念",))

    variants = build_query_variants(profile, ("subagent 基础 概念",))

    assert any("子代理" in variant for variant in variants)
    assert "subagent" in profile.alias_subject_terms
    assert "子代理" in profile.alias_subject_terms


def test_query_understanding_extracts_alias_groups_from_front_matter():
    alias_groups = build_alias_groups_from_front_matter(
        [
            {
                "front_matter": {
                    "aliases": ["对象复用", "对象缓存", "池化分配"],
                }
            }
        ]
    )

    profile = analyze_query_profile("对象复用有什么好处？", ("对象复用 好处",), alias_groups=alias_groups)
    variants = build_query_variants(profile, ("对象复用 好处",), alias_groups=alias_groups)

    assert any("对象缓存" in variant for variant in variants)
    assert "对象复用" in profile.alias_subject_terms
    assert "对象缓存" in profile.alias_subject_terms


def test_query_understanding_keeps_canonical_question_for_multi_query_metadata_case():
    profile = analyze_query_profile("网络编程分类下有没有讲 timerfd？", ("网络编程 timerfd", "timerfd 定时器"))

    variants = build_query_variants(profile, ("网络编程 timerfd", "timerfd 定时器"))

    assert variants[0] == "网络编程分类下有没有讲 timerfd？"
    assert "网络编程 timerfd" in variants
    assert "timerfd 定时器" in variants


def test_query_understanding_routes_comparison_and_procedure_queries_more_aggressively():
    comparison = analyze_query_profile("HLC 和 TrueTime 的区别是什么？", ("HLC 和 TrueTime 的区别是什么？",))
    procedure = analyze_query_profile("Claude Code 的 settings 怎么配置？", ("Claude Code 的 settings 怎么配置？",))
    metadata_filter = analyze_query_profile("网络编程分类下有没有讲 timerfd？", ("网络编程 timerfd",))

    comparison_route = route_retrieval(
        comparison,
        default_recall_top_k=10,
        default_rerank_top_k=4,
    )
    procedure_route = route_retrieval(
        procedure,
        default_recall_top_k=10,
        default_rerank_top_k=4,
    )
    metadata_route = route_retrieval(
        metadata_filter,
        default_recall_top_k=10,
        default_rerank_top_k=4,
    )

    assert comparison_route == (24, 8)
    assert procedure_route == (22, 8)
    assert metadata_route == (22, 8)
