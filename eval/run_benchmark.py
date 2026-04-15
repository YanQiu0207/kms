from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import load_config

from .benchmark import run_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 KMS benchmark")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--benchmark", default="eval/benchmark.sample.jsonl", help="benchmark 文件路径")
    parser.add_argument("--reindex", choices=["full", "incremental"], default=None, help="运行前是否重建索引")
    parser.add_argument("--output", default="", help="可选：输出 JSON 摘要文件路径")
    args = parser.parse_args()

    summary = run_benchmark(
        args.benchmark,
        config=load_config(args.config),
        reindex_mode=args.reindex,
    )
    rendered = json.dumps(summary.to_dict(), ensure_ascii=False, indent=2)
    print(rendered)

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
