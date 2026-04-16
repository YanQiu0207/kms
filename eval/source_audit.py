from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import PurePath

from app.config import AppConfig, load_config
from app.store import SQLiteMetadataStore


@dataclass(slots=True)
class SourceAuditBucket:
    name: str
    document_count: int
    chunk_count: int


@dataclass(slots=True)
class SourceAuditSnapshot:
    document_count: int
    chunk_count: int
    front_matter_docs: int
    front_matter_ratio: float
    category_docs: int
    category_ratio: float
    tag_docs: int
    tag_ratio: float
    alias_docs: int
    alias_ratio: float
    by_source_id: list[SourceAuditBucket] = field(default_factory=list)
    by_top_level_path: list[SourceAuditBucket] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "document_count": self.document_count,
            "chunk_count": self.chunk_count,
            "front_matter_docs": self.front_matter_docs,
            "front_matter_ratio": self.front_matter_ratio,
            "category_docs": self.category_docs,
            "category_ratio": self.category_ratio,
            "tag_docs": self.tag_docs,
            "tag_ratio": self.tag_ratio,
            "alias_docs": self.alias_docs,
            "alias_ratio": self.alias_ratio,
            "by_source_id": [asdict(item) for item in self.by_source_id],
            "by_top_level_path": [asdict(item) for item in self.by_top_level_path],
        }


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _top_level_path(metadata: dict[str, object], file_path: str) -> str:
    relative_path = str(metadata.get("relative_path") or "").strip()
    if relative_path:
        return relative_path.replace("\\", "/").split("/", 1)[0]
    if file_path:
        return PurePath(file_path).parts[-2] if len(PurePath(file_path).parts) >= 2 else PurePath(file_path).name
    return "(unknown)"


def snapshot_source_audit(config: AppConfig | None = None) -> SourceAuditSnapshot:
    settings = config or load_config()
    document_count = 0
    chunk_count = 0
    front_matter_docs = 0
    category_docs = 0
    tag_docs = 0
    alias_docs = 0
    source_documents: Counter[str] = Counter()
    source_chunks: Counter[str] = Counter()
    path_documents: Counter[str] = Counter()
    path_chunks: Counter[str] = Counter()

    with SQLiteMetadataStore(settings.data.sqlite) as store:
        for document in store.iter_documents():
            document_count += 1
            metadata = dict(document.metadata or {})
            source_id = str(metadata.get("source_id") or "(unknown)")
            top_level_path = _top_level_path(metadata, document.file_path)
            source_documents[source_id] += 1
            path_documents[top_level_path] += 1

            has_category = bool(str(metadata.get("front_matter_category") or "").strip())
            has_tags = bool(metadata.get("front_matter_tags"))
            has_aliases = bool(metadata.get("front_matter_aliases"))
            if has_category or has_tags or has_aliases:
                front_matter_docs += 1
            if has_category:
                category_docs += 1
            if has_tags:
                tag_docs += 1
            if has_aliases:
                alias_docs += 1

        for chunk in store.iter_chunks():
            chunk_count += 1
            metadata = dict(chunk.metadata or {})
            source_id = str(metadata.get("source_id") or "(unknown)")
            top_level_path = _top_level_path(metadata, chunk.file_path)
            source_chunks[source_id] += 1
            path_chunks[top_level_path] += 1

    by_source_id = [
        SourceAuditBucket(name=name, document_count=source_documents[name], chunk_count=source_chunks.get(name, 0))
        for name in sorted(source_documents)
    ]
    by_top_level_path = [
        SourceAuditBucket(name=name, document_count=path_documents[name], chunk_count=path_chunks.get(name, 0))
        for name, _ in path_documents.most_common(12)
    ]
    return SourceAuditSnapshot(
        document_count=document_count,
        chunk_count=chunk_count,
        front_matter_docs=front_matter_docs,
        front_matter_ratio=_ratio(front_matter_docs, document_count),
        category_docs=category_docs,
        category_ratio=_ratio(category_docs, document_count),
        tag_docs=tag_docs,
        tag_ratio=_ratio(tag_docs, document_count),
        alias_docs=alias_docs,
        alias_ratio=_ratio(alias_docs, document_count),
        by_source_id=by_source_id,
        by_top_level_path=by_top_level_path,
    )
