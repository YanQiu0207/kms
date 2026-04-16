from __future__ import annotations

from app.answer import (
    AbstainThresholds,
    CitationCheckConfig,
    CitationVerifierImpl,
    PromptAssemblerImpl,
    build_prompt_package,
    evaluate_abstain,
    extract_cited_chunk_ids,
    verify_citations,
)
from app.retrieve.contracts import RetrievedChunk


def test_prompt_assembler_builds_direct_ask_payload():
    chunks = [
        RetrievedChunk(
            document_id="doc-1",
            content="个人知识库需要混合检索。",
            score=0.82,
            metadata={
                "chunk_id": "notes/rag.md#7",
                "file_path": "notes/rag.md",
                "title_path": ["RAG", "Hybrid Retrieval"],
                "start_line": 12,
                "end_line": 18,
            },
        ),
        RetrievedChunk(
            document_id="doc-2",
            content="向量检索不能覆盖所有精确命中场景。",
            score=0.77,
            metadata={
                "chunk_id": "notes/rag.md#4",
                "file_path": "notes/rag.md",
                "title_path": ["RAG"],
                "start_line": 20,
                "end_line": 26,
            },
        ),
    ]

    package = PromptAssemblerImpl(
        thresholds=AbstainThresholds(top1_min=0.2, top3_avg_min=0.2, min_hits=1, min_total_chars=1),
    ).build("为什么个人知识库不能只做向量检索？", chunks)

    assert not package.abstained
    assert package.prompt
    assert "为什么个人知识库不能只做向量检索？" in package.prompt
    assert "[证据 1]" in package.prompt
    assert "来源列表" in package.prompt
    assert "rag.md:12-18" in package.prompt
    assert "[1]" in package.prompt
    assert "chunk_id=" not in package.prompt
    assert package.chunks[0].document_id == "doc-1"


def test_prompt_assembler_abstains_on_low_top1_score():
    chunk = RetrievedChunk(
        document_id="doc-1",
        content="内容很短但可用。",
        score=0.12,
        metadata={"chunk_id": "notes/rag.md#1"},
    )

    package = build_prompt_package("问题是什么？", [chunk])

    assert package.abstained is True
    assert package.prompt == ""
    assert package.abstain_reason == "top1_score_below_threshold"


def test_guardrail_evaluation_reports_scores():
    chunks = [
        RetrievedChunk(document_id="doc-1", content="甲" * 120, score=0.8),
        RetrievedChunk(document_id="doc-2", content="乙" * 110, score=0.7),
    ]

    decision = evaluate_abstain(chunks, AbstainThresholds(top1_min=0.1, top3_avg_min=0.1, min_hits=1, min_total_chars=1))

    assert decision.abstained is False
    assert decision.confidence > 0.0
    assert decision.top1_score == 0.8
    assert decision.hit_count == 2


def test_guardrail_rejects_single_substantive_hit_plus_metadata_shell():
    chunks = [
        RetrievedChunk(
            document_id="doc-1",
            file_path="E:/github/mykms/data/corpora/e-notes-frontmatter-v1/数据库问题.md",
            content="业务分库影响需要同时查询不同数据库中表的 sql 语句。",
            score=0.48,
            metadata={
                "metadata_constraint_passed": True,
                "metadata_constraint_coverage": 1.0,
                "relative_path": "数据库问题.md",
                "front_matter_category": "数据库",
            },
        ),
        RetrievedChunk(
            document_id="doc-2",
            file_path="E:/github/mykms/data/corpora/e-notes-frontmatter-v1/数据库.md",
            content="# 数据库",
            score=0.40,
            metadata={
                "metadata_constraint_passed": True,
                "metadata_constraint_coverage": 1.0,
                "relative_path": "数据库.md",
                "front_matter_category": "数据库",
                "source_hits": ["semantic:q1"],
            },
        ),
    ]

    decision = evaluate_abstain(
        chunks,
        AbstainThresholds(top1_min=0.2, top3_avg_min=0.3, min_hits=2, min_total_chars=150),
    )

    assert decision.abstained is True
    assert decision.reason == "recall_hits_below_threshold"


