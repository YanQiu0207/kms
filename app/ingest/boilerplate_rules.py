from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Sequence

from app.config import SourceCleaningRuleConfig

from .contracts import MarkdownDocument

_ATX_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*$")
_ATX_TRAILING_HASHES_RE = re.compile(r"\s+#+\s*$")
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def _normalize_heading_title(value: str) -> str:
    cleaned = value.strip()
    cleaned = _ATX_TRAILING_HASHES_RE.sub("", cleaned)
    return cleaned.strip().lower()


def _is_fenced_code_line(line: str) -> bool:
    return bool(_FENCE_RE.match(line))


@dataclass(slots=True)
class SourceRuleMatch:
    text: str
    applied_rule_ids: tuple[str, ...]
    dropped_line_count: int
    dropped_section_count: int


@dataclass(slots=True)
class _CompiledSourceRule:
    id: str
    path_globs: tuple[str, ...]
    source_root_globs: tuple[str, ...]
    drop_line_patterns: tuple[re.Pattern[str], ...]
    drop_trailing_heading_titles: tuple[str, ...]

    def matches(self, document: MarkdownDocument) -> bool:
        if self.source_root_globs:
            normalized_root = document.source_root.replace("\\", "/")
            if not any(fnmatchcase(normalized_root, pattern) for pattern in self.source_root_globs):
                return False

        if self.path_globs:
            relative_path = document.relative_path.replace("\\", "/")
            absolute_path = document.file_path.replace("\\", "/")
            if not any(
                fnmatchcase(relative_path, pattern) or fnmatchcase(absolute_path, pattern)
                for pattern in self.path_globs
            ):
                return False

        return True


def compile_source_rules(rules: Sequence[SourceCleaningRuleConfig]) -> tuple[_CompiledSourceRule, ...]:
    compiled: list[_CompiledSourceRule] = []
    for rule in rules:
        if not rule.enabled:
            continue
        compiled.append(
            _CompiledSourceRule(
                id=rule.id or "(unnamed-rule)",
                path_globs=tuple(pattern.strip() for pattern in rule.path_globs if pattern.strip()),
                source_root_globs=tuple(pattern.strip() for pattern in rule.source_root_globs if pattern.strip()),
                drop_line_patterns=tuple(re.compile(pattern) for pattern in rule.drop_line_patterns if pattern.strip()),
                drop_trailing_heading_titles=tuple(
                    _normalize_heading_title(title) for title in rule.drop_trailing_heading_titles if title.strip()
                ),
            )
        )
    return tuple(compiled)


def _drop_matching_lines(text: str, patterns: Sequence[re.Pattern[str]]) -> tuple[str, int]:
    if not patterns:
        return text, 0

    kept_lines: list[str] = []
    dropped = 0
    for line in text.split("\n"):
        if any(pattern.search(line) for pattern in patterns):
            dropped += 1
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines), dropped


def _drop_trailing_sections_by_heading(text: str, titles: Sequence[str]) -> tuple[str, int]:
    if not titles:
        return text, 0

    lines = text.split("\n")
    headings: list[tuple[int, int, str]] = []
    in_fence = False
    for index, line in enumerate(lines):
        if _is_fenced_code_line(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _ATX_HEADING_RE.match(line)
        if not match:
            continue
        headings.append((index, len(match.group(1)), _normalize_heading_title(match.group(2))))

    if not headings:
        return text, 0

    title_set = set(titles)
    for offset, (line_index, level, title) in enumerate(headings):
        if title not in title_set:
            continue

        next_same_or_higher_heading = len(lines)
        for next_line_index, next_level, _ in headings[offset + 1 :]:
            if next_level <= level:
                next_same_or_higher_heading = next_line_index
                break

        if next_same_or_higher_heading == len(lines):
            trimmed = "\n".join(lines[:line_index]).rstrip()
            return trimmed, 1

    return text, 0


def apply_source_rules(
    text: str,
    *,
    document: MarkdownDocument,
    rules: Sequence[_CompiledSourceRule],
) -> SourceRuleMatch:
    current = text
    applied_rule_ids: list[str] = []
    dropped_line_count = 0
    dropped_section_count = 0

    for rule in rules:
        if not rule.matches(document):
            continue

        rule_applied = False
        if rule.drop_line_patterns:
            current, dropped_lines = _drop_matching_lines(current, rule.drop_line_patterns)
            if dropped_lines:
                dropped_line_count += dropped_lines
                rule_applied = True

        if rule.drop_trailing_heading_titles:
            current, dropped_sections = _drop_trailing_sections_by_heading(current, rule.drop_trailing_heading_titles)
            if dropped_sections:
                dropped_section_count += dropped_sections
                rule_applied = True

        if rule_applied:
            applied_rule_ids.append(rule.id)

    return SourceRuleMatch(
        text=current,
        applied_rule_ids=tuple(applied_rule_ids),
        dropped_line_count=dropped_line_count,
        dropped_section_count=dropped_section_count,
    )
