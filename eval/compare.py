from __future__ import annotations

import json
from pathlib import Path

from .index_stats import compare_index_stats_payloads

_BENCHMARK_METRICS = (
    "recall_at_k",
    "mrr",
    "abstain_accuracy",
    "abstain_precision",
    "abstain_recall",
    "false_abstain_rate",
    "false_answer_rate",
    "evidence_hit_rate",
    "evidence_source_recall",
    "source_count_satisfaction_rate",
    "expected_term_coverage",
    "avg_search_latency_ms",
    "avg_ask_latency_ms",
)

_CASE_FIELDS = (
    "abstained",
    "abstain_correct",
    "search_hit",
    "rank",
    "source_count",
    "matched_source_count",
    "evidence_hit",
    "expected_term_coverage",
    "top_file_path",
    "top_location",
)


def _round_or_none(value: object) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def load_json_payload(path: str | Path) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _metric_delta(baseline: object, candidate: object) -> dict[str, object]:
    if baseline is None or candidate is None:
        return {
            "baseline": baseline,
            "candidate": candidate,
            "delta": None,
        }
    return {
        "baseline": baseline,
        "candidate": candidate,
        "delta": _round_or_none(float(candidate) - float(baseline)),
    }


def _compare_breakdown(
    baseline: dict[str, object],
    candidate: dict[str, object],
) -> dict[str, object]:
    rows: dict[str, dict[str, object]] = {}
    for name in sorted(set(baseline) | set(candidate)):
        baseline_row = dict(baseline.get(name) or {})
        candidate_row = dict(candidate.get(name) or {})
        rows[name] = {
            metric: _metric_delta(baseline_row.get(metric), candidate_row.get(metric))
            for metric in _BENCHMARK_METRICS
            if metric in baseline_row or metric in candidate_row
        }
    return rows


def compare_benchmark_payloads(
    baseline: dict[str, object],
    candidate: dict[str, object],
) -> dict[str, object]:
    overall = {metric: _metric_delta(baseline.get(metric), candidate.get(metric)) for metric in _BENCHMARK_METRICS}

    baseline_cases = {str(item.get("id") or ""): item for item in baseline.get("case_results") or [] if item.get("id")}
    candidate_cases = {str(item.get("id") or ""): item for item in candidate.get("case_results") or [] if item.get("id")}
    case_changes: list[dict[str, object]] = []
    for case_id in sorted(set(baseline_cases) | set(candidate_cases)):
        baseline_case = dict(baseline_cases.get(case_id) or {})
        candidate_case = dict(candidate_cases.get(case_id) or {})
        changed_fields: dict[str, dict[str, object]] = {}
        for field in _CASE_FIELDS:
            if baseline_case.get(field) != candidate_case.get(field):
                changed_fields[field] = {
                    "baseline": baseline_case.get(field),
                    "candidate": candidate_case.get(field),
                }
        if changed_fields:
            case_changes.append(
                {
                    "id": case_id,
                    "question": candidate_case.get("question") or baseline_case.get("question"),
                    "case_type": candidate_case.get("case_type") or baseline_case.get("case_type"),
                    "tags": candidate_case.get("tags") or baseline_case.get("tags") or [],
                    "changes": changed_fields,
                }
            )

    return {
        "overall": overall,
        "by_type": _compare_breakdown(dict(baseline.get("by_type") or {}), dict(candidate.get("by_type") or {})),
        "by_tag": _compare_breakdown(dict(baseline.get("by_tag") or {}), dict(candidate.get("by_tag") or {})),
        "case_changes": case_changes,
    }


def build_comparison_report(
    *,
    baseline_benchmark: dict[str, object] | None = None,
    candidate_benchmark: dict[str, object] | None = None,
    baseline_index_stats: dict[str, object] | None = None,
    candidate_index_stats: dict[str, object] | None = None,
) -> dict[str, object]:
    report: dict[str, object] = {}
    if baseline_benchmark is not None and candidate_benchmark is not None:
        report["benchmark"] = compare_benchmark_payloads(baseline_benchmark, candidate_benchmark)
    if baseline_index_stats is not None and candidate_index_stats is not None:
        report["index_stats"] = compare_index_stats_payloads(baseline_index_stats, candidate_index_stats)
    return report

