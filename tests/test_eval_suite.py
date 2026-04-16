from __future__ import annotations

import json

from eval.benchmark import BenchmarkSummary
from eval.suite import evaluate_suite_entry, export_failure_records, load_suite_entries, BenchmarkSuiteEntry


def _summary(**overrides) -> BenchmarkSummary:
    payload = {
        "total_cases": 2,
        "answered_cases": 1,
        "abstain_cases": 1,
        "recall_at_k": 1.0,
        "mrr": 1.0,
        "abstain_accuracy": 1.0,
        "abstain_precision": 1.0,
        "abstain_recall": 1.0,
        "false_abstain_rate": 0.0,
        "false_answer_rate": 0.0,
        "evidence_hit_rate": 1.0,
        "evidence_source_recall": 1.0,
        "source_count_satisfaction_rate": 1.0,
        "expected_term_coverage": 1.0,
        "avg_search_latency_ms": 10.0,
        "avg_ask_latency_ms": 20.0,
        "case_results": [],
        "by_type": {},
        "by_tag": {},
    }
    payload.update(overrides)
    return BenchmarkSummary(**payload)


def test_load_suite_entries_supports_dict_root(tmp_path):
    path = tmp_path / "suite.json"
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "name": "demo",
                        "benchmark_path": "eval/demo.jsonl",
                        "config_path": "config.yaml",
                        "gate": False,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    entries = load_suite_entries(path)

    assert len(entries) == 1
    assert entries[0].name == "demo"
    assert entries[0].gate is False
    assert entries[0].base_url == ""


def test_load_suite_entries_supports_base_url(tmp_path):
    path = tmp_path / "suite.json"
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "name": "demo",
                        "benchmark_path": "eval/demo.jsonl",
                        "base_url": "http://127.0.0.1:49153",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    entries = load_suite_entries(path)

    assert entries[0].base_url == "http://127.0.0.1:49153"


def test_evaluate_suite_entry_reports_metric_failures():
    entry = BenchmarkSuiteEntry(name="demo", benchmark_path="eval/demo.jsonl")
    summary = _summary(mrr=0.8, false_answer_rate=0.2)

    result = evaluate_suite_entry(entry, summary)

    assert result.passed is False
    assert "mrr 0.8 < 1.0" in result.failing_checks
    assert "false_answer_rate 0.2 > 0.0" in result.failing_checks


def test_export_failure_records_collects_abstain_and_retrieval_failures():
    payload = {
        "case_results": [
            {
                "id": "case-1",
                "question": "Q1",
                "case_type": "lookup",
                "tags": ["demo"],
                "linked_issue_ids": ["ISSUE-1"],
                "should_abstain": False,
                "abstained": True,
                "search_hit": False,
                "source_count_ok": False,
                "abstain_reason": "query_term_coverage_below_threshold",
                "top_file_path": "E:/notes/demo.md",
                "rank": None,
            },
            {
                "id": "case-2",
                "question": "Q2",
                "case_type": "abstain",
                "tags": ["demo"],
                "should_abstain": True,
                "abstained": True,
                "search_hit": False,
                "source_count_ok": None,
            },
        ]
    }

    records = export_failure_records(payload, suite_name="demo-suite")

    assert len(records) == 1
    assert records[0]["suite_name"] == "demo-suite"
    assert records[0]["linked_issue_ids"] == ["ISSUE-1"]
    assert records[0]["reasons"] == [
        "abstain_mismatch",
        "retrieval_miss",
        "source_count_below_expectation",
    ]
