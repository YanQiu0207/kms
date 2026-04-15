"""Pure Python citation verification for `/verify`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .contracts import AnswerError, ChunkTextProvider, VerificationDetail, VerificationResult


_CITATION_RE = re.compile(r"\[([^\[\]]+)\]")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?\.]+\s*|\n+")
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")


@dataclass(slots=True)
class CitationCheckConfig:
    """Thresholds for citation verification."""

    min_ngram_len: int = 8
    coverage_threshold: float = 0.50

    @classmethod
    def from_any(cls, value: object | None) -> "CitationCheckConfig":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        return cls(
            min_ngram_len=int(getattr(value, "min_ngram_len", cls.min_ngram_len)),
            coverage_threshold=float(getattr(value, "coverage_threshold", cls.coverage_threshold)),
        )


def extract_cited_chunk_ids(answer: str) -> tuple[str, ...]:
    """Extract unique chunk ids in the order they first appear in the answer."""

    seen: set[str] = set()
    ordered: list[str] = []
    for raw in _CITATION_RE.findall(answer):
        chunk_id = raw.strip()
        if not chunk_id or chunk_id in seen:
            continue
        seen.add(chunk_id)
        ordered.append(chunk_id)
    return tuple(ordered)


def _is_cjk_char(character: str) -> bool:
    codepoint = ord(character)
    return 0x4E00 <= codepoint <= 0x9FFF or 0x3400 <= codepoint <= 0x4DBF


def _normalize_text(text: str) -> str:
    parts: list[str] = []
    for character in text.lower():
        if character.isalnum() or _is_cjk_char(character):
            parts.append(character)
    return "".join(parts)


def _sentence_mode(sentence: str) -> str:
    if any(_is_cjk_char(character) for character in sentence):
        return "char"
    return "word"


def _tokenize_sentence(sentence: str, mode: str) -> list[str]:
    if mode == "char":
        normalized = _normalize_text(sentence)
        return [character for character in normalized if character]
    return [token.lower() for token in _WORD_RE.findall(sentence)]


def _build_ngrams(tokens: Sequence[str], min_len: int) -> list[str]:
    if len(tokens) < min_len:
        return []
    return ["".join(tokens[index : index + min_len]) for index in range(0, len(tokens) - min_len + 1)]


def _split_sentences(answer: str) -> list[str]:
    sentences = [_CITATION_RE.sub("", sentence).strip() for sentence in _SENTENCE_SPLIT_RE.split(answer)]
    return [sentence for sentence in sentences if sentence]


def _build_answer_ngrams(answer: str, min_len: int) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for sentence in _split_sentences(answer):
        mode = _sentence_mode(sentence)
        tokens = _tokenize_sentence(sentence, mode)
        for gram in _build_ngrams(tokens, min_len):
            normalized = _normalize_text(gram)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def _coerce_chunk_ids(answer: str, used_chunk_ids: Sequence[str]) -> tuple[str, ...]:
    cited = extract_cited_chunk_ids(answer)
    if not cited:
        return ()
    allowed = {item.strip() for item in used_chunk_ids if item.strip()}
    if not allowed:
        return cited
    return tuple(chunk_id for chunk_id in cited if chunk_id in allowed)


def _resolve_chunk_text_source(
    chunk_texts: Mapping[str, str] | Callable[[str], str | None] | ChunkTextProvider,
) -> Callable[[str], str | None]:
    if callable(chunk_texts):
        return chunk_texts
    if hasattr(chunk_texts, "get_chunk_text"):
        return getattr(chunk_texts, "get_chunk_text")
    if hasattr(chunk_texts, "resolve_chunk_text"):
        return getattr(chunk_texts, "resolve_chunk_text")
    if isinstance(chunk_texts, Mapping):
        return chunk_texts.get
    raise AnswerError("unsupported chunk text provider")


def verify_citations(
    answer: str,
    used_chunk_ids: Sequence[str],
    chunk_texts: Mapping[str, str] | Callable[[str], str | None] | ChunkTextProvider,
    config: CitationCheckConfig | object | None = None,
) -> VerificationResult:
    """Verify citations against the provided chunk texts."""

    cfg = CitationCheckConfig.from_any(config)
    resolver = _resolve_chunk_text_source(chunk_texts)
    chunk_ids = _coerce_chunk_ids(answer, used_chunk_ids)
    ngrams = _build_answer_ngrams(answer, cfg.min_ngram_len)

    if not ngrams:
        details = tuple(
            VerificationDetail(chunk_id=chunk_id, matched_ngrams=0, total_ngrams=0)
            for chunk_id in chunk_ids
        )
        return VerificationResult(
            citation_unverified=True,
            coverage=0.0,
            matched_chunk_ids=(),
            details=details,
        )

    resolved_texts: dict[str, str] = {}
    for chunk_id in chunk_ids:
        text = resolver(chunk_id)
        if text is None:
            continue
        resolved_texts[chunk_id] = _normalize_text(str(text))

    matched_total = 0
    matched_chunk_ids: list[str] = []
    detail_matches: dict[str, int] = {chunk_id: 0 for chunk_id in chunk_ids}

    for gram in ngrams:
        matched_any = False
        for chunk_id, normalized_text in resolved_texts.items():
            if gram and gram in normalized_text:
                detail_matches[chunk_id] = detail_matches.get(chunk_id, 0) + 1
                matched_any = True
        if matched_any:
            matched_total += 1

    for chunk_id in chunk_ids:
        if detail_matches.get(chunk_id, 0) > 0:
            matched_chunk_ids.append(chunk_id)

    total_ngrams = len(ngrams)
    coverage = matched_total / total_ngrams if total_ngrams else 0.0
    details = tuple(
        VerificationDetail(
            chunk_id=chunk_id,
            matched_ngrams=detail_matches.get(chunk_id, 0),
            total_ngrams=total_ngrams,
        )
        for chunk_id in chunk_ids
    )
    return VerificationResult(
        citation_unverified=coverage < cfg.coverage_threshold,
        coverage=round(coverage, 4),
        matched_chunk_ids=tuple(matched_chunk_ids),
        details=details,
    )


class CitationVerifierImpl:
    """Concrete verifier that can be backed by a mapping or callback."""

    def __init__(
        self,
        chunk_texts: Mapping[str, str] | Callable[[str], str | None] | ChunkTextProvider,
        config: CitationCheckConfig | object | None = None,
    ) -> None:
        self._chunk_texts = chunk_texts
        self._config = config

    def verify(self, answer: str, used_chunk_ids: Sequence[str]) -> VerificationResult:
        return verify_citations(answer, used_chunk_ids, self._chunk_texts, self._config)
