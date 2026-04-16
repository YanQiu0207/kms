from __future__ import annotations

from eval.compare import build_comparison_report, compare_benchmark_payloads


def test_compare_benchmark_payloads_reports_overall_and_case_diffs():
    baseline = {
        "recall_at_k": 1.0,
        "mrr": 0.5,
        "false_answer_rate": 0.0,
        "by_type": {
            "rewrite": {
                "recall_at_k": 1.0,
                "mrr": 0.5,
            }
        },
        "by_tag": {
            "ai": {
                "recall_at_k": 1.0,
                "mrr": 0.5,
            }
        },
        "case_results": [
            {
                "id": "case-1",
                "question": "q1",
                "case_type": "rewrite",
                "tags": ["ai"],
                "abstained": False,
                "abstain_correct": True,
                "search_hit": True,
                "rank": 2,
                "source_count": 1,
                "matched_source_count": 1,
                "evidence_hit": True,
                "expected_term_coverage": 0.5,
                "top_file_path": "a.md",
                "top_location": "a.md:1-2",
            }
        ],
    }
    candidate = {
        "recall_at_k": 1.0,
        "mrr": 1.0,
        "false_answer_rate": 0.0,
        "by_type": {
            "rewrite": {
                "recall_at_k": 1.0,
                "mrr": 1.0,
            }
        },
        "by_tag": {
            "ai": {
                "recall_at_k": 1.0,
                "mrr": 1.0,
            }
        },
        "case_results": [
            {
                "id": "case-1",
                "question": "q1",
                "case_type": "rewrite",
                "tags": ["ai"],
                "abstained": False,
                "abstain_correct": True,
                "search_hit": True,
                "rank": 1,
                "source_count": 2,
                "matched_source_count": 1,
                "evidence_hit": True,
                "expected_term_coverage": 1.0,
                "top_file_path": "a.md",
                "top_location": "a.md:3-4",
            }
        ],
    }

    diff = compare_benchmark_payloads(baseline, candidate)

    assert diff["overall"]["mrr"]["delta"] == 0.5
    assert diff["by_type"]["rewrite"]["mrr"]["candidate"] == 1.0
    assert len(diff["case_changes"]) == 1
    assert diff["case_changes"][0]["changes"]["rank"]["baseline"] == 2
    assert diff["case_changes"][0]["changes"]["expected_term_coverage"]["candidate"] == 1.0


def test_build_comparison_report_combines_sections():
    report = build_comparison_report(
        baseline_benchmark={"recall_at_k": 0.5, "case_results": [], "by_type": {}, "by_tag": {}},
        candidate_benchmark={"recall_at_k": 1.0, "case_results": [], "by_type": {}, "by_tag": {}},
        baseline_index_stats={"document_count": 1, "chunk_count": 2, "exact_duplicate_groups": 0, "exact_duplicate_chunk_count": 0, "exact_duplicate_chunk_ratio": 0.0, "chunk_length_chars": {}, "chunk_token_count": {}, "chunks_per_document": {}, "by_source": []},
        candidate_index_stats={"document_count": 1, "chunk_count": 3, "exact_duplicate_groups": 0, "exact_duplicate_chunk_count": 0, "exact_duplicate_chunk_ratio": 0.0, "chunk_length_chars": {}, "chunk_token_count": {}, "chunks_per_document": {}, "by_source": []},
    )

    assert "benchmark" in report
    assert "index_stats" in report
    assert report["benchmark"]["overall"]["recall_at_k"]["delta"] == 0.5
    assert report["index_stats"]["chunk_count"]["delta"] == 1.0
