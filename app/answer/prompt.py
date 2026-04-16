"""Prompt assembly for host-side answer generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import Sequence

from app.retrieve.contracts import RetrievedChunk

from .contracts import AnswerError, EvidencePackage, EvidenceSource, PromptAssembler
from .guardrail import AbstainThresholds, GuardrailDecision, evaluate_abstain


DEFAULT_SYSTEM_PROMPT = """你是 KMS 的答案编排器。
你必须只基于下方“证据”回答用户问题。

硬性规则：
1. 只能使用证据中的信息，不得编造、猜测或调用训练记忆。
2. 每条结论都必须带上来源标记，格式必须是 [1]、[2] 这类数字引用。
3. 如果证据不足，直接输出“资料不足，无法确认。”，不要继续补写。
4. 先给结论，再给必要说明；不要输出与问题无关的内容。
5. 当多个证据都支持同一结论时，可以并列标注多个 [1][2]。
6. 回答正文结束后，必须追加“来源列表”，逐条列出 [n]、文件名:行号、标题路径。
"""


@dataclass(slots=True)
class PromptRenderConfig:
    """Configurable prompt rendering knobs for debug and host use."""

    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    max_sources: int = 6
    max_source_chars: int = 1200
    include_scores: bool = True


def _coerce_text(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _coerce_title_path(value: object | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        cleaned = value.strip()
        return (cleaned,) if cleaned else ()
    if isinstance(value, Sequence):
        items: list[str] = []
        for item in value:
            text = _coerce_text(item)
            if text:
                items.append(text)
        return tuple(items)
    text = _coerce_text(value)
    return (text,) if text else ()


def _coerce_chunk_id(chunk: RetrievedChunk) -> str:
    if chunk.chunk_id:
        return chunk.chunk_id.strip()
    metadata = chunk.metadata or {}
    raw = metadata.get("chunk_id") or metadata.get("id") or metadata.get("source_id")
    if raw:
        return str(raw).strip()
    return chunk.document_id.strip()


def _coerce_file_path(chunk: RetrievedChunk) -> str:
    if chunk.file_path:
        return chunk.file_path.strip()
    metadata = chunk.metadata or {}
    raw = metadata.get("file_path") or metadata.get("path") or metadata.get("source_path")
    return _coerce_text(raw)


def _coerce_doc_id(chunk: RetrievedChunk) -> str | None:
    metadata = chunk.metadata or {}
    raw = metadata.get("doc_id") or metadata.get("document_id")
    if raw:
        return str(raw).strip()
    return chunk.document_id.strip() or None


def _coerce_line_number(value: object | None) -> int:
    if value is None or value == "":
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _coerce_line_range(chunk: RetrievedChunk) -> tuple[int, int]:
    metadata = chunk.metadata or {}
    start_line = _coerce_line_number(metadata.get("start_line"))
    end_line = _coerce_line_number(metadata.get("end_line"))
    if end_line and start_line and end_line < start_line:
        end_line = start_line
    return start_line, end_line


def _coerce_source(chunk: RetrievedChunk) -> EvidenceSource:
    metadata = dict(chunk.metadata or {})
    start_line, end_line = _coerce_line_range(chunk)
    return EvidenceSource(
        chunk_id=_coerce_chunk_id(chunk),
        file_path=_coerce_file_path(chunk),
        title_path=_coerce_title_path(chunk.title_path or metadata.get("title_path") or metadata.get("titles")),
        start_line=start_line,
        end_line=end_line,
        text=_coerce_text(chunk.text or chunk.content),
        score=float(chunk.score or 0.0),
        doc_id=_coerce_doc_id(chunk),
        metadata=metadata,
    )


def build_evidence_sources(chunks: Sequence[RetrievedChunk]) -> tuple[EvidenceSource, ...]:
    """Convert retrieval chunks into prompt-friendly evidence sources."""

    sources: list[EvidenceSource] = []
    for index, chunk in enumerate((chunk for chunk in chunks if chunk.content.strip()), start=1):
        source = _coerce_source(chunk)
        source.ref_index = index
        sources.append(source)
    return tuple(sources)


def _truncate_text(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: max(limit - 1, 0)].rstrip()}…"


def _render_title_path(title_path: tuple[str, ...]) -> str:
    return " / ".join(title_path) if title_path else ""


def _render_source_location(source: EvidenceSource) -> str:
    file_name = PurePath(source.file_path).name if source.file_path else ""
    file_name = file_name or source.file_path or "(无文件名)"
    start_line = max(0, int(source.start_line or 0))
    end_line = max(0, int(source.end_line or 0))
    if start_line <= 0:
        return file_name
    if end_line > start_line:
        return f"{file_name}:{start_line}-{end_line}"
    return f"{file_name}:{start_line}"


def _render_source_block(source: EvidenceSource, index: int, config: PromptRenderConfig) -> str:
    ref_index = source.ref_index or index
    parts = [f"[证据 {ref_index}]"]
    parts.append(f"ref: [{ref_index}]")
    parts.append(f"location: {_render_source_location(source)}")
    if source.file_path:
        parts.append(f"file_path: {source.file_path}")
    if source.doc_id:
        parts.append(f"doc_id: {source.doc_id}")
    title = _render_title_path(source.title_path)
    if title:
        parts.append(f"title_path: {title}")
    if config.include_scores:
        parts.append(f"score: {source.score:.4f}")
    text = _truncate_text(source.text, config.max_source_chars)
    parts.append("text:")
    parts.append(text or "(empty)")
    return "\n".join(parts)


def _render_source_list(sources: Sequence[EvidenceSource]) -> str:
    lines: list[str] = []
    for source in sources:
        title = _render_title_path(source.title_path) or "(无标题)"
        location = _render_source_location(source)
        lines.append(f"[{source.ref_index}] {location} | {title}")
    return "\n".join(lines) if lines else "(无来源)"


def _render_prompt(question: str, sources: Sequence[EvidenceSource], config: PromptRenderConfig) -> str:
    evidence_blocks = [
        _render_source_block(source, index + 1, config)
        for index, source in enumerate(sources)
    ]

    sections = [
        config.system_prompt.strip(),
        f"问题：{question.strip()}",
        "证据：",
        "\n\n".join(evidence_blocks) if evidence_blocks else "(无证据)",
        "输出要求：",
        "1. 只能基于证据回答。",
        "2. 每条结论都必须带 [1]、[2] 这类数字引用。",
        "3. 若证据不足，必须直接回复“资料不足，无法确认。”。",
        "4. 回答末尾必须追加“来源列表”。",
        "5. 来源列表中的每条来源必须包含 [n]、文件名:行号、标题路径。",
        "来源列表：",
        _render_source_list(sources),
        "6. 不要暴露推理过程，不要编造来源。",
    ]
    return "\n\n".join(section for section in sections if section)


def build_prompt_package(
    question: str,
    chunks: Sequence[RetrievedChunk],
    *,
    render_config: PromptRenderConfig | None = None,
    thresholds: AbstainThresholds | object | None = None,
    decision: GuardrailDecision | None = None,
) -> EvidencePackage:
    """Build the final prompt package used by `/ask`."""

    config = render_config or PromptRenderConfig()
    stripped_question = question.strip()
    if not stripped_question:
        raise AnswerError("question cannot be empty")

    decision = decision or evaluate_abstain(chunks, thresholds)
    if decision.abstained:
        return EvidencePackage(
            question=stripped_question,
            prompt="",
            chunks=(),
            abstained=True,
            abstain_reason=decision.reason,
        )

    selected_chunks = [chunk for chunk in chunks if chunk.content.strip()][: config.max_sources]
    prompt = _render_prompt(stripped_question, build_evidence_sources(selected_chunks), config)
    if not prompt:
        raise AnswerError("prompt rendering produced an empty prompt")

    return EvidencePackage(
        question=stripped_question,
        prompt=prompt,
        chunks=tuple(selected_chunks),
        abstained=False,
        abstain_reason=None,
    )


class PromptAssemblerImpl(PromptAssembler):
    """Concrete prompt assembler used by the host and tests."""

    def __init__(
        self,
        render_config: PromptRenderConfig | None = None,
        thresholds: AbstainThresholds | object | None = None,
    ) -> None:
        self._render_config = render_config or PromptRenderConfig()
        self._thresholds = thresholds

    def build(self, question: str, chunks: Sequence[RetrievedChunk]) -> EvidencePackage:
        return build_prompt_package(
            question,
            chunks,
            render_config=self._render_config,
            thresholds=self._thresholds,
        )
