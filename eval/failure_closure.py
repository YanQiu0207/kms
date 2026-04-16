from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

from .benchmark import BenchmarkCase, load_benchmark_cases


def _normalize_text(value: object | None) -> str:
    return str(value or "").strip().casefold()


def _normalize_path(value: object | None) -> str:
    return str(value or "").replace("\\", "/").strip()


def _coerce_strings(values: object | None) -> tuple[str, ...]:
    if not values:
        return ()
    if isinstance(values, str):
        cleaned = values.strip()
        return (cleaned,) if cleaned else ()
    if isinstance(values, Sequence):
        return tuple(str(value).strip() for value in values if str(value).strip())
    return ()


def _draft_case_id(record: dict[str, object]) -> str:
    payload = "|".join(
        [
            str(record.get("suite_name") or "").strip(),
            str(record.get("case_type") or "").strip(),
            str(record.get("question") or "").strip(),
        ]
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"draft-{digest}"


@dataclass(slots=True)
class FailureCaseDraft:
    id: str
    question: str
    queries: tuple[str, ...]
    expected_file_paths: tuple[str, ...]
    linked_issue_ids: tuple[str, ...]
    should_abstain: bool
    case_type: str
    tags: tuple[str, ...]
    notes: str = ""

    def to_record(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class FailureBacklogItem:
    question: str
    suite_name: str
    case_type: str
    tags: tuple[str, ...]
    linked_issue_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    should_abstain: bool
    top_file_path: str = ""
    covered_by_benchmark: bool = False
    matching_case_ids: tuple[str, ...] = ()
    suggested_case: FailureCaseDraft | None = None

    def to_record(self) -> dict[str, object]:
        payload = asdict(self)
        if self.suggested_case is not None:
            payload["suggested_case"] = self.suggested_case.to_record()
        return payload


@dataclass(slots=True)
class FailureClosureSummary:
    total_failure_records: int
    backlog_count: int
    uncovered_count: int
    covered_count: int
    items: tuple[FailureBacklogItem, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "total_failure_records": self.total_failure_records,
            "backlog_count": self.backlog_count,
            "uncovered_count": self.uncovered_count,
            "covered_count": self.covered_count,
            "items": [item.to_record() for item in self.items],
        }


def load_failure_records(path: str | Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        raw = json.loads(stripped)
        if isinstance(raw, dict):
            records.append(raw)
    return records


def draft_case_from_failure_record(record: dict[str, object]) -> FailureCaseDraft:
    question = str(record.get("question") or "").strip()
    should_abstain = bool(record.get("should_abstain", False))
    top_file_path = _normalize_path(record.get("top_file_path"))
    tags = _coerce_strings(record.get("tags"))
    reasons = _coerce_strings(record.get("reasons"))
    linked_issue_ids = _coerce_strings(record.get("linked_issue_ids"))
    notes_parts = [
        f"auto-draft from {str(record.get('suite_name') or '').strip() or 'failure-record'}",
        "verify expected_file_paths / should_abstain before promoting to main benchmark",
    ]
    if reasons:
        notes_parts.append(f"reasons={','.join(reasons)}")
    abstain_reason = str(record.get("abstain_reason") or "").strip()
    if abstain_reason:
        notes_parts.append(f"abstain_reason={abstain_reason}")
    if top_file_path:
        notes_parts.append(f"top_file_path={top_file_path}")
    return FailureCaseDraft(
        id=_draft_case_id(record),
        question=question,
        queries=(question,),
        expected_file_paths=() if should_abstain or not top_file_path else (top_file_path,),
        linked_issue_ids=linked_issue_ids,
        should_abstain=should_abstain,
        case_type=str(record.get("case_type") or "lookup").strip() or "lookup",
        tags=tags,
        notes="; ".join(notes_parts),
    )


def _matching_benchmark_case_ids(record: dict[str, object], benchmark_cases: Sequence[BenchmarkCase]) -> tuple[str, ...]:
    normalized_question = _normalize_text(record.get("question"))
    linked_issue_ids = {issue_id.casefold() for issue_id in _coerce_strings(record.get("linked_issue_ids"))}
    matches: list[str] = []
    for case in benchmark_cases:
        if normalized_question and _normalize_text(case.question) == normalized_question:
            matches.append(case.id)
            continue
        if linked_issue_ids and any(issue.casefold() in linked_issue_ids for issue in case.linked_issue_ids):
            matches.append(case.id)
    deduped: list[str] = []
    seen: set[str] = set()
    for case_id in matches:
        if case_id in seen:
            continue
        seen.add(case_id)
        deduped.append(case_id)
    return tuple(deduped)


def build_failure_backlog(
    failure_records: Sequence[dict[str, object]],
    *,
    benchmark_cases: Sequence[BenchmarkCase] = (),
) -> FailureClosureSummary:
    deduped_records: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for record in failure_records:
        key = (
            _normalize_text(record.get("question")),
            str(record.get("case_type") or "lookup").strip().casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped_records.append(record)

    items: list[FailureBacklogItem] = []
    covered_count = 0
    uncovered_count = 0
    for record in deduped_records:
        matching_case_ids = _matching_benchmark_case_ids(record, benchmark_cases)
        covered = bool(matching_case_ids)
        if covered:
            covered_count += 1
        else:
            uncovered_count += 1
        item = FailureBacklogItem(
            question=str(record.get("question") or "").strip(),
            suite_name=str(record.get("suite_name") or "").strip(),
            case_type=str(record.get("case_type") or "lookup").strip() or "lookup",
            tags=_coerce_strings(record.get("tags")),
            linked_issue_ids=_coerce_strings(record.get("linked_issue_ids")),
            reasons=_coerce_strings(record.get("reasons")),
            should_abstain=bool(record.get("should_abstain", False)),
            top_file_path=_normalize_path(record.get("top_file_path")),
            covered_by_benchmark=covered,
            matching_case_ids=matching_case_ids,
            suggested_case=None if covered else draft_case_from_failure_record(record),
        )
        items.append(item)
    return FailureClosureSummary(
        total_failure_records=len(failure_records),
        backlog_count=len(items),
        uncovered_count=uncovered_count,
        covered_count=covered_count,
        items=tuple(items),
    )


def load_benchmark_case_index(path: str | Path) -> list[BenchmarkCase]:
    return load_benchmark_cases(path)


def write_case_drafts(path: str | Path, drafts: Sequence[FailureCaseDraft]) -> None:
    payload = "\n".join(json.dumps(draft.to_record(), ensure_ascii=False) for draft in drafts)
    Path(path).write_text(payload, encoding="utf-8")
