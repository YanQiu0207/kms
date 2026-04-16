"""Low-risk Markdown cleaning helpers for retrieval-oriented ingest."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

import yaml

from app.config import CleaningConfig

from .boilerplate_rules import apply_source_rules, compile_source_rules
from .contracts import MarkdownChunk, MarkdownDocument
from .table_normalizer import normalize_markdown_tables

_FRONT_MATTER_BOUNDARY_RE = re.compile(r"^\s*---\s*$")
_FRONT_MATTER_ALT_BOUNDARY_RE = re.compile(r"^\s*\.\.\.\s*$")
_TOC_MARKER_RE = re.compile(r"^\s*\[toc\]\s*$", re.IGNORECASE)
_LOW_VALUE_PLACEHOLDER_RE = re.compile(r"^\s*(待续|未完待续|todo|tbd|wip)\s*$", re.IGNORECASE)


def _strip_utf8_bom(text: str) -> tuple[str, bool]:
    if text.startswith("\ufeff"):
        return text.removeprefix("\ufeff"), True
    return text, False


def _normalize_line_endings(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _strip_trailing_spaces(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.split("\n"))


def _extract_front_matter(text: str) -> tuple[dict[str, object], str, int]:
    if not text.startswith("---"):
        return {}, text, 0

    lines = text.split("\n")
    if not lines or not _FRONT_MATTER_BOUNDARY_RE.match(lines[0]):
        return {}, text, 0

    for index in range(1, len(lines)):
        line = lines[index]
        if _FRONT_MATTER_BOUNDARY_RE.match(line) or _FRONT_MATTER_ALT_BOUNDARY_RE.match(line):
            raw_payload = "\n".join(lines[1:index]).strip()
            remainder = "\n".join(lines[index + 1 :])
            if not raw_payload:
                return {}, remainder, index + 1
            try:
                parsed = yaml.safe_load(raw_payload) or {}
            except yaml.YAMLError:
                return {}, text, 0
            if not isinstance(parsed, dict):
                return {}, text, 0
            return {str(key): value for key, value in parsed.items()}, remainder, index + 1
    return {}, text, 0


def _normalized_chunk_key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _drop_matching_lines(text: str, pattern: re.Pattern[str]) -> tuple[str, int]:
    kept_lines: list[str] = []
    dropped = 0
    for line in text.split("\n"):
        if pattern.match(line):
            dropped += 1
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines), dropped


@dataclass(slots=True)
class MarkdownCleaner:
    config: CleaningConfig
    _source_rules: tuple[object, ...] = field(init=False, repr=False, default_factory=tuple)

    def __post_init__(self) -> None:
        self._source_rules = compile_source_rules(self.config.source_rules)

    def clean_document(self, document: MarkdownDocument) -> MarkdownDocument:
        if not self.config.enabled:
            return document

        text, bom_removed = _strip_utf8_bom(document.text)
        text = _normalize_line_endings(text)

        front_matter: dict[str, object] = {}
        front_matter_line_count = 0
        if self.config.extract_front_matter:
            front_matter, cleaned, front_matter_line_count = _extract_front_matter(text)
            if front_matter and self.config.drop_front_matter_from_content:
                text = cleaned

        whitespace_normalized = False
        if self.config.normalize_whitespace:
            normalized = _strip_trailing_spaces(text)
            whitespace_normalized = normalized != text
            text = normalized

        toc_markers_removed = 0
        if self.config.drop_toc_markers:
            text, toc_markers_removed = _drop_matching_lines(text, _TOC_MARKER_RE)

        low_value_placeholders_removed = 0
        if self.config.drop_low_value_placeholders:
            text, low_value_placeholders_removed = _drop_matching_lines(text, _LOW_VALUE_PLACEHOLDER_RE)

        tables_normalized = 0
        normalized_table_rows = 0
        if self.config.normalize_markdown_tables:
            table_result = normalize_markdown_tables(text)
            text = table_result.text
            tables_normalized = table_result.table_count
            normalized_table_rows = table_result.row_count

        source_rule_dropped_lines = 0
        source_rule_dropped_sections = 0
        source_rules_applied: tuple[str, ...] = ()
        if self._source_rules:
            rule_result = apply_source_rules(text, document=document, rules=self._source_rules)
            text = rule_result.text
            source_rules_applied = rule_result.applied_rule_ids
            source_rule_dropped_lines = rule_result.dropped_line_count
            source_rule_dropped_sections = rule_result.dropped_section_count

        metadata = dict(document.metadata)
        cleaning = dict(metadata.get("cleaning") or {})
        cleaning.update(
            {
                "enabled": True,
                "bom_removed": bom_removed,
                "front_matter_extracted": bool(front_matter),
                "front_matter_line_count": front_matter_line_count,
                "whitespace_normalized": whitespace_normalized,
                "toc_markers_removed": toc_markers_removed,
                "low_value_placeholders_removed": low_value_placeholders_removed,
                "tables_normalized": tables_normalized,
                "normalized_table_rows": normalized_table_rows,
                "source_rule_dropped_lines": source_rule_dropped_lines,
                "source_rule_dropped_sections": source_rule_dropped_sections,
            }
        )
        if source_rules_applied:
            cleaning["source_rules_applied"] = list(source_rules_applied)
        if front_matter:
            metadata["front_matter"] = front_matter
        metadata["cleaning"] = cleaning

        return MarkdownDocument(
            source_id=document.source_id,
            source_root=document.source_root,
            document_id=document.document_id,
            file_path=document.file_path,
            relative_path=document.relative_path,
            file_hash=document.file_hash,
            mtime_ns=document.mtime_ns,
            size=document.size,
            text=text,
            encoding=document.encoding,
            metadata=metadata,
        )

    def dedupe_exact_chunks(
        self,
        document: MarkdownDocument,
        chunks: Sequence[MarkdownChunk],
    ) -> tuple[MarkdownChunk, ...]:
        if not self.config.enabled or not self.config.dedupe_exact_chunks:
            return tuple(chunks)

        normalized_counts: dict[str, int] = {}
        for chunk in chunks:
            key = _normalized_chunk_key(chunk.text)
            if key:
                normalized_counts[key] = normalized_counts.get(key, 0) + 1

        kept: list[MarkdownChunk] = []
        seen: set[str] = set()
        dropped_duplicates = 0
        for chunk in chunks:
            key = _normalized_chunk_key(chunk.text)
            if not key:
                kept.append(chunk)
                continue
            if key in seen:
                dropped_duplicates += 1
                continue
            seen.add(key)

            metadata = dict(chunk.metadata)
            duplicate_group_size = normalized_counts.get(key, 1)
            if duplicate_group_size > 1:
                metadata["exact_duplicate_group_size"] = duplicate_group_size
            kept.append(
                MarkdownChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    file_path=chunk.file_path,
                    file_hash=chunk.file_hash,
                    title_path=chunk.title_path,
                    section_index=chunk.section_index,
                    chunk_index=chunk.chunk_index,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    text=chunk.text,
                    token_count=chunk.token_count,
                    chunker_version=chunk.chunker_version,
                    embedding_model=chunk.embedding_model,
                    metadata=metadata,
                )
            )

        if dropped_duplicates:
            cleaning = dict(document.metadata.get("cleaning") or {})
            cleaning["dropped_exact_duplicate_chunks"] = dropped_duplicates
            document.metadata["cleaning"] = cleaning

        return tuple(kept)
