from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_build_notes_frontmatter_corpus_generates_derived_files(tmp_path: Path):
    source_root = tmp_path / "notes"
    output_root = tmp_path / "corpus"
    source_root.mkdir()
    (source_root / "程序设计").mkdir()
    (source_root / "程序设计" / "对象池.md").write_text(
        "# 对象池\n\n用于减少等长对象的频繁分配。\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_notes_frontmatter_corpus.py",
            "--source-root",
            str(source_root),
            "--output-root",
            str(output_root),
            "--replace",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )

    manifest = json.loads(result.stdout)
    assert manifest["written_files"] == 1
    target = output_root / "程序设计" / "对象池.md"
    text = target.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "title: 对象池" in text
    assert "category: 程序设计" in text
    assert "origin_path: 程序设计/对象池.md" in text
    assert "用于减少等长对象的频繁分配" in text
