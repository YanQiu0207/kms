from __future__ import annotations

from pathlib import Path


def test_adapter_and_eval_assets_exist():
    required_paths = [
        Path("app/adapters/reference/api.md"),
        Path("app/adapters/claude/SKILL.md"),
        Path("app/adapters/codex/kms.md"),
        Path("eval/README.md"),
        Path("eval/benchmark.sample.jsonl"),
    ]

    for path in required_paths:
        assert path.exists(), f"missing asset: {path}"


def test_api_reference_mentions_core_endpoints():
    content = Path("app/adapters/reference/api.md").read_text(encoding="utf-8")
    for endpoint in ("/index", "/search", "/ask", "/verify", "/stats", "/health"):
        assert endpoint in content
