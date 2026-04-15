from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from .state_store import ProjectState, SQLiteStateStore, SourceState


def default_state_db_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "state.db"


def _normalize_redact_fields(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return tuple(str(item) for item in value if str(item).strip())
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item).strip())
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        return tuple(segment.strip() for segment in text.split(",") if segment.strip())
    return ()


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


@dataclass(slots=True)
class SourceSpec:
    project_id: str
    source_id: str
    log_path: str
    name: str | None = None
    format: str = "jsonl"
    timezone: str = "Asia/Shanghai"
    service_hint: str | None = None
    redact_fields: tuple[str, ...] = ()
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_state(self) -> SourceState:
        return SourceState(
            project_id=self.project_id,
            source_id=self.source_id,
            name=self.name or self.source_id,
            log_path=self.log_path,
            format=self.format,
            timezone=self.timezone,
            service_hint=self.service_hint,
            redact_fields=tuple(self.redact_fields),
            enabled=self.enabled,
            metadata=dict(self.metadata),
        )

    @classmethod
    def from_state(cls, source: SourceState) -> SourceSpec:
        return cls(
            project_id=source.project_id,
            source_id=source.source_id,
            log_path=source.log_path,
            name=source.name,
            format=source.format,
            timezone=source.timezone,
            service_hint=source.service_hint,
            redact_fields=tuple(source.redact_fields),
            enabled=source.enabled,
            metadata=dict(source.metadata),
        )


@dataclass(slots=True)
class ProjectSpec:
    project_id: str
    name: str | None = None
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    sources: tuple[SourceSpec, ...] = ()

    def with_source(self, source: SourceSpec) -> ProjectSpec:
        if source.project_id != self.project_id:
            raise ValueError(f"source {source.source_id} belongs to {source.project_id}, expected {self.project_id}")
        return replace(self, sources=self.sources + (source,))

    def to_state(self) -> ProjectState:
        return ProjectState(
            project_id=self.project_id,
            name=self.name or self.project_id,
            enabled=self.enabled,
            metadata=dict(self.metadata),
        )

    @classmethod
    def from_state(cls, project: ProjectState, sources: Iterable[SourceState] = ()) -> ProjectSpec:
        return cls(
            project_id=project.project_id,
            name=project.name,
            enabled=project.enabled,
            metadata=dict(project.metadata),
            sources=tuple(SourceSpec.from_state(source) for source in sources),
        )


@dataclass(slots=True)
class RegistrySnapshot:
    projects: tuple[ProjectSpec, ...]

    @property
    def sources(self) -> tuple[SourceSpec, ...]:
        items: list[SourceSpec] = []
        for project in self.projects:
            items.extend(project.sources)
        return tuple(items)


class SourceRegistry:
    """In-memory registry backed by SQLite state metadata."""

    def __init__(
        self,
        state_store: SQLiteStateStore | str | Path | None = None,
        *,
        initialize: bool = True,
    ) -> None:
        if state_store is None:
            state_store = default_state_db_path()
        if isinstance(state_store, SQLiteStateStore):
            self._store = state_store
        else:
            self._store = SQLiteStateStore(state_store, initialize=initialize)
        self._projects: dict[str, ProjectSpec] = {}
        self.reload()

    @property
    def store(self) -> SQLiteStateStore:
        return self._store

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> SourceRegistry:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def reload(self) -> RegistrySnapshot:
        projects = self._store.list_projects()
        sources = self._store.get_sources()
        grouped: dict[str, list[SourceState]] = {}
        for source in sources:
            grouped.setdefault(source.project_id, []).append(source)

        self._projects = {
            project.project_id: ProjectSpec.from_state(project, grouped.get(project.project_id, ()))
            for project in projects
        }
        return self.snapshot()

    def snapshot(self) -> RegistrySnapshot:
        return RegistrySnapshot(projects=self.list_projects())

    def list_projects(self) -> tuple[ProjectSpec, ...]:
        return tuple(self._projects[project_id] for project_id in sorted(self._projects))

    def list_sources(self, project_id: str | None = None) -> tuple[SourceSpec, ...]:
        if project_id is None:
            items: list[SourceSpec] = []
            for project in self.list_projects():
                items.extend(project.sources)
            return tuple(items)
        project = self._projects.get(project_id)
        if project is None:
            return ()
        return project.sources

    def get_project(self, project_id: str) -> ProjectSpec | None:
        return self._projects.get(project_id)

    def get_source(self, project_id: str, source_id: str) -> SourceSpec | None:
        project = self._projects.get(project_id)
        if project is None:
            return None
        for source in project.sources:
            if source.source_id == source_id:
                return source
        return None

    def register_project(self, project: ProjectSpec) -> ProjectSpec:
        saved_project = self._store.upsert_project(project.to_state())
        saved_sources = self._store.replace_project_sources(
            project.project_id,
            [source.to_state() for source in project.sources],
        )
        saved = ProjectSpec.from_state(saved_project, saved_sources)
        self._projects[project.project_id] = saved
        return saved

    def register_source(self, source: SourceSpec) -> SourceSpec:
        existing_project = self._store.get_project(source.project_id)
        saved_project = self._store.upsert_project(
            ProjectState(
                project_id=source.project_id,
                name=(existing_project.name if existing_project else source.project_id),
                enabled=existing_project.enabled if existing_project else True,
                metadata=dict(existing_project.metadata) if existing_project else {},
                created_at=existing_project.created_at if existing_project else None,
            )
        )
        saved_source = self._store.upsert_source(source.to_state())
        project = self._projects.get(source.project_id)
        if project is None:
            project = ProjectSpec.from_state(saved_project)
        sources = {item.source_id: item for item in project.sources}
        sources[source.source_id] = SourceSpec.from_state(saved_source)
        updated = replace(project, sources=tuple(sorted(sources.values(), key=lambda item: item.source_id)))
        self._projects[source.project_id] = updated
        return SourceSpec.from_state(saved_source)

    def register_many(self, projects: Iterable[ProjectSpec]) -> tuple[ProjectSpec, ...]:
        results: list[ProjectSpec] = []
        for project in projects:
            results.append(self.register_project(project))
        return tuple(results)

    def merge_declared_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        enabled: bool = True,
        metadata: Mapping[str, Any] | None = None,
        sources: Iterable[Mapping[str, Any] | SourceSpec] = (),
    ) -> ProjectSpec:
        normalized_sources: list[SourceSpec] = []
        for source in sources:
            if isinstance(source, SourceSpec):
                normalized_sources.append(source)
                continue
            normalized_sources.append(
                SourceSpec(
                    project_id=project_id,
                    source_id=str(source.get("source_id") or source.get("name") or "main"),
                    log_path=str(source.get("log_path") or ""),
                    name=str(source.get("name") or source.get("source_id") or project_id),
                    format=str(source.get("format") or "jsonl"),
                    timezone=str(source.get("timezone") or "Asia/Shanghai"),
                    service_hint=(str(source.get("service_hint")) if source.get("service_hint") is not None else None),
                    redact_fields=_normalize_redact_fields(source.get("redact_fields")),
                    enabled=_as_bool(source.get("enabled", True)),
                    metadata=dict(source.get("metadata") or {}),
                )
            )
        project = ProjectSpec(
            project_id=project_id,
            name=name or project_id,
            enabled=enabled,
            metadata=dict(metadata or {}),
            sources=tuple(normalized_sources),
        )
        return self.register_project(project)


__all__ = [
    "ProjectSpec",
    "RegistrySnapshot",
    "SourceRegistry",
    "SourceSpec",
    "default_state_db_path",
]
