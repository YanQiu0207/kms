export type HealthStatus = "ok" | "degraded" | "error";
export type StalenessState = "live" | "idle" | "stale" | "offline";
export type RequestStatus = "ok" | "failed" | "partial";
export type P95Confidence = "low" | "medium" | "high";
export type TransportState = "idle" | "connecting" | "live" | "reconnecting" | "paused" | "error";
export type UiLocaleMode = "zh" | "en" | "bilingual";

export interface RequestFilters {
  path: string | null;
  method: string | null;
  status: RequestStatus | null;
  requestType: string | null;
}

export interface ErrorFilters {
  path: string | null;
  errorType: string | null;
  statusCode: number | null;
}

export interface StageFilters {
  stage: string | null;
}

export interface SourceInfo {
  project_id: string;
  source_id: string;
  name: string;
  log_path: string;
  format: string;
  timezone: string;
  service_hint: string | null;
  redact_fields: readonly string[];
  enabled: boolean;
  metadata: Record<string, string>;
  status: HealthStatus;
  staleness: StalenessState;
  last_event_at: string | null;
  replaying: boolean;
  tailer_error: string | null;
}

export interface ProjectInfo {
  project_id: string;
  name: string;
  display_name: string;
  enabled: boolean;
  metadata: Record<string, unknown>;
  status: HealthStatus;
  staleness: StalenessState;
  last_event_at: string | null;
  replaying: boolean;
  tailer_error: string | null;
  source_count: number;
  sources: readonly SourceInfo[];
}

export interface ProjectsPayload {
  generated_at: string;
  count: number;
  projects: readonly ProjectInfo[];
}

export interface ServiceHealth {
  service: string;
  status: HealthStatus;
  version: string | null;
  started_at: string | null;
  replaying: boolean;
  tailer_error: string | null;
}

export interface ProjectHealth {
  project_id: string;
  display_name: string | null;
  status: HealthStatus;
  staleness: StalenessState;
  last_event_at: string | null;
  replaying: boolean;
  tailer_error: string | null;
}

export interface HealthResponse {
  service: ServiceHealth;
  projects: readonly ProjectHealth[];
  generated_at: string | null;
}

export interface UiSettingsResponse {
  default_locale: UiLocaleMode;
  available_locales: readonly UiLocaleMode[];
}

export interface StageTiming {
  stage: string;
  duration_ms: number;
  self_duration_ms: number | null;
  event: string | null;
  status: string | null;
  timestamp: string | null;
}

export interface RequestSummary {
  project_id: string;
  request_id: string;
  request_type: string | null;
  started_at: string | null;
  ended_at: string | null;
  method: string | null;
  path: string | null;
  status_code: number | null;
  status: RequestStatus;
  duration_ms: number | null;
  summary: string | null;
  top_stages: readonly StageTiming[];
  error_count: number;
  last_event_at: string | null;
  partial: boolean;
  failed_request?: boolean;
  source_ids?: readonly string[];
  event_count?: number;
  stage_count?: number;
}

export interface ErrorSummary {
  project_id: string;
  timestamp: string | null;
  request_id: string | null;
  event: string | null;
  path: string | null;
  error_type: string | null;
  message: string | null;
  detail: string | null;
  level: string | null;
  status_code: number | null;
}

export interface StageStats {
  project_id: string;
  stage: string;
  count: number;
  error_count: number;
  avg_ms: number;
  p95_ms: number;
  max_ms: number;
  last_seen_at: string | null;
  p95_confidence: P95Confidence;
}

export interface AggregationOverview {
  scope_project_id: string | null;
  generated_at: string | null;
  first_event_at: string | null;
  last_event_at: string | null;
  request_count: number;
  failed_request_count: number;
  partial_request_count: number;
  error_count: number;
  stage_count: number;
}

export interface OverviewPayload {
  generated_at: string;
  project_id: string | null;
  window: string | null;
  overview: AggregationOverview;
  request_p95_ms: number | null;
  slowest_stage: StageStats | null;
  staleness: StalenessState | null;
  last_event_at: string | null;
  project: ProjectInfo | null;
  top_requests: readonly RequestSummary[];
  top_errors: readonly ErrorSummary[];
  top_stages: readonly StageStats[];
}

export interface RequestsPayload {
  project_id: string | null;
  limit: number;
  count: number;
  items: readonly RequestSummary[];
}

export interface ErrorsPayload {
  project_id: string | null;
  limit: number;
  count: number;
  items: readonly ErrorSummary[];
}

export interface TimelineEvent {
  timestamp: string | null;
  event: string | null;
  event_type: string | null;
  span_name: string | null;
  request_id: string | null;
  level: string | null;
  status: string | null;
  status_code: number | null;
  duration_ms: number | null;
  error_type: string | null;
  summary: string | null;
  path: string | null;
  method: string | null;
}

export interface RequestDetailPayload {
  request_id?: string;
  project_id?: string | null;
  summary: RequestSummary;
  timeline: readonly TimelineEvent[];
  stages: readonly StageTiming[];
  errors: readonly ErrorSummary[];
}

export interface StagesPayload {
  project_id: string | null;
  window: string | null;
  limit: number;
  count: number;
  items: readonly StageStats[];
}

export interface StreamScope {
  project_id: string | null;
  source_id: string | null;
}

export interface StreamEnvelope<T = unknown> {
  topic: string;
  scope: StreamScope;
  generated_at: string | null;
  payload: T;
}

export interface StreamBatchItem {
  event: string;
  topic: string;
  data: StreamEnvelope;
}

export interface StreamBatchPayload {
  count: number;
  topics: readonly string[];
  items: readonly StreamBatchItem[];
}
