from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Sequence

from app.config import AppConfig, load_config
from app.services import IndexingService, QueryService


def _round_metric(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _coerce_strings(values: Sequence[object] | None) -> tuple[str, ...]:
    if not values:
        return ()
    if isinstance(values, str):
        cleaned = values.strip()
        return (cleaned,) if cleaned else ()
    return tuple(str(value).strip() for value in values if str(value).strip())


def _normalize_path(value: object | None) -> str:
    return str(value or "").replace("\\", "/").strip()


def _normalize_text(value: object | None) -> str:
    return str(value or "").strip().casefold()


@dataclass(slots=True)
class BenchmarkCase:
    id: str
    question: str
    queries: tuple[str, ...]
    expected_chunk_ids: tuple[str, ...] = ()
    expected_file_paths: tuple[str, ...] = ()
    should_abstain: bool = False
    case_type: str = "lookup"
    tags: tuple[str, ...] = ()
    min_expected_sources: int = 0
    expected_terms: tuple[str, ...] = ()
    notes: str = ""


@dataclass(slots=True)
class BenchmarkCaseResult:
    id: str
    question: str
    case_type: str
    tags: tuple[str, ...]
    should_abstain: bool
    abstained: bool
    abstain_correct: bool
    search_latency_ms: float
    ask_latency_ms: float
    search_hit: bool
    rank: int | None
    mrr: float
    result_count: int
    source_count: int
    top_chunk_id: str | None = None
    top_file_path: str | None = None
    top_location: str | None = None
    confidence: float = 0.0
    abstain_reason: str | None = None
    expected_source_count: int = 0
    matched_source_count: int = 0
    evidence_hit: bool | None = None
    evidence_source_recall: float | None = None
    min_expected_sources: int = 0
    source_count_ok: bool | None = None
    expected_terms_total: int = 0
    matched_terms_count: int = 0
    expected_term_coverage: float | None = None


@dataclass(slots=True)
class MetricBreakdown:
    total_cases: int
    answered_cases: int
    abstain_cases: int
    recall_at_k: float
    mrr: float
    abstain_accuracy: float
    abstain_precision: float
    abstain_recall: float
    false_abstain_rate: float
    false_answer_rate: float
    evidence_hit_rate: float | None
    evidence_source_recall: float | None
    source_count_satisfaction_rate: float | None
    expected_term_coverage: float | None
    avg_search_latency_ms: float
    avg_ask_latency_ms: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class BenchmarkSummary:
    total_cases: int
    answered_cases: int
    abstain_cases: int
    recall_at_k: float
    mrr: float
    abstain_accuracy: float
    abstain_precision: float
    abstain_recall: float
    false_abstain_rate: float
    false_answer_rate: float
    evidence_hit_rate: float | None
    evidence_source_recall: float | None
    source_count_satisfaction_rate: float | None
    expected_term_coverage: float | None
    avg_search_latency_ms: float
    avg_ask_latency_ms: float
    case_results: list[BenchmarkCaseResult] = field(default_factory=list)
    by_type: dict[str, MetricBreakdown] = field(default_factory=dict)
    by_tag: dict[str, MetricBreakdown] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        payload = {
            "total_cases": self.total_cases,
            "answered_cases": self.answered_cases,
            "abstain_cases": self.abstain_cases,
            "recall_at_k": self.recall_at_k,
            "mrr": self.mrr,
            "abstain_accuracy": self.abstain_accuracy,
            "abstain_precision": self.abstain_precision,
            "abstain_recall": self.abstain_recall,
            "false_abstain_rate": self.false_abstain_rate,
            "false_answer_rate": self.false_answer_rate,
            "evidence_hit_rate": self.evidence_hit_rate,
            "evidence_source_recall": self.evidence_source_recall,
            "source_count_satisfaction_rate": self.source_count_satisfaction_rate,
            "expected_term_coverage": self.expected_term_coverage,
            "avg_search_latency_ms": self.avg_search_latency_ms,
            "avg_ask_latency_ms": self.avg_ask_latency_ms,
            "case_results": [asdict(item) for item in self.case_results],
            "by_type": {name: breakdown.to_dict() for name, breakdown in self.by_type.items()},
            "by_tag": {name: breakdown.to_dict() for name, breakdown in self.by_tag.items()},
        }
        return payload


def load_benchmark_cases(path: str | Path) -> list[BenchmarkCase]:
    cases: list[BenchmarkCase] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        raw = json.loads(stripped)
        case_type = str(raw.get("case_type") or raw.get("type") or "lookup").strip() or "lookup"
        min_expected_sources = raw.get("min_expected_sources", 0)
        cases.append(
            BenchmarkCase(
                id=str(raw["id"]),
                question=str(raw["question"]),
                queries=_coerce_strings(raw.get("queries")) or (str(raw["question"]).strip(),),
                expected_chunk_ids=_coerce_strings(raw.get("expected_chunk_ids")),
                expected_file_paths=tuple(_normalize_path(path) for path in _coerce_strings(raw.get("expected_file_paths"))),
                should_abstain=bool(raw.get("should_abstain", False)),
                case_type=case_type,
                tags=_coerce_strings(raw.get("tags")),
                min_expected_sources=max(int(min_expected_sources or 0), 0),
                expected_terms=_coerce_strings(raw.get("expected_terms")),
                notes=str(raw.get("notes") or "").strip(),
            )
        )
    return cases


def _match_rank(case: BenchmarkCase, results: Sequence[dict[str, object]]) -> int | None:
    expected_chunk_ids = set(case.expected_chunk_ids)
    expected_file_paths = set(case.expected_file_paths)
    for index, result in enumerate(results, start=1):
        chunk_id = str(result.get("chunk_id") or "")
        file_path = _normalize_path(result.get("file_path"))
        if expected_chunk_ids and chunk_id in expected_chunk_ids:
            return index
        if expected_file_paths and file_path in expected_file_paths:
            return index
    return None


def _expected_source_keys(case: BenchmarkCase) -> set[str]:
    keys = {f"chunk:{chunk_id}" for chunk_id in case.expected_chunk_ids}
    keys.update(f"file:{file_path}" for file_path in case.expected_file_paths)
    return keys


def _matched_source_keys(case: BenchmarkCase, sources: Sequence[dict[str, object]]) -> set[str]:
    matched: set[str] = set()
    expected_chunk_ids = set(case.expected_chunk_ids)
    expected_file_paths = set(case.expected_file_paths)
    for source in sources:
        chunk_id = str(source.get("chunk_id") or "")
        file_path = _normalize_path(source.get("file_path"))
        if expected_chunk_ids and chunk_id in expected_chunk_ids:
            matched.add(f"chunk:{chunk_id}")
        if expected_file_paths and file_path in expected_file_paths:
            matched.add(f"file:{file_path}")
    return matched


def _collect_source_text(sources: Sequence[dict[str, object]]) -> str:
    parts: list[str] = []
    for source in sources:
        text = str(source.get("text") or "").strip()
        if text:
            parts.append(text)
        title_path = source.get("title_path") or ()
        if isinstance(title_path, Sequence) and not isinstance(title_path, str):
            parts.extend(str(item).strip() for item in title_path if str(item).strip())
        file_path = str(source.get("file_path") or "").strip()
        if file_path:
            parts.append(Path(file_path).stem)
    return " ".join(parts)


def _expected_term_stats(case: BenchmarkCase, sources: Sequence[dict[str, object]]) -> tuple[int, int, float | None]:
    if not case.expected_terms:
        return 0, 0, None

    source_text = _normalize_text(_collect_source_text(sources))
    matched = sum(1 for term in case.expected_terms if _normalize_text(term) in source_text)
    total = len(case.expected_terms)
    return total, matched, _round_metric(_safe_ratio(matched, total))


def _compute_metrics(case_results: Sequence[BenchmarkCaseResult]) -> MetricBreakdown:
    total_cases = len(case_results)
    answered_cases = sum(1 for item in case_results if not item.should_abstain)
    abstain_cases = sum(1 for item in case_results if item.should_abstain)

    recall_hits = sum(1 for item in case_results if not item.should_abstain and item.search_hit)
    mrr_total = sum(item.mrr for item in case_results if not item.should_abstain)

    abstain_correct_total = sum(1 for item in case_results if item.abstain_correct)
    abstain_tp = sum(1 for item in case_results if item.should_abstain and item.abstained)
    abstain_fp = sum(1 for item in case_results if not item.should_abstain and item.abstained)
    abstain_fn = sum(1 for item in case_results if item.should_abstain and not item.abstained)

    evidence_cases = [item for item in case_results if not item.should_abstain and item.expected_source_count > 0]
    evidence_hit_cases = [item for item in evidence_cases if item.evidence_hit is not None]

    source_count_cases = [item for item in case_results if not item.should_abstain and item.min_expected_sources > 0]
    term_cases = [item for item in case_results if item.expected_terms_total > 0]

    return MetricBreakdown(
        total_cases=total_cases,
        answered_cases=answered_cases,
        abstain_cases=abstain_cases,
        recall_at_k=_round_metric(_safe_ratio(recall_hits, answered_cases)) or 0.0,
        mrr=_round_metric(_safe_ratio(mrr_total, answered_cases)) or 0.0,
        abstain_accuracy=_round_metric(_safe_ratio(abstain_correct_total, total_cases)) or 0.0,
        abstain_precision=_round_metric(_safe_ratio(abstain_tp, abstain_tp + abstain_fp)) or 0.0,
        abstain_recall=_round_metric(_safe_ratio(abstain_tp, abstain_cases)) or 0.0,
        false_abstain_rate=_round_metric(_safe_ratio(abstain_fp, answered_cases)) or 0.0,
        false_answer_rate=_round_metric(_safe_ratio(abstain_fn, abstain_cases)) or 0.0,
        evidence_hit_rate=_round_metric(_safe_ratio(sum(1 for item in evidence_hit_cases if item.evidence_hit), len(evidence_hit_cases)))
        if evidence_hit_cases
        else None,
        evidence_source_recall=_round_metric(
            _safe_ratio(
                sum(float(item.evidence_source_recall or 0.0) for item in evidence_cases),
                len(evidence_cases),
            )
        )
        if evidence_cases
        else None,
        source_count_satisfaction_rate=_round_metric(
            _safe_ratio(sum(1 for item in source_count_cases if item.source_count_ok), len(source_count_cases))
        )
        if source_count_cases
        else None,
        expected_term_coverage=_round_metric(
            _safe_ratio(sum(float(item.expected_term_coverage or 0.0) for item in term_cases), len(term_cases))
        )
        if term_cases
        else None,
        avg_search_latency_ms=round(_safe_ratio(sum(item.search_latency_ms for item in case_results), total_cases), 2),
        avg_ask_latency_ms=round(_safe_ratio(sum(item.ask_latency_ms for item in case_results), total_cases), 2),
    )


def _group_case_results(case_results: Sequence[BenchmarkCaseResult], *, key_getter) -> dict[str, MetricBreakdown]:
    grouped: dict[str, list[BenchmarkCaseResult]] = defaultdict(list)
    for item in case_results:
        keys = key_getter(item)
        for key in keys:
            grouped[key].append(item)
    return {name: _compute_metrics(items) for name, items in sorted(grouped.items())}


def run_benchmark(
    benchmark_path: str | Path,
    *,
    config: AppConfig | None = None,
    reindex_mode: str | None = None,
) -> BenchmarkSummary:
    settings = config or load_config()
    if reindex_mode:
        IndexingService(settings).index(reindex_mode)

    service = QueryService(settings)
    try:
        cases = load_benchmark_cases(benchmark_path)
        case_results: list[BenchmarkCaseResult] = []

        for case in cases:
            start = perf_counter()
            search_result = service.search(case.queries)
            search_latency_ms = (perf_counter() - start) * 1000.0

            start = perf_counter()
            ask_result = service.ask(case.question, queries=case.queries)
            ask_latency_ms = (perf_counter() - start) * 1000.0

            payload = search_result.to_payload()
            results = payload["results"]
            rank = _match_rank(case, results)
            search_hit = rank is not None
            mrr = 0.0 if rank is None else 1.0 / rank

            ask_sources = tuple(ask_result.sources)
            matched_source_keys = _matched_source_keys(case, ask_sources)
            expected_source_keys = _expected_source_keys(case)
            expected_source_count = len(expected_source_keys)
            matched_source_count = len(matched_source_keys)
            evidence_hit = matched_source_count > 0 if expected_source_count > 0 else None
            evidence_source_recall = (
                _round_metric(_safe_ratio(matched_source_count, expected_source_count)) if expected_source_count > 0 else None
            )

            expected_terms_total, matched_terms_count, expected_term_coverage = _expected_term_stats(case, ask_sources)
            source_count = len(ask_sources)
            source_count_ok = source_count >= case.min_expected_sources if case.min_expected_sources > 0 else None
            abstain_correct = ask_result.abstained is case.should_abstain

            top = results[0] if results else {}
            case_results.append(
                BenchmarkCaseResult(
                    id=case.id,
                    question=case.question,
                    case_type=case.case_type,
                    tags=case.tags,
                    should_abstain=case.should_abstain,
                    abstained=ask_result.abstained,
                    abstain_correct=abstain_correct,
                    search_latency_ms=round(search_latency_ms, 2),
                    ask_latency_ms=round(ask_latency_ms, 2),
                    search_hit=search_hit,
                    rank=rank,
                    mrr=_round_metric(mrr) or 0.0,
                    result_count=len(results),
                    source_count=source_count,
                    top_chunk_id=str(top.get("chunk_id")) if top else None,
                    top_file_path=_normalize_path(top.get("file_path")) if top else None,
                    top_location=str(top.get("location")) if top else None,
                    confidence=round(float(getattr(ask_result, "confidence", 0.0) or 0.0), 4),
                    abstain_reason=getattr(ask_result, "abstain_reason", None),
                    expected_source_count=expected_source_count,
                    matched_source_count=matched_source_count,
                    evidence_hit=evidence_hit,
                    evidence_source_recall=evidence_source_recall,
                    min_expected_sources=case.min_expected_sources,
                    source_count_ok=source_count_ok,
                    expected_terms_total=expected_terms_total,
                    matched_terms_count=matched_terms_count,
                    expected_term_coverage=expected_term_coverage,
                )
            )

        overall = _compute_metrics(case_results)
        by_type = _group_case_results(case_results, key_getter=lambda item: (item.case_type,) if item.case_type else ())
        by_tag = _group_case_results(case_results, key_getter=lambda item: item.tags)
        return BenchmarkSummary(
            total_cases=overall.total_cases,
            answered_cases=overall.answered_cases,
            abstain_cases=overall.abstain_cases,
            recall_at_k=overall.recall_at_k,
            mrr=overall.mrr,
            abstain_accuracy=overall.abstain_accuracy,
            abstain_precision=overall.abstain_precision,
            abstain_recall=overall.abstain_recall,
            false_abstain_rate=overall.false_abstain_rate,
            false_answer_rate=overall.false_answer_rate,
            evidence_hit_rate=overall.evidence_hit_rate,
            evidence_source_recall=overall.evidence_source_recall,
            source_count_satisfaction_rate=overall.source_count_satisfaction_rate,
            expected_term_coverage=overall.expected_term_coverage,
            avg_search_latency_ms=overall.avg_search_latency_ms,
            avg_ask_latency_ms=overall.avg_ask_latency_ms,
            case_results=case_results,
            by_type=by_type,
            by_tag=by_tag,
        )
    finally:
        service.close()
