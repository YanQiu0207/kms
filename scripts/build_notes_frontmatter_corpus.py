from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable

import yaml


MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkdn", ".mdtxt"}
ATX_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*$")
SETEXT_RE = re.compile(r"^\s{0,3}(=+|-+)\s*$")
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
HAN_RE = re.compile(r"[\u4e00-\u9fff]")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a derived corpus from E:\\notes with generated front matter.")
    parser.add_argument("--source-root", default="E:\\notes", help="Source notes root.")
    parser.add_argument("--output-root", default="data\\corpora\\e-notes-frontmatter-v1", help="Output corpus root.")
    parser.add_argument("--skip-empty", action="store_true", default=True, help="Skip empty markdown files.")
    parser.add_argument("--replace", action="store_true", help="Remove existing output root before writing.")
    parser.add_argument("--manifest", default="", help="Optional explicit manifest path.")
    return parser.parse_args()


def _iter_markdown_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in MARKDOWN_SUFFIXES:
            yield path


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _has_front_matter(text: str) -> bool:
    return text.startswith("---\n") or text.startswith("---\r\n")


def _extract_title(text: str, fallback: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    in_fence = False
    for index, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = ATX_HEADING_RE.match(line)
        if match:
            return match.group(2).strip().strip("#").strip() or fallback
        if index + 1 < len(lines) and line.strip():
            if SETEXT_RE.match(lines[index + 1]):
                return line.strip() or fallback
    return fallback


def _infer_language(text: str) -> str:
    if not text.strip():
        return "unknown"
    han_count = len(HAN_RE.findall(text))
    ascii_letters = sum(1 for ch in text if "a" <= ch.lower() <= "z")
    if han_count and han_count >= ascii_letters:
        return "zh"
    if ascii_letters:
        return "en"
    return "unknown"


def _sanitize_tag(value: str) -> str:
    return value.strip().replace("\\", "/")


def _build_front_matter(source_root: Path, path: Path, text: str) -> dict[str, object]:
    relative = path.relative_to(source_root)
    parts = list(relative.parts[:-1])
    stem = path.stem
    title = _extract_title(text, stem)
    stat = path.stat()
    updated_at = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d")

    tags: list[str] = []
    for segment in parts:
        cleaned = _sanitize_tag(segment)
        if cleaned and cleaned not in tags:
            tags.append(cleaned)
    if stem not in tags:
        tags.append(stem)

    return {
        "title": title,
        "aliases": [stem],
        "category": parts[0] if parts else stem,
        "tags": tags,
        "language": _infer_language(text),
        "date": updated_at,
        "origin_path": relative.as_posix(),
        "origin_root": str(source_root),
        "corpus": "e-notes-frontmatter-v1",
        "frontmatter_generated_by": "mykms/scripts/build_notes_frontmatter_corpus.py",
    }


def _render_front_matter(front_matter: dict[str, object]) -> str:
    rendered = yaml.safe_dump(front_matter, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{rendered}\n---\n\n"


def _clean_output_root(output_root: Path) -> None:
    if not output_root.exists():
        return
    for path in sorted(output_root.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    output_root.rmdir()


def main() -> int:
    args = parse_args()
    source_root = Path(args.source_root)
    output_root = Path(args.output_root)
    manifest_path = Path(args.manifest) if args.manifest else output_root / "manifest.json"

    if not source_root.exists():
        raise SystemExit(f"source root does not exist: {source_root}")

    if args.replace:
        _clean_output_root(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    category_counts: Counter[str] = Counter()
    language_counts: Counter[str] = Counter()
    written_files = 0
    skipped_empty = 0
    skipped_existing_front_matter = 0
    file_summaries: list[dict[str, object]] = []

    for path in _iter_markdown_files(source_root):
        text = _read_text(path)
        if args.skip_empty and not text.strip():
            skipped_empty += 1
            continue

        relative = path.relative_to(source_root)
        target_path = output_root / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if _has_front_matter(text):
            skipped_existing_front_matter += 1
            rendered_text = text
            front_matter = {}
        else:
            front_matter = _build_front_matter(source_root, path, text)
            rendered_text = f"{_render_front_matter(front_matter)}{text.lstrip()}"

        target_path.write_text(rendered_text, encoding="utf-8")
        written_files += 1

        category = str(front_matter.get("category") or relative.parts[0] if relative.parts else "(root)")
        language = str(front_matter.get("language") or _infer_language(text))
        category_counts[category] += 1
        language_counts[language] += 1
        file_summaries.append(
            {
                "relative_path": relative.as_posix(),
                "target_path": target_path.as_posix(),
                "has_generated_front_matter": bool(front_matter),
                "title": str(front_matter.get("title") or path.stem),
                "category": category,
                "language": language,
                "content_sha1": hashlib.sha1(text.encode("utf-8")).hexdigest(),
            }
        )

    manifest = {
        "source_root": source_root.as_posix(),
        "output_root": output_root.as_posix(),
        "written_files": written_files,
        "skipped_empty": skipped_empty,
        "skipped_existing_front_matter": skipped_existing_front_matter,
        "category_counts": dict(sorted(category_counts.items())),
        "language_counts": dict(sorted(language_counts.items())),
        "files": file_summaries,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