def test_guardrail_allows_same_document_metadata_cluster_with_semantic_support():
    chunks = [
        RetrievedChunk(
            document_id="doc-1",
            file_path="E:/github/mykms/data/corpora/e-notes-frontmatter-v1/程序设计/对象池.md",
            title_path=("对象池",),
            content="# 对象池",
            score=0.4167,
            metadata={
                "metadata_constraint_passed": True,
                "metadata_constraint_coverage": 1.0,
                "relative_path": "程序设计/对象池.md",
                "front_matter_title": "对象池",
                "front_matter_category": "程序设计",
                "front_matter_aliases": ["对象池"],
                "front_matter_tags": ["程序设计", "对象池"],
                "path_segments": ["程序设计", "对象池.md"],
                "source_hits": [
                    "lexical:程序设计 对象 复用",
                    "lexical:程序设计 分类 对象复用",
                    "semantic:程序设计 对象 复用",
                ],
            },
        ),
        RetrievedChunk(
            document_id="doc-1",
            file_path="E:/github/mykms/data/corpora/e-notes-frontmatter-v1/程序设计/对象池.md",
            title_path=("对象池", "关键技术"),
            content="## 关键技术",
            score=0.3847,
            metadata={
                "metadata_constraint_passed": True,
                "metadata_constraint_coverage": 1.0,
                "relative_path": "程序设计/对象池.md",
                "front_matter_title": "对象池",
                "front_matter_category": "程序设计",
                "front_matter_aliases": ["对象池"],
                "front_matter_tags": ["程序设计", "对象池"],
                "path_segments": ["程序设计", "对象池.md"],
                "source_hits": [
                    "lexical:程序设计 对象 复用",
                    "lexical:程序设计 分类 对象复用",
                ],
            },
        ),
        RetrievedChunk(
            document_id="doc-1",
            file_path="E:/github/mykms/data/corpora/e-notes-frontmatter-v1/程序设计/对象池.md",
            title_path=("对象池", "测试"),
            content="## 测试",
            score=0.3839,
            metadata={
                "metadata_constraint_passed": True,
                "metadata_constraint_coverage": 1.0,
                "relative_path": "程序设计/对象池.md",
                "front_matter_title": "对象池",
                "front_matter_category": "程序设计",
                "front_matter_aliases": ["对象池"],
                "front_matter_tags": ["程序设计", "对象池"],
                "path_segments": ["程序设计", "对象池.md"],
                "source_hits": [
                    "lexical:程序设计 对象 复用",
                    "lexical:程序设计 分类 对象复用",
                ],
            },
        ),
    ]

    decision = evaluate_abstain(
        chunks,
        AbstainThresholds(top1_min=0.2, top3_avg_min=0.3, min_hits=2, min_total_chars=150),
    )

    assert decision.abstained is False
    assert decision.reason is None


def test_citation_verifier_matches_against_chunk_text_mapping():
    answer = "混合检索结合了词法与语义检索的优势 [notes/rag.md#7]。"
    used_chunk_ids = ["notes/rag.md#7"]
    texts = {
        "notes/rag.md#7": "混合检索结合了词法与语义检索的优势，它兼顾精确匹配和语义召回。",
    }

    result = verify_citations(answer, used_chunk_ids, texts)

    assert result.citation_unverified is False
    assert result.coverage >= 0.5
    assert result.matched_chunk_ids == ("notes/rag.md#7",)
    assert result.details[0].matched_ngrams > 0


def test_citation_verifier_can_be_backed_by_callable():
    verifier = CitationVerifierImpl(
        lambda chunk_id: "资料不足时应当直接拒答。" if chunk_id == "notes/rag.md#1" else None,
        CitationCheckConfig(min_ngram_len=4, coverage_threshold=0.5),
    )

    result = verifier.verify("资料不足时应当直接拒答。[notes/rag.md#1]", ["notes/rag.md#1"])

    assert result.citation_unverified is False
    assert extract_cited_chunk_ids("a [x] b [x] c") == ("x",)
