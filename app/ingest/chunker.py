"""Markdown section chunking helpers."""

from __future__ import annotations

import hashlib
from pathlib import PurePath
import re
from dataclasses import dataclass
from typing import Sequence

from .contracts import MarkdownChunk, MarkdownSection

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _is_fenced_code_line(line: str) -> bool:
    return bool(_FENCE_RE.match(line))


def _estimate_token_count(text: str) -> int:
    return len(_TOKEN_RE.findall(text))


def _preferred_split_point(text: str, start: int, end: int) -> int:
    window = text[start:end]
    if not window:
        return end

    candidates = [
        "\n\n",
        "\n",
        "。",
        "！",
        "？",
        ". ",
        "! ",
        "? ",
        " ",
    ]
    for separator in candidates:
        offset = window.rfind(separator)
        if offset > 0:
            return start + offset + len(separator)
    return end


def _split_long_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    overlap = max(0, min(overlap, chunk_size - 1))
    pieces: list[str] = []
    start = 0
    length = len(normalized)

    while start < length:
        hard_end = min(length, start + chunk_size)
        split_at = hard_end
        if hard_end < length:
            split_at = _preferred_split_point(normalized, start, hard_end)
            if split_at <= start:
                split_at = hard_end

        piece = normalized[start:split_at].strip()
        if piece:
            pieces.append(piece)

        if split_at >= length:
            break

        next_start = max(split_at - overlap, start + 1)
        if next_start <= start:
            next_start = split_at
        start = next_start

    return pieces


@dataclass(slots=True)
class _SectionBlock:
    text: str
    start_line: int
    end_line: int


def _split_section_blocks(text: str, *, section_start_line: int) -> list[_SectionBlock]:
    normalized = _normalize_text(text)
    if not normalized:
        return []

    blocks: list[_SectionBlock] = []
    current_lines: list[str] = []
    in_fence = False
    block_start_line = 0

    for offset, line in enumerate(normalized.split("\n")):
        line_number = section_start_line + offset
        if _is_fenced_code_line(line):
            if not current_lines:
                block_start_line = line_number
            current_lines.append(line)
            in_fence = not in_fence
            continue

        if not in_fence and not line.strip():
            if current_lines:
                block = "\n".join(current_lines).strip()
                if block:
                    blocks.append(
                        _SectionBlock(
                            text=block,
                            start_line=block_start_line,
                            end_line=line_number - 1,
                        )
                    )
                current_lines = []
                block_start_line = 0
            continue

        if not current_lines:
            block_start_line = line_number
        current_lines.append(line)

    if current_lines:
        block = "\n".join(current_lines).strip()
        if block:
            blocks.append(
                _SectionBlock(
                    text=block,
                    start_line=block_start_line,
                    end_line=section_start_line + len(normalized.split("\n")) - 1,
                )
            )

    return blocks or [_SectionBlock(text=normalized, start_line=section_start_line, end_line=section_start_line)]


def build_chunk_id(
    *,
    document_id: str,
    title_path: Sequence[str],
    section_index: int,
    chunk_index: int,
    text: str,
) -> str:
    """Build a stable chunk identifier using the final plan's SHA1 recipe."""

    content_sha1 = hashlib.sha1(text.encode("utf-8")).hexdigest()
    payload = "\n".join(
        [
            document_id,
            " / ".join(title_path),
            str(section_index),
            str(chunk_index),
            content_sha1,
        ]
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def build_contextual_chunk_text(chunk: MarkdownChunk) -> str:
    """Build an embedding-only text with lightweight document context."""

    body = _normalize_text(chunk.text)
    if not body:
        return ""

    metadata = chunk.metadata if isinstance(chunk.metadata, dict) else {}
    relative_path = str(metadata.get("relative_path") or "").strip()
    file_label = relative_path or PurePath(chunk.file_path).name or chunk.file_path.strip()
    front_matter_title = str(metadata.get("front_matter_title") or "").strip()
    title_path = " / ".join(title.strip() for title in chunk.title_path if title.strip())

    header_lines: list[str] = []
    if front_matter_title:
        header_lines.append(f"文档标题: {front_matter_title}")
    elif file_label:
        header_lines.append(f"文档标题: {PurePath(file_label).stem}")
    if file_label:
        header_lines.append(f"文档路径: {file_label}")
    if title_path:
        header_lines.append(f"章节路径: {title_path}")

    if not header_lines:
        return body
    return "\n".join([*header_lines, "", body])


@dataclass(slots=True)
class MarkdownChunker:
    """Chunk long Markdown sections into embedding-friendly segments."""

    chunk_size: int = 800
    chunk_overlap: int = 100
    chunker_version: str = "v1"
    embedding_model: str = ""

    def chunk(self, section: MarkdownSection) -> Sequence[MarkdownChunk]:
        normalized = _normalize_text(section.text)
        if not normalized:
            return ()

        blocks = _split_section_blocks(section.text, section_start_line=section.start_line)
        chunks: list[MarkdownChunk] = []
        current_parts: list[_SectionBlock] = []
        current_length = 0
        chunk_index = 0

        def flush_current() -> None:
            nonlocal chunk_index, current_parts, current_length
            if not current_parts:
                return

            text = "\n\n".join(part.text for part in current_parts).strip()
            if not text:
                current_parts = []
                current_length = 0
                return

            start_line = current_parts[0].start_line
            end_line = current_parts[-1].end_line
            chunks.append(
                MarkdownChunk(
                    chunk_id=build_chunk_id(
                        document_id=section.document_id,
                        title_path=section.title_path,
                        section_index=section.section_index,
                        chunk_index=chunk_index,
                        text=text,
                    ),
                    document_id=section.document_id,
                    file_path=section.file_path,
                    file_hash=section.file_hash,
                    title_path=section.title_path,
                    section_index=section.section_index,
                    chunk_index=chunk_index,
                    start_line=start_line,
                    end_line=end_line,
                    text=text,
                    token_count=_estimate_token_count(text),
                    chunker_version=self.chunker_version,
                    embedding_model=self.embedding_model,
                    metadata={},
                )
            )
            chunk_index += 1
            current_parts = []
            current_length = 0

        for block in blocks:
            if len(block.text) > self.chunk_size:
                flush_current()
                for piece in _split_long_text(block.text, self.chunk_size, self.chunk_overlap):
                    chunks.append(
                        MarkdownChunk(
                            chunk_id=build_chunk_id(
                                document_id=section.document_id,
                                title_path=section.title_path,
                                section_index=section.section_index,
                                chunk_index=chunk_index,
                                text=piece,
                            ),
                            document_id=section.document_id,
                            file_path=section.file_path,
                            file_hash=section.file_hash,
                            title_path=section.title_path,
                            section_index=section.section_index,
                            chunk_index=chunk_index,
                            start_line=block.start_line,
                            end_line=block.end_line,
                            text=piece,
                            token_count=_estimate_token_count(piece),
                            chunker_version=self.chunker_version,
                            embedding_model=self.embedding_model,
                            metadata={},
                        )
                    )
                    chunk_index += 1
                continue

            projected = current_length + len(block.text) + (2 if current_parts else 0)
            if current_parts and projected > self.chunk_size:
                flush_current()

            current_parts.append(block)
            current_length = sum(len(part.text) for part in current_parts) + max(0, (len(current_parts) - 1) * 2)

        flush_current()
        return tuple(chunks)
