"""Adapter contracts and placeholders."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Protocol


@dataclass(slots=True)
class AdapterMetadata:
    """Minimal adapter metadata used for orchestration and tracing."""

    adapter_id: str
    name: str = ""
    capabilities: tuple[str, ...] = field(default_factory=tuple)


class AdapterError(RuntimeError):
    """Raised when a source adapter cannot read content."""


class SourceAdapter(Protocol):
    """Generic adapter boundary for external sources."""

    metadata: AdapterMetadata

    def iter_items(self) -> Iterable[dict[str, object]]:
        raise NotImplementedError


class PlaceholderSourceAdapter:
    """Import-safe stub for future source integrations."""

    metadata = AdapterMetadata(adapter_id="placeholder")

    def iter_items(self) -> Iterable[dict[str, object]]:
        raise NotImplementedError("source adapter is not implemented yet")
