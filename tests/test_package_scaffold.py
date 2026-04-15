from __future__ import annotations

import importlib


def test_core_skeleton_modules_import():
    modules = [
        "app.ingest",
        "app.store",
        "app.retrieve",
        "app.answer",
        "app.adapters",
    ]

    for module_name in modules:
        module = importlib.import_module(module_name)
        assert module.__name__ == module_name


def test_placeholder_contracts_are_available():
    from app.answer import (
        EvidencePackage,
        PlaceholderCitationVerifier,
        PlaceholderPromptAssembler,
        VerificationResult,
    )
    from app.ingest import IngestBatch, PlaceholderIngestor
    from app.retrieve import RetrievedChunk, PlaceholderRetrievalService
    from app.store import DocumentRecord, PlaceholderStoreWriter

    assert IngestBatch(source_id="source-1").source_id == "source-1"
    assert DocumentRecord(document_id="doc-1", content="x").content == "x"
    assert RetrievedChunk(document_id="doc-1", content="x").document_id == "doc-1"
    assert EvidencePackage(question="q", prompt="p").question == "q"
    assert VerificationResult(citation_unverified=False, coverage=1.0).coverage == 1.0

    assert isinstance(PlaceholderIngestor(), PlaceholderIngestor)
    assert isinstance(PlaceholderStoreWriter(), PlaceholderStoreWriter)
    assert isinstance(PlaceholderRetrievalService(), PlaceholderRetrievalService)
    assert isinstance(PlaceholderPromptAssembler(), PlaceholderPromptAssembler)
    assert isinstance(PlaceholderCitationVerifier(), PlaceholderCitationVerifier)
