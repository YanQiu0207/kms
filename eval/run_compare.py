from __future__ import annotations

import argparse
import json
from pathlib import Path

from .compare import build_comparison_report, load_json_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="比较 benchmark 结果和索引统计快照")
    parser.add_argument("--baseline-benchmark", default="", help="baseline benchmark JSON 路径")
    parser.add_argument("--candidate-benchmark", default="", help="candidate benchmark JSON 路径")
    parser.add_argument("--baseline-index-stats", default="", help="baseline index stats JSON 路径")
    parser.add_argument("--candidate-index-stats", default="", help="candidate index stats JSON 路径")
    parser.add_argument("--output", default="", help="可选：输出 JSON 文件路径")
    args = parser.parse_args()

    report = build_comparison_report(
        baseline_benchmark=load_json_payload(args.baseline_benchmark) if args.baseline_benchmark and args.candidate_benchmark else None,
        candidate_benchmark=load_json_payload(args.candidate_benchmark) if args.baseline_benchmark and args.candidate_benchmark else None,
        baseline_index_stats=load_json_payload(args.baseline_index_stats)
        if args.baseline_index_stats and args.candidate_index_stats
        else None,
        candidate_index_stats=load_json_payload(args.candidate_index_stats)
        if args.baseline_index_stats and args.candidate_index_stats
        else None,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

