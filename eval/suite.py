from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

from app.config import load_config

from .benchmark import BenchmarkSummary, run_benchmark


def _round_metric(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


@dataclass(slots=True)
class BenchmarkSuiteEntry:
    name: str
    benchmark_path: str
    config_path: str = "config.yaml"
    base_url: str = ""
    reindex_mode: str | None = None
    gate: bool = True
    min_recall_at_k: float = 1.0
    min_mrr: float = 1.0
    min_abstain_accuracy: float = 1.0
    max_false_abstain_rate: float = 0.0
    max_false_answer_rate: float = 0.0
    output_path: str = ""
    notes: str = ""


@dataclass(slots=True)
class BenchmarkSuiteResult:
    name: str
    benchmark_path: str
    config_path: str
    gate: bool
    passed: bool
    notes: str
    summary: dict[str, object]
    failing_checks: list[str] = field(default_factory=list)
    failing_cases: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class BenchmarkSuiteSummary:
    total_entries: int
    gated_entries: int
    passed_entries: int
    passed_gated_entries: int
    suite_results: list[BenchmarkSuiteResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "total_entries": self.total_entries,
            "gated_entries": self.gated_entries,
            "passed_entries": self.passed_entries,
            "passed_gated_entries": self.passed_gated_entries,
            "suite_results": [item.to_dict() for item in self.suite_results],
        }


def load_suite_entries(path: str | Path) -> list[BenchmarkSuiteEntry]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw.get("entries") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("suite spec must be a list or an object with 'entries'")

    entries: list[BenchmarkSuiteEntry] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each suite entry must be an object")
        entries.append(
            BenchmarkSuiteEntry(
                name=str(item["name"]),
                benchmark_path=str(item["benchmark_path"]),
                config_path=str(item.get("config_path") or "config.yaml"),
                base_url=str(item.get("base_url") or ""),
                reindex_mode=str(item["reindex_mode"]) if item.get("reindex_mode") else None,
                gate=bool(item.get("gate", True)),
                min_recall_at_k=float(item.get("min_recall_at_k", 1.0)),
                min_mrr=float(item.get("min_mrr", 1.0)),
                min_abstain_accuracy=float(item.get("min_abstain_accuracy", 1.0)),
                max_false_abstain_rate=float(item.get("max_false_abstain_rate", 0.0)),
                max_false_answer_rate=float(item.get("max_false_answer_rate", 0.0)),
                output_path=str(item.get("output_path") or ""),
                notes=str(item.get("notes") or ""),
            )
        )
    return entries


def evaluate_suite_entry(entry: BenchmarkSuiteEntry, summary: BenchmarkSummary) -> BenchmarkSuiteResult:
    rendered = summary.to_dict()
    failing_checks: list[str] = []
    if summary.recall_at_k < entry.min_recall_at_k:
        failing_checks.append(
            f"recall_at_k {summary.recall_at_k} < {entry.min_recall_at_k}"
        )
    if summary.mrr < entry.min_mrr:
        failing_checks.append(f"mrr {summary.mrr} < {entry.min_mrr}")
    if summary.abstain_accuracy < entry.min_abstain_accuracy:
        failing_checks.append(
            f"abstain_accuracy {summary.abstain_accuracy} < {entry.min_abstain_accuracy}"
        )
    if summary.false_abstain_rate > entry.max_false_abstain_rate:
        failing_checks.append(
            f"false_abstain_rate {summary.false_abstain_rate} > {entry.max_false_abstain_rate}"
        )
    if summary.false_answer_rate > entry.max_false_answer_rate:
        failing_checks.append(
            f"false_answer_rate {summary.false_answer_rate} > {entry.max_false_answer_rate}"
        )

    failing_cases = export_failure_records(rendered, suite_name=entry.name)
    passed = not failing_checks
    return BenchmarkSuiteResult(
        name=entry.name,
        benchmark_path=entry.benchmark_path,
        config_path=entry.config_path,
        gate=entry.gate,
        passed=passed,
        notes=entry.notes,
        summary=rendered,
        failing_checks=failing_checks,
        failing_cases=failing_cases,
    )


def export_failure_records(
    benchmark_payload: dict[str, object],
    *,
    suite_name: str = "",
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for item in benchmark_payload.get("case_results", []):
        if not isinstance(item, dict):
            continue
        should_abstain = bool(item.get("should_abstain", False))
        abstained = bool(item.get("abstained", False))
        search_hit = bool(item.get("search_hit", False))
        source_count_ok = item.get("source_count_ok")

        reasons: list[str] = []
        if should_abstain != abstained:
            reasons.append("abstain_mismatch")
        if not should_abstain and not search_hit:
            reasons.append("retrieval_miss")
        if not should_abstain and source_count_ok is False:
            reasons.append("source_count_below_expectation")
        if not reasons:
            continue

        records.append(
            {
                "suite_name": suite_name,
                "id": item.get("id"),
                "question": item.get("question"),
                "case_type": item.get("case_type"),
                "tags": item.get("tags") or [],
                "linked_issue_ids": item.get("linked_issue_ids") or [],
                "reasons": reasons,
                "abstain_reason": item.get("abstain_reason"),
                "top_file_path": item.get("top_file_path"),
                "rank": item.get("rank"),
                "should_abstain": should_abstain,
                "abstained": abstained,
            }
        )
    return records


def run_benchmark_suite(
    entries: Sequence[BenchmarkSuiteEntry],
    *,
    base_url_override: str | None = None,
) -> BenchmarkSuiteSummary:
    results: list[BenchmarkSuiteResult] = []
    for entry in entries:
        resolved_base_url = base_url_override or entry.base_url or None
        summary = run_benchmark(
            entry.benchmark_path,
            config=None if resolved_base_url else load_config(entry.config_path),
            reindex_mode=entry.reindex_mode,
            base_url=resolved_base_url,
        )
        rendered = json.dumps(summary.to_dict(), ensure_ascii=False, indent=2)
        if entry.output_path:
            Path(entry.output_path).write_text(rendered, encoding="utf-8")
        results.append(evaluate_suite_entry(entry, summary))

    total_entries = len(results)
    gated_entries = sum(1 for item in results if item.gate)
    passed_entries = sum(1 for item in results if item.passed)
    passed_gated_entries = sum(1 for item in results if item.gate and item.passed)
    return BenchmarkSuiteSummary(
        total_entries=total_entries,
        gated_entries=gated_entries,
        passed_entries=passed_entries,
        passed_gated_entries=passed_gated_entries,
        suite_results=results,
    )
