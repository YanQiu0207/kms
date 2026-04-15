from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, ConfigDict, field_validator, model_validator


class BaseSchema(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, str_strip_whitespace=True)


HealthStatus = Literal["ok", "degraded", "error"]
StalenessState = Literal["live", "idle", "stale", "offline"]
SourceFormat = Literal["jsonl", "plain_text"]
RequestStatus = Literal["ok", "failed", "partial"]
P95Confidence = Literal["low", "medium", "high"]
UiLocaleMode = Literal["zh", "en", "bilingual"]


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class ServerConfig(BaseSchema):
    host: str = "127.0.0.1"
    port: int = 49154

    @field_validator("host")
    @classmethod
    def _validate_host(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("host cannot be empty")
        return cleaned

    @field_validator("port")
    @classmethod
    def _validate_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("port must be between 1 and 65535")
        return value


class StorageConfig(BaseSchema):
    state_db_path: str = "./data/state.db"

    @field_validator("state_db_path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("path cannot be empty")
        return cleaned


class LoggingConfig(BaseSchema):
    level: str = "INFO"
    log_dir: str | None = None

    @field_validator("level")
    @classmethod
    def _validate_level(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("level cannot be empty")
        return cleaned

    @field_validator("log_dir")
    @classmethod
    def _validate_log_dir(cls, value: str | None) -> str | None:
        return _clean_text(value)


class RuntimeConfig(BaseSchema):
    tail_poll_interval_seconds: float = 1.0
    max_cached_records: int = 50_000

    @field_validator("tail_poll_interval_seconds")
    @classmethod
    def _validate_tail_poll_interval_seconds(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("tail_poll_interval_seconds must be positive")
        return float(value)

    @field_validator("max_cached_records")
    @classmethod
    def _validate_max_cached_records(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_cached_records must be at least 1")
        return int(value)


class TailerConfig(BaseSchema):
    chunk_size: int = 64 * 1024
    encoding: str = "utf-8"
    errors: str = "replace"

    @field_validator("chunk_size")
    @classmethod
    def _validate_chunk_size(cls, value: int) -> int:
        if value < 1024:
            raise ValueError("chunk_size must be at least 1024 bytes")
        return int(value)

    @field_validator("encoding", "errors")
    @classmethod
    def _validate_text_options(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value cannot be empty")
        return cleaned


class StreamConfig(BaseSchema):
    path: str = "/api/stream"
    heartbeat_ms: int = 15_000
    batch_window_ms: int = 250
    batch_max_items: int = 16
    max_queue_size: int = 256

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("path cannot be empty")
        if not cleaned.startswith("/"):
            raise ValueError("path must start with '/'")
        return cleaned

    @field_validator("heartbeat_ms")
    @classmethod
    def _validate_heartbeat_ms(cls, value: int) -> int:
        if value < 200:
            raise ValueError("heartbeat_ms must be at least 200")
        return int(value)

    @field_validator("batch_window_ms")
    @classmethod
    def _validate_batch_window_ms(cls, value: int) -> int:
        if value < 0:
            raise ValueError("batch_window_ms cannot be negative")
        return int(value)

    @field_validator("batch_max_items", "max_queue_size")
    @classmethod
    def _validate_positive_int(cls, value: int) -> int:
        if value < 1:
            raise ValueError("value must be at least 1")
        return int(value)


class AggregationConfig(BaseSchema):
    top_n: int = 20
    request_stage_limit: int = 5

    @field_validator("top_n", "request_stage_limit")
    @classmethod
    def _validate_positive_int(cls, value: int) -> int:
        if value < 1:
            raise ValueError("value must be at least 1")
        return int(value)


class UiConfig(BaseSchema):
    default_locale: UiLocaleMode = "bilingual"

    @field_validator("default_locale")
    @classmethod
    def _validate_default_locale(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in {"zh", "en", "bilingual"}:
            raise ValueError("default_locale must be zh, en, or bilingual")
        return cleaned


class SourceConfig(BaseSchema):
    source_id: str
    log_path: str = Field(validation_alias=AliasChoices("log_path", "path"))
    format: SourceFormat = "jsonl"
    timezone: str = "Asia/Shanghai"
    service_hint: str | None = None
    redact_fields: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("source_id", "log_path", "timezone")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value cannot be empty")
        return cleaned

    @field_validator("service_hint")
    @classmethod
    def _validate_service_hint(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @field_validator("redact_fields")
    @classmethod
    def _validate_redact_fields(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            candidate = item.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            cleaned.append(candidate)
        return cleaned

    @field_validator("format")
    @classmethod
    def _validate_format(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in {"jsonl", "plain_text"}:
            raise ValueError("format must be jsonl or plain_text")
        return cleaned


class ProjectConfig(BaseSchema):
    project_id: str = Field(validation_alias=AliasChoices("project_id", "name"))
    display_name: str | None = None
    enabled: bool = True
    summary_mapping: dict[str, str] = Field(default_factory=dict)
    sources: list[SourceConfig] = Field(default_factory=list)

    @field_validator("project_id")
    @classmethod
    def _validate_project_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("project_id cannot be empty")
        return cleaned

    @field_validator("display_name")
    @classmethod
    def _validate_display_name(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @field_validator("summary_mapping")
    @classmethod
    def _validate_summary_mapping(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for key, mapped_field in value.items():
            map_key = key.strip()
            map_value = mapped_field.strip()
            if not map_key or not map_value:
                continue
            cleaned[map_key] = map_value
        return cleaned

    @model_validator(mode="after")
    def _validate_sources(self) -> "ProjectConfig":
        seen: set[str] = set()
        for source in self.sources:
            if source.source_id in seen:
                raise ValueError(f"duplicate source_id in project {self.project_id!r}: {source.source_id!r}")
            seen.add(source.source_id)
        return self


class AppConfig(BaseSchema):
    server: ServerConfig = Field(default_factory=ServerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    tailer: TailerConfig = Field(default_factory=TailerConfig)
    stream: StreamConfig = Field(default_factory=StreamConfig)
    aggregation: AggregationConfig = Field(default_factory=AggregationConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    projects: list[ProjectConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_projects(self) -> "AppConfig":
        seen: set[str] = set()
        for project in self.projects:
            if project.project_id in seen:
                raise ValueError(f"duplicate project_id: {project.project_id!r}")
            seen.add(project.project_id)
        return self


class ServiceHealth(BaseSchema):
    service: str = "obs-local"
    status: HealthStatus = "ok"
    version: str | None = None
    started_at: str | None = None
    replaying: bool = False
    tailer_error: str | None = None

    @field_validator("service", "version", "started_at", "tailer_error")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return _clean_text(value)


class SourceHealth(BaseSchema):
    project_id: str
    source_id: str
    log_path: str
    status: HealthStatus = "ok"
    staleness: StalenessState = "live"
    last_event_at: str | None = None
    replaying: bool = False
    tailer_error: str | None = None

    @field_validator("project_id", "source_id", "log_path", "last_event_at", "tailer_error")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return _clean_text(value)


class ProjectHealth(BaseSchema):
    project_id: str
    display_name: str | None = None
    status: HealthStatus = "ok"
    staleness: StalenessState = "live"
    last_event_at: str | None = None
    replaying: bool = False
    tailer_error: str | None = None
    sources: list[SourceHealth] = Field(default_factory=list)

    @field_validator("project_id", "display_name", "last_event_at", "tailer_error")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return _clean_text(value)


class HealthResponse(BaseSchema):
    service: ServiceHealth = Field(default_factory=ServiceHealth)
    projects: list[ProjectHealth] = Field(default_factory=list)
    generated_at: str | None = None

    @field_validator("generated_at")
    @classmethod
    def _validate_generated_at(cls, value: str | None) -> str | None:
        return _clean_text(value)


class UiSettingsResponse(BaseSchema):
    default_locale: UiLocaleMode = "bilingual"
    available_locales: list[UiLocaleMode] = Field(default_factory=lambda: ["zh", "en", "bilingual"])


class StageTiming(BaseSchema):
    stage: str
    duration_ms: float
    self_duration_ms: float | None = None
    event: str | None = None
    status: str | None = None
    timestamp: str | None = None

    @field_validator("stage", "event", "status", "timestamp")
    @classmethod
    def _validate_stage_text(cls, value: str | None) -> str | None:
        return _clean_text(value)


class TimelineEvent(BaseSchema):
    timestamp: str | None = None
    event: str | None = None
    event_type: str | None = None
    span_name: str | None = None
    request_id: str | None = None
    level: str | None = None
    status: str | None = None
    status_code: int | None = None
    duration_ms: float | None = None
    error_type: str | None = None
    summary: str | None = None
    path: str | None = None
    method: str | None = None

    @field_validator(
        "timestamp",
        "event",
        "event_type",
        "span_name",
        "request_id",
        "level",
        "status",
        "error_type",
        "summary",
        "path",
        "method",
    )
    @classmethod
    def _validate_timeline_text(cls, value: str | None) -> str | None:
        return _clean_text(value)


class RequestSummary(BaseSchema):
    project_id: str
    request_id: str
    request_type: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    method: str | None = None
    path: str | None = None
    status_code: int | None = None
    status: RequestStatus = "partial"
    duration_ms: float | None = None
    summary: str | None = None
    top_stages: list[StageTiming] = Field(default_factory=list)
    error_count: int = 0
    last_event_at: str | None = None
    partial: bool = False

    @field_validator(
        "project_id",
        "request_id",
        "request_type",
        "started_at",
        "ended_at",
        "method",
        "path",
        "summary",
        "last_event_at",
    )
    @classmethod
    def _validate_request_text(cls, value: str | None) -> str | None:
        return _clean_text(value)


class ErrorSummary(BaseSchema):
    project_id: str
    timestamp: str | None = None
    request_id: str | None = None
    event: str | None = None
    path: str | None = None
    error_type: str | None = None
    message: str | None = None
    detail: str | None = None
    level: str | None = None
    status_code: int | None = None

    @field_validator(
        "project_id",
        "timestamp",
        "request_id",
        "event",
        "path",
        "error_type",
        "message",
        "detail",
        "level",
    )
    @classmethod
    def _validate_error_text(cls, value: str | None) -> str | None:
        return _clean_text(value)


class StageStats(BaseSchema):
    project_id: str
    stage: str
    count: int = 0
    error_count: int = 0
    avg_ms: float = 0.0
    p95_ms: float = 0.0
    max_ms: float = 0.0
    last_seen_at: str | None = None
    p95_confidence: P95Confidence = "low"

    @field_validator("project_id", "stage", "last_seen_at")
    @classmethod
    def _validate_stage_stats_text(cls, value: str | None) -> str | None:
        return _clean_text(value)


class AggregationOverview(BaseSchema):
    scope_project_id: str | None = None
    generated_at: str | None = None
    first_event_at: str | None = None
    last_event_at: str | None = None
    request_count: int = 0
    failed_request_count: int = 0
    partial_request_count: int = 0
    error_count: int = 0
    stage_count: int = 0

    @field_validator(
        "scope_project_id",
        "generated_at",
        "first_event_at",
        "last_event_at",
    )
    @classmethod
    def _validate_overview_text(cls, value: str | None) -> str | None:
        return _clean_text(value)


class RequestDetail(BaseSchema):
    summary: RequestSummary
    timeline: list[TimelineEvent] = Field(default_factory=list)
    stages: list[StageTiming] = Field(default_factory=list)
    errors: list[ErrorSummary] = Field(default_factory=list)


class AggregationResult(BaseSchema):
    overview: AggregationOverview
    requests: list[RequestSummary] = Field(default_factory=list)
    errors: list[ErrorSummary] = Field(default_factory=list)
    stages: list[StageStats] = Field(default_factory=list)
    request_details: list[RequestDetail] = Field(default_factory=list)
