from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import load_config

from .index_stats import snapshot_index_stats, snapshot_index_stats_for_config


def main() -> int:
    parser = argparse.ArgumentParser(description="输出当前索引统计快照")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--sqlite", default="", help="可选：直接指定 sqlite 路径，优先于 --config")
    parser.add_argument("--output", default="", help="可选：输出 JSON 文件路径")
    args = parser.parse_args()

    if args.sqlite:
        snapshot = snapshot_index_stats(args.sqlite)
    else:
        snapshot = snapshot_index_stats_for_config(load_config(args.config))

    rendered = json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

