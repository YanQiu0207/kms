from __future__ import annotations

import argparse
import json
from pathlib import Path

from .suite import load_suite_entries, run_benchmark_suite


def main() -> int:
    parser = argparse.ArgumentParser(description="批量运行 benchmark suite")
    parser.add_argument("--suite", default="eval/benchmark-suite.m18.json", help="suite 规格文件路径")
    parser.add_argument("--base-url", default="", help="可选：通过 HTTP API 跑整套 benchmark，例如 http://127.0.0.1:49153")
    parser.add_argument("--output", default="", help="可选：输出 suite summary JSON 文件路径")
    parser.add_argument("--failures-output", default="", help="可选：输出失败 case JSONL 文件路径")
    args = parser.parse_args()

    summary = run_benchmark_suite(
        load_suite_entries(args.suite),
        base_url_override=args.base_url or None,
    )
    rendered = json.dumps(summary.to_dict(), ensure_ascii=False, indent=2)
    print(rendered)

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    if args.failures_output:
        records: list[dict[str, object]] = []
        for item in summary.suite_results:
            records.extend(item.failing_cases)
        payload = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
        Path(args.failures_output).write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
