"""Answer package skeleton."""

from .contracts import (
    AnswerError,
    CitationVerifier,
    ChunkTextProvider,
    EvidencePackage,
    EvidenceSource,
    PlaceholderCitationVerifier,
    PlaceholderPromptAssembler,
    PromptAssembler,
    VerificationDetail,
    VerificationResult,
)
from .citation_check import (
    CitationCheckConfig,
    CitationVerifierImpl,
    extract_cited_chunk_ids,
    verify_citations,
)
from .guardrail import AbstainThresholds, GuardrailDecision, evaluate_abstain
from .prompt import (
    DEFAULT_SYSTEM_PROMPT,
    PromptAssemblerImpl,
    PromptRenderConfig,
    build_evidence_sources,
    build_prompt_package,
)

__all__ = [
    "AbstainThresholds",
    "AnswerError",
    "CitationCheckConfig",
    "CitationVerifier",
    "CitationVerifierImpl",
    "EvidencePackage",
    "EvidenceSource",
    "ChunkTextProvider",
    "DEFAULT_SYSTEM_PROMPT",
    "GuardrailDecision",
    "PlaceholderCitationVerifier",
    "PlaceholderPromptAssembler",
    "PromptAssemblerImpl",
    "PromptAssembler",
    "PromptRenderConfig",
    "VerificationDetail",
    "VerificationResult",
    "build_evidence_sources",
    "build_prompt_package",
    "evaluate_abstain",
    "extract_cited_chunk_ids",
    "verify_citations",
]
