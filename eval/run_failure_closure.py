from __future__ import annotations

import argparse
import json
from pathlib import Path

from .failure_closure import build_failure_backlog, load_benchmark_case_index, load_failure_records, write_case_drafts


def main() -> int:
    parser = argparse.ArgumentParser(description="从 benchmark failure 记录生成 backlog 与 candidate case drafts")
    parser.add_argument("--failures", required=True, help="failure JSONL 文件路径")
    parser.add_argument("--benchmark", default="", help="可选：现有 benchmark JSONL，用于判断 failure 是否已入集")
    parser.add_argument("--output", default="", help="可选：输出 backlog summary JSON")
    parser.add_argument("--drafts-output", default="", help="可选：输出未入集 candidate case JSONL")
    args = parser.parse_args()

    failure_records = load_failure_records(args.failures)
    benchmark_cases = load_benchmark_case_index(args.benchmark) if args.benchmark else []
    summary = build_failure_backlog(failure_records, benchmark_cases=benchmark_cases)
    rendered = json.dumps(summary.to_dict(), ensure_ascii=False, indent=2)
    print(rendered)

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    if args.drafts_output:
        drafts = [item.suggested_case for item in summary.items if item.suggested_case is not None]
        write_case_drafts(args.drafts_output, [draft for draft in drafts if draft is not None])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
