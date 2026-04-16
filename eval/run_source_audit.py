from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import load_config

from .source_audit import snapshot_source_audit


def main() -> int:
    parser = argparse.ArgumentParser(description="输出索引 source audit 快照")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--output", default="", help="可选：输出 JSON 文件路径")
    args = parser.parse_args()

    snapshot = snapshot_source_audit(load_config(args.config))
    rendered = json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
