from __future__ import annotations

import json

from eval.benchmark import BenchmarkCase
from eval.failure_closure import (
    build_failure_backlog,
    draft_case_from_failure_record,
    load_failure_records,
    write_case_drafts,
)


def test_draft_case_from_failure_record_builds_candidate_case():
    draft = draft_case_from_failure_record(
        {
            "suite_name": "distributed.real10",
            "question": "为什么 ZooKeeper watch 会丢事件？",
            "case_type": "lookup",
            "tags": ["distributed", "watch"],
            "linked_issue_ids": ["ISSUE-M19-001"],
            "reasons": ["retrieval_miss"],
            "top_file_path": "E:/notes/distributed/zookeeper.md",
            "should_abstain": False,
        }
    )

    assert draft.id.startswith("draft-")
    assert draft.queries == ("为什么 ZooKeeper watch 会丢事件？",)
    assert draft.expected_file_paths == ("E:/notes/distributed/zookeeper.md",)
    assert draft.linked_issue_ids == ("ISSUE-M19-001",)
    assert "retrieval_miss" in draft.notes


def test_build_failure_backlog_marks_existing_question_as_covered():
    summary = build_failure_backlog(
        [
            {
                "suite_name": "distributed.real10",
                "question": "为什么 ZooKeeper watch 会丢事件？",
                "case_type": "lookup",
                "tags": ["distributed", "watch"],
                "linked_issue_ids": ["ISSUE-M19-001"],
                "reasons": ["retrieval_miss"],
                "top_file_path": "E:/notes/distributed/zookeeper.md",
                "should_abstain": False,
            }
        ],
        benchmark_cases=[
            BenchmarkCase(
                id="dist-1",
                question="为什么 ZooKeeper watch 会丢事件？",
                queries=("为什么 ZooKeeper watch 会丢事件？",),
                linked_issue_ids=("ISSUE-M19-001",),
            )
        ],
    )

    assert summary.backlog_count == 1
    assert summary.covered_count == 1
    assert summary.uncovered_count == 0
    assert summary.items[0].covered_by_benchmark is True
    assert summary.items[0].matching_case_ids == ("dist-1",)
    assert summary.items[0].suggested_case is None


def test_load_failure_records_and_write_case_drafts_round_trip(tmp_path):
    failure_path = tmp_path / "failures.jsonl"
    failure_path.write_text(
        json.dumps(
            {
                "suite_name": "demo",
                "question": "什么是对象复用？",
                "case_type": "lookup",
                "tags": ["programming"],
                "reasons": ["retrieval_miss"],
                "top_file_path": "E:/notes/programming/object-pool.md",
                "should_abstain": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    records = load_failure_records(failure_path)
    draft = draft_case_from_failure_record(records[0])
    draft_path = tmp_path / "drafts.jsonl"
    write_case_drafts(draft_path, [draft])

    payload = [json.loads(line) for line in draft_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(records) == 1
    assert payload[0]["question"] == "什么是对象复用？"
    assert payload[0]["expected_file_paths"] == ["E:/notes/programming/object-pool.md"]
