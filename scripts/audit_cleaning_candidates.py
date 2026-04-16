from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from app.config import load_config

MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkdn", ".mdtxt"}
TOC_RE = re.compile(r"^\s*\[TOC\]\s*$", re.MULTILINE)
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}.*\|?\s*$")
AUTHOR_PATTERNS = (
    "编辑于",
    "作者之一",
    "知乎",
    "转载",
    "原文链接",
    "原文地址",
    "本文转自",
    "公众号",
    "阅读原文",
)
REFERENCE_PATTERNS = (
    "参考链接",
    "参考文献",
    "参考资料",
    "参考博客",
    "参考：",
)
PLACEHOLDER_PATTERNS = (
    "待续",
    "TODO",
    "TBD",
)


def _iter_markdown_paths(root: Path):
    if root.is_file():
        if root.suffix.lower() in MARKDOWN_SUFFIXES:
            yield root
        return
    for candidate in root.rglob("*"):
        if candidate.is_file() and candidate.suffix.lower() in MARKDOWN_SUFFIXES:
            yield candidate


def _has_markdown_table(text: str) -> bool:
    lines = text.splitlines()
    for index in range(len(lines) - 1):
        if TABLE_ROW_RE.match(lines[index]) and TABLE_SEPARATOR_RE.match(lines[index + 1]):
            return True
    return False


def _path_display(path: Path) -> str:
    return path.resolve(strict=False).as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan markdown sources for M14 cleaning candidates.")
    parser.add_argument("--config", default="config.yaml", help="Config file path.")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    parser.add_argument("--samples-per-group", type=int, default=12, help="Representative sample file count per group.")
    args = parser.parse_args()

    config = load_config(args.config)
    roots = [Path(source.path).expanduser() for source in config.sources]

    totals = {
        "documents": 0,
        "toc_docs": 0,
        "table_docs": 0,
        "author_docs": 0,
        "reference_docs": 0,
        "placeholder_docs": 0,
    }
    samples: dict[str, list[str]] = defaultdict(list)
    by_root: dict[str, dict[str, int]] = {}

    for root in roots:
        root_key = _path_display(root)
        root_counts = {
            "documents": 0,
            "toc_docs": 0,
            "table_docs": 0,
            "author_docs": 0,
            "reference_docs": 0,
            "placeholder_docs": 0,
        }
        for path in _iter_markdown_paths(root):
            text = path.read_text(encoding="utf-8", errors="replace")
            root_counts["documents"] += 1
            totals["documents"] += 1
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            display_path = _path_display(path)

            if TOC_RE.search(normalized):
                root_counts["toc_docs"] += 1
                totals["toc_docs"] += 1
                if len(samples["toc_docs"]) < args.samples_per_group:
                    samples["toc_docs"].append(display_path)

            if _has_markdown_table(normalized):
                root_counts["table_docs"] += 1
                totals["table_docs"] += 1
                if len(samples["table_docs"]) < args.samples_per_group:
                    samples["table_docs"].append(display_path)

            if any(pattern in normalized for pattern in AUTHOR_PATTERNS):
                root_counts["author_docs"] += 1
                totals["author_docs"] += 1
                if len(samples["author_docs"]) < args.samples_per_group:
                    samples["author_docs"].append(display_path)

            if any(pattern in normalized for pattern in REFERENCE_PATTERNS):
                root_counts["reference_docs"] += 1
                totals["reference_docs"] += 1
                if len(samples["reference_docs"]) < args.samples_per_group:
                    samples["reference_docs"].append(display_path)

            if any(pattern in normalized for pattern in PLACEHOLDER_PATTERNS):
                root_counts["placeholder_docs"] += 1
                totals["placeholder_docs"] += 1
                if len(samples["placeholder_docs"]) < args.samples_per_group:
                    samples["placeholder_docs"].append(display_path)

        by_root[root_key] = root_counts

    payload = {
        "config_path": str(Path(args.config)),
        "summary": totals,
        "by_root": by_root,
        "samples": dict(samples),
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
