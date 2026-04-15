import type {
  ErrorFilters,
  ErrorsPayload,
  HealthResponse,
  OverviewPayload,
  ProjectsPayload,
  UiSettingsResponse,
  RequestFilters,
  RequestDetailPayload,
  RequestsPayload,
  StageFilters,
  StagesPayload,
} from "@/types/observability";

type QueryValue = string | number | boolean | null | undefined;

const rawBaseUrl = (import.meta.env.VITE_OBS_API_BASE_URL ?? "").trim();

function normalizedBaseUrl(): string {
  if (!rawBaseUrl) {
    return `${window.location.origin}/`;
  }
  if (/^https?:\/\//i.test(rawBaseUrl)) {
    return rawBaseUrl.endsWith("/") ? rawBaseUrl : `${rawBaseUrl}/`;
  }
  const relativeBase = rawBaseUrl.startsWith("/") ? rawBaseUrl : `/${rawBaseUrl}`;
  return new URL(relativeBase.endsWith("/") ? relativeBase : `${relativeBase}/`, window.location.origin).toString();
}

function buildUrl(path: string, query?: Record<string, QueryValue>): URL {
  const cleanedPath = path.replace(/^\//, "");
  const url = new URL(cleanedPath, normalizedBaseUrl());
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === null || value === undefined || value === "") {
        continue;
      }
      url.searchParams.set(key, String(value));
    }
  }
  return url;
}

async function requestJson<T>(
  path: string,
  options?: {
    method?: "GET" | "POST";
    query?: Record<string, QueryValue>;
  },
): Promise<T> {
  const response = await fetch(buildUrl(path, options?.query), {
    method: options?.method ?? "GET",
    headers: {
      Accept: "application/json",
    },
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} when requesting ${path}`);
  }
  return (await response.json()) as T;
}

export function buildStreamUrl(projectId?: string | null): string {
  return buildUrl("/api/stream", {
    project: projectId ?? undefined,
  }).toString();
}

export function getProjects(): Promise<ProjectsPayload> {
  return requestJson<ProjectsPayload>("/api/projects");
}

export function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/api/health");
}

export function getUiSettings(): Promise<UiSettingsResponse> {
  return requestJson<UiSettingsResponse>("/api/ui-settings");
}

export function getOverview(projectId?: string | null, window = "30m", limit = 12): Promise<OverviewPayload> {
  return requestJson<OverviewPayload>("/api/overview", {
    query: {
      project: projectId ?? undefined,
      window,
      limit,
    },
  });
}

export function getRequests(
  projectId?: string | null,
  window = "30m",
  limit = 12,
  filters?: Partial<RequestFilters>,
): Promise<RequestsPayload> {
  return requestJson<RequestsPayload>("/api/requests", {
    query: {
      project: projectId ?? undefined,
      window,
      limit,
      path: filters?.path ?? undefined,
      method: filters?.method ?? undefined,
      status: filters?.status ?? undefined,
      request_type: filters?.requestType ?? undefined,
    },
  });
}

export function getRequestDetail(
  requestId: string,
  projectId?: string | null,
  window = "30m",
): Promise<RequestDetailPayload> {
  return requestJson<RequestDetailPayload>(`/api/requests/${encodeURIComponent(requestId)}`, {
    query: {
      project: projectId ?? undefined,
      window,
    },
  });
}

export function getErrors(
  projectId?: string | null,
  window = "30m",
  limit = 10,
  filters?: Partial<ErrorFilters>,
): Promise<ErrorsPayload> {
  return requestJson<ErrorsPayload>("/api/errors", {
    query: {
      project: projectId ?? undefined,
      window,
      limit,
      path: filters?.path ?? undefined,
      error_type: filters?.errorType ?? undefined,
      status_code: filters?.statusCode ?? undefined,
    },
  });
}

export function getStages(
  projectId?: string | null,
  window = "30m",
  limit = 10,
  filters?: Partial<StageFilters>,
): Promise<StagesPayload> {
  return requestJson<StagesPayload>("/api/stages", {
    query: {
      project: projectId ?? undefined,
      window,
      limit,
      stage: filters?.stage ?? undefined,
    },
  });
}

export function reloadProject(projectId?: string | null): Promise<unknown> {
  return requestJson("/api/reload", {
    method: "POST",
    query: {
      project: projectId ?? undefined,
    },
  });
}
