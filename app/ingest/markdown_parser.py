"""Markdown document parsing helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from .contracts import MarkdownDocument, MarkdownSection

_ATX_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*$")
_ATX_TRAILING_HASHES_RE = re.compile(r"\s+#+\s*$")
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_SETEXT_RE = re.compile(r"^\s{0,3}(=+|-+)\s*$")


@dataclass(slots=True)
class _SectionBuilder:
    title_path: tuple[str, ...] = ()
    heading: str = ""
    heading_level: int = 0
    start_line: int = 0
    end_line: int = 0
    lines: list[str] = field(default_factory=list)


def _clean_heading_text(raw_text: str) -> str:
    cleaned = raw_text.strip()
    cleaned = _ATX_TRAILING_HASHES_RE.sub("", cleaned)
    return cleaned.strip()


def _is_fenced_code_line(line: str) -> bool:
    return bool(_FENCE_RE.match(line))


def _parse_heading(lines: Sequence[str], index: int, in_fence: bool) -> tuple[int, str, int] | None:
    if in_fence:
        return None

    current = lines[index]
    atx_match = _ATX_HEADING_RE.match(current)
    if atx_match:
        return len(atx_match.group(1)), _clean_heading_text(atx_match.group(2)), index + 1

    if index + 1 >= len(lines):
        return None

    next_line = lines[index + 1]
    setext_match = _SETEXT_RE.match(next_line)
    if not setext_match:
        return None

    text = current.strip()
    if not text:
        return None

    level = 1 if setext_match.group(1).startswith("=") else 2
    return level, text, index + 2


def parse_markdown_sections(document: MarkdownDocument) -> list[MarkdownSection]:
    """Split a Markdown document into title-scoped sections."""

    lines = document.text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sections: list[MarkdownSection] = []
    stack: list[tuple[int, str]] = []
    builder = _SectionBuilder()
    section_index = 0
    in_fence = False
    line_index = 0

    def flush_builder() -> None:
        nonlocal section_index, builder
        if not builder.lines:
            return

        text = "\n".join(builder.lines).rstrip()
        if not text:
            builder = _SectionBuilder()
            return

        sections.append(
            MarkdownSection(
                document_id=document.document_id,
                file_path=document.file_path,
                file_hash=document.file_hash,
                title_path=builder.title_path,
                heading=builder.heading,
                heading_level=builder.heading_level,
                section_index=section_index,
                start_line=builder.start_line,
                end_line=builder.end_line,
                text=text,
            )
        )
        section_index += 1
        builder = _SectionBuilder()

    while line_index < len(lines):
        parsed = _parse_heading(lines, line_index, in_fence)
        if parsed is not None:
            level, heading_text, next_line_index = parsed
            flush_builder()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading_text))
            builder = _SectionBuilder(
                title_path=tuple(title for _, title in stack),
                heading=heading_text,
                heading_level=level,
                start_line=line_index + 1,
                end_line=line_index + 1,
                lines=[lines[line_index].rstrip()],
            )
            line_index = next_line_index
            continue

        current_line = lines[line_index]
        if _is_fenced_code_line(current_line):
            in_fence = not in_fence

        if not builder.lines:
            builder = _SectionBuilder(
                title_path=tuple(title for _, title in stack),
                heading=stack[-1][1] if stack else "",
                heading_level=stack[-1][0] if stack else 0,
                start_line=line_index + 1,
                lines=[],
            )

        builder.lines.append(current_line.rstrip())
        builder.end_line = line_index + 1
        line_index += 1

    flush_builder()
    return sections


class MarkdownParser:
    """Import-safe parser that exposes the section split used by the loader."""

    def parse(self, document: MarkdownDocument) -> Sequence[MarkdownSection]:
        return parse_markdown_sections(document)
