import { computed, reactive, readonly } from "vue";

import {
  buildStreamUrl,
  getErrors,
  getHealth,
  getOverview,
  getProjects,
  getRequestDetail,
  getRequests,
  getStages,
  reloadProject,
} from "@/api/client";
import { useEventStream, type EventStreamController, type StreamMessage } from "@/composables/useEventStream";
import { extractStreamEnvelopes } from "@/stores/stream-envelope";
import type {
  AggregationOverview,
  ErrorFilters,
  ErrorSummary,
  HealthResponse,
  OverviewPayload,
  ProjectHealth,
  ProjectInfo,
  RequestFilters,
  RequestDetailPayload,
  RequestSummary,
  StageFilters,
  StageStats,
  StreamEnvelope,
  StalenessState,
  TransportState,
} from "@/types/observability";

interface ObservabilityState {
  started: boolean;
  loading: boolean;
  reloading: boolean;
  errorMessage: string | null;
  selectedProjectId: string | null;
  selectedRequestId: string | null;
  selectedWindow: string;
  livePaused: boolean;
  transportState: TransportState;
  reconnectCount: number;
  lastDisconnectAt: string | null;
  projects: ProjectInfo[];
  health: HealthResponse | null;
  overview: AggregationOverview | null;
  staleness: StalenessState | null;
  projectMeta: ProjectInfo | null;
  requests: RequestSummary[];
  errors: ErrorSummary[];
  stages: StageStats[];
  requestDetail: RequestDetailPayload | null;
  requestDetailLoading: boolean;
  requestDetailError: string | null;
  requestDetailSyncedAt: string | null;
  lastSyncAt: string | null;
  lastStreamMessageAt: string | null;
  lastStreamTopic: string | null;
  liveNoticeKey: string | null;
  requestFilters: RequestFilters;
  errorFilters: ErrorFilters;
  stageFilters: StageFilters;
}

const REQUEST_FEED_LIMIT = 24;
const ERROR_FEED_LIMIT = 18;
const STAGE_FEED_LIMIT = 12;

const state = reactive<ObservabilityState>({
  started: false,
  loading: false,
  reloading: false,
  errorMessage: null,
  selectedProjectId: null,
  selectedRequestId: null,
  selectedWindow: "30m",
  livePaused: false,
  transportState: "idle",
  reconnectCount: 0,
  lastDisconnectAt: null,
  projects: [],
  health: null,
  overview: null,
  staleness: null,
  projectMeta: null,
  requests: [],
  errors: [],
  stages: [],
  requestDetail: null,
  requestDetailLoading: false,
  requestDetailError: null,
  requestDetailSyncedAt: null,
  lastSyncAt: null,
  lastStreamMessageAt: null,
  lastStreamTopic: null,
  liveNoticeKey: null,
  requestFilters: {
    path: null,
    method: null,
    status: null,
    requestType: null,
  },
  errorFilters: {
    path: null,
    errorType: null,
    statusCode: null,
  },
  stageFilters: {
    stage: null,
  },
});

let streamController: EventStreamController | null = null;
let startPromise: Promise<void> | null = null;
let snapshotSequence = 0;
let collectionSequence = 0;
let projectSelectionPinned = false;
let detailSequence = 0;
let detailRefreshTimer: ReturnType<typeof setTimeout> | null = null;
let collectionRefreshTimer: ReturnType<typeof setTimeout> | null = null;
let windowRefreshSequence = 0;
let windowRefreshTimer: ReturnType<typeof setTimeout> | null = null;

function percentile(values: number[], percentileValue: number): number | null {
  if (!values.length) {
    return null;
  }
  const ordered = [...values].sort((left, right) => left - right);
  if (ordered.length === 1) {
    return ordered[0];
  }
  const rank = percentileValue * (ordered.length - 1);
  const lowerIndex = Math.floor(rank);
  const upperIndex = Math.min(lowerIndex + 1, ordered.length - 1);
  const fraction = rank - lowerIndex;
  return ordered[lowerIndex] * (1 - fraction) + ordered[upperIndex] * fraction;
}

function normalizeFilterText(value: string | null | undefined): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  const text = value.trim();
  return text || null;
}

function hasRequestFilters(filters: RequestFilters = state.requestFilters): boolean {
  return Boolean(filters.path || filters.method || filters.status || filters.requestType);
}

function hasErrorFilters(filters: ErrorFilters = state.errorFilters): boolean {
  return Boolean(filters.path || filters.errorType || filters.statusCode !== null);
}

function hasStageFilters(filters: StageFilters = state.stageFilters): boolean {
  return Boolean(filters.stage);
}

function requestFiltersQuery(): RequestFilters {
  return {
    path: normalizeFilterText(state.requestFilters.path),
    method: normalizeFilterText(state.requestFilters.method),
    status: state.requestFilters.status,
    requestType: normalizeFilterText(state.requestFilters.requestType),
  };
}

function errorFiltersQuery(): ErrorFilters {
  return {
    path: normalizeFilterText(state.errorFilters.path),
    errorType: normalizeFilterText(state.errorFilters.errorType),
    statusCode: state.errorFilters.statusCode,
  };
}

function stageFiltersQuery(): StageFilters {
  return {
    stage: normalizeFilterText(state.stageFilters.stage),
  };
}

function syncSelectedProject(projects: readonly ProjectInfo[]): void {
  if (!projects.length) {
    state.selectedProjectId = null;
    return;
  }
  if (state.selectedProjectId === null && projectSelectionPinned) {
    return;
  }
  if (state.selectedProjectId && projects.some((item) => item.project_id === state.selectedProjectId)) {
    return;
  }
  state.selectedProjectId = projects[0].project_id;
}

function applyOverviewPayload(payload: OverviewPayload): void {
  state.overview = payload.overview;
  state.staleness = payload.staleness;
  state.projectMeta = payload.project;
}

function computeGlobalStaleness(projects: readonly ProjectInfo[]): StalenessState {
  if (!projects.length) {
    return "offline";
  }
  if (projects.some((item) => item.staleness === "live")) {
    return "live";
  }
  if (projects.some((item) => item.staleness === "stale")) {
    return "stale";
  }
  if (projects.some((item) => item.staleness === "idle")) {
    return "idle";
  }
  return "offline";
}

function applyProjectMetaFromCurrentSelection(): void {
  if (!state.selectedProjectId) {
    state.projectMeta = null;
    state.staleness = computeGlobalStaleness(state.projects);
    return;
  }
  const matched = state.projects.find((item) => item.project_id === state.selectedProjectId) ?? null;
  state.projectMeta = matched;
  state.staleness = matched?.staleness ?? "offline";
}

function clearDetailRefreshTimer(): void {
  if (detailRefreshTimer) {
    clearTimeout(detailRefreshTimer);
    detailRefreshTimer = null;
  }
}

function clearCollectionRefreshTimer(): void {
  if (collectionRefreshTimer) {
    clearTimeout(collectionRefreshTimer);
    collectionRefreshTimer = null;
  }
}

function clearWindowRefreshTimer(): void {
  if (windowRefreshTimer) {
    clearTimeout(windowRefreshTimer);
    windowRefreshTimer = null;
  }
}

function resetRequestDetailState(): void {
  clearDetailRefreshTimer();
  detailSequence += 1;
  state.selectedRequestId = null;
  state.requestDetail = null;
  state.requestDetailLoading = false;
  state.requestDetailError = null;
  state.requestDetailSyncedAt = null;
}

function applyCollectionPayloads(
  requestsPayload: { items: readonly RequestSummary[] },
  errorsPayload: { items: readonly ErrorSummary[] },
  stagesPayload: { items: readonly StageStats[] },
): void {
  state.requests = [...requestsPayload.items];
  state.errors = [...errorsPayload.items];
  state.stages = [...stagesPayload.items];
  state.lastSyncAt = new Date().toISOString();
}

function hydrateProjectsFromHealth(healthProjects: readonly ProjectHealth[]): ProjectInfo[] {
  const healthByProjectId = new Map(healthProjects.map((item) => [item.project_id, item]));
  return state.projects.map((project) => {
    const health = healthByProjectId.get(project.project_id);
    if (!health) {
      return project;
    }
    return {
      ...project,
      status: health.status,
      staleness: health.staleness,
      last_event_at: health.last_event_at,
      replaying: health.replaying,
      tailer_error: health.tailer_error,
    };
  });
}

async function fetchSnapshot(): Promise<boolean> {
  const sequence = ++snapshotSequence;
  const targetCollectionSequence = ++collectionSequence;
  state.loading = true;
  state.errorMessage = null;
  try {
    const projectsPayload = await getProjects();
    if (sequence !== snapshotSequence) {
      return false;
    }
    state.projects = [...projectsPayload.projects];
    syncSelectedProject(projectsPayload.projects);

    const projectId = state.selectedProjectId;
    const window = state.selectedWindow;
    const [health, overviewPayload, requestsPayload, errorsPayload, stagesPayload] = await Promise.all([
      getHealth(),
      getOverview(projectId, window),
      getRequests(projectId, window, REQUEST_FEED_LIMIT, requestFiltersQuery()),
      getErrors(projectId, window, ERROR_FEED_LIMIT, errorFiltersQuery()),
      getStages(projectId, window, STAGE_FEED_LIMIT, stageFiltersQuery()),
    ]);
    if (sequence !== snapshotSequence || targetCollectionSequence !== collectionSequence) {
      return false;
    }

    state.health = health;
    state.projects = hydrateProjectsFromHealth(health.projects);
    applyOverviewPayload(overviewPayload);
    applyCollectionPayloads(requestsPayload, errorsPayload, stagesPayload);
    if (state.selectedRequestId) {
      void fetchRequestDetailById(state.selectedRequestId, { silent: true });
    }
    return true;
  } catch (error) {
    state.errorMessage = error instanceof Error ? error.message : "加载观测数据失败";
    return false;
  } finally {
    if (sequence === snapshotSequence) {
      state.loading = false;
    }
  }
}

async function refreshFilteredCollections(options?: { preserveError?: boolean }): Promise<boolean> {
  const sequence = ++collectionSequence;
  if (!options?.preserveError) {
    state.errorMessage = null;
  }
  try {
    const projectId = state.selectedProjectId;
    const window = state.selectedWindow;
    const [requestsPayload, errorsPayload, stagesPayload] = await Promise.all([
      getRequests(projectId, window, REQUEST_FEED_LIMIT, requestFiltersQuery()),
      getErrors(projectId, window, ERROR_FEED_LIMIT, errorFiltersQuery()),
      getStages(projectId, window, STAGE_FEED_LIMIT, stageFiltersQuery()),
    ]);
    if (sequence !== collectionSequence) {
      return false;
    }
    applyCollectionPayloads(requestsPayload, errorsPayload, stagesPayload);
    if (state.selectedRequestId) {
      void fetchRequestDetailById(state.selectedRequestId, { silent: true });
    }
    return true;
  } catch (error) {
    if (sequence !== collectionSequence || options?.preserveError) {
      return false;
    }
    state.errorMessage = error instanceof Error ? error.message : "刷新过滤结果失败";
    return false;
  }
}

function scheduleFilteredCollectionsRefresh(delayMs = 180): void {
  clearCollectionRefreshTimer();
  collectionRefreshTimer = setTimeout(() => {
    collectionRefreshTimer = null;
    void refreshFilteredCollections({ preserveError: true });
  }, delayMs);
}

async function refreshWindowScopedSnapshot(options?: { preserveError?: boolean }): Promise<boolean> {
  const sequence = ++windowRefreshSequence;
  if (!options?.preserveError) {
    state.errorMessage = null;
  }
  try {
    const projectId = state.selectedProjectId;
    const window = state.selectedWindow;
    const [overviewPayload, requestsPayload, errorsPayload, stagesPayload] = await Promise.all([
      getOverview(projectId, window),
      getRequests(projectId, window, REQUEST_FEED_LIMIT, requestFiltersQuery()),
      getErrors(projectId, window, ERROR_FEED_LIMIT, errorFiltersQuery()),
      getStages(projectId, window, STAGE_FEED_LIMIT, stageFiltersQuery()),
    ]);
    if (sequence !== windowRefreshSequence) {
      return false;
    }
    applyOverviewPayload(overviewPayload);
    applyCollectionPayloads(requestsPayload, errorsPayload, stagesPayload);
    if (state.selectedRequestId) {
      void fetchRequestDetailById(state.selectedRequestId, { silent: true });
    }
    return true;
  } catch (error) {
    if (sequence !== windowRefreshSequence || options?.preserveError) {
      return false;
    }
    state.errorMessage = error instanceof Error ? error.message : "刷新窗口快照失败";
    return false;
  }
}

function scheduleWindowScopedRefresh(delayMs = 180): void {
  clearWindowRefreshTimer();
  windowRefreshTimer = setTimeout(() => {
    windowRefreshTimer = null;
    void refreshWindowScopedSnapshot({ preserveError: true });
  }, delayMs);
}

async function fetchRequestDetailById(requestId: string, options?: { silent?: boolean }): Promise<boolean> {
  if (!requestId) {
    return false;
  }
  const silent = options?.silent ?? false;
  const sequence = ++detailSequence;
  const shouldShowLoading = !silent || state.requestDetail === null;
  if (shouldShowLoading) {
    state.requestDetailLoading = true;
  }
  state.requestDetailError = null;
  try {
    const detail = await getRequestDetail(requestId, state.selectedProjectId, state.selectedWindow);
    if (sequence !== detailSequence || state.selectedRequestId !== requestId) {
      return false;
    }
    state.requestDetail = detail;
    state.requestDetailSyncedAt = new Date().toISOString();
    return true;
  } catch (error) {
    if (sequence !== detailSequence || state.selectedRequestId !== requestId) {
      return false;
    }
    state.requestDetail = null;
    state.requestDetailError = error instanceof Error ? error.message : "加载请求详情失败";
    return false;
  } finally {
    if (sequence === detailSequence && state.selectedRequestId === requestId) {
      state.requestDetailLoading = false;
    }
  }
}

function scheduleRequestDetailRefresh(delayMs = 180): void {
  if (!state.selectedRequestId) {
    return;
  }
  clearDetailRefreshTimer();
  detailRefreshTimer = setTimeout(() => {
    detailRefreshTimer = null;
    const requestId = state.selectedRequestId;
    if (!requestId) {
      return;
    }
    void fetchRequestDetailById(requestId, { silent: true });
  }, delayMs);
}

function applyStreamEnvelope(envelope: StreamEnvelope): void {
  state.lastStreamMessageAt = new Date().toISOString();
  state.lastStreamTopic = envelope.topic;
  const topic = envelope.topic;
  if (topic === "live") {
    const payload = envelope.payload as Record<string, unknown> | null;
    const liveStatus = typeof payload?.status === "string" ? payload.status : null;
    if (liveStatus === "overflow") {
      state.liveNoticeKey = "stream_backpressure";
      void fetchSnapshot();
      return;
    }
    if (liveStatus === "connected") {
      state.liveNoticeKey = "stream_connected";
      return;
    }
    if (liveStatus === "heartbeat") {
      state.liveNoticeKey = "stream_active";
      return;
    }
    return;
  }
  if (topic === "health.updated") {
    state.health = envelope.payload as HealthResponse;
    state.projects = hydrateProjectsFromHealth(state.health.projects);
    applyProjectMetaFromCurrentSelection();
    scheduleRequestDetailRefresh();
    return;
  }
  if (topic === "overview.updated") {
    scheduleWindowScopedRefresh();
    return;
  }
  if (topic === "requests.updated") {
    scheduleWindowScopedRefresh();
    return;
  }
  if (topic === "errors.updated") {
    scheduleWindowScopedRefresh();
    return;
  }
  if (topic === "stages.updated") {
    scheduleWindowScopedRefresh();
  }
}

function handleStreamMessage(message: StreamMessage): void {
  for (const envelope of extractStreamEnvelopes(message)) {
    applyStreamEnvelope(envelope);
  }
}

function bindStream(): void {
  streamController?.dispose();
  streamController = useEventStream({
    url: () => buildStreamUrl(state.selectedProjectId),
    onMessage: handleStreamMessage,
    onStatusChange: (nextStatus) => {
      state.transportState = nextStatus;
      if (nextStatus === "live") {
        state.liveNoticeKey = state.livePaused ? "live_paused_notice" : "stream_connected";
      } else if (nextStatus === "reconnecting") {
        state.reconnectCount += 1;
        state.lastDisconnectAt = new Date().toISOString();
        state.liveNoticeKey = "stream_reconnecting";
      } else if (nextStatus === "paused") {
        state.liveNoticeKey = "live_paused_notice";
      } else if (nextStatus === "error") {
        state.lastDisconnectAt = new Date().toISOString();
        state.liveNoticeKey = "stream_degraded";
      }
    },
  });
  if (!state.livePaused) {
    streamController.connect();
  }
}

async function start(): Promise<void> {
  if (state.started) {
    return;
  }
  if (startPromise) {
    return startPromise;
  }
  startPromise = (async () => {
    await fetchSnapshot();
    bindStream();
    state.started = true;
  })();
  try {
    await startPromise;
  } finally {
    startPromise = null;
  }
}

function stop(): void {
  streamController?.dispose();
  streamController = null;
  clearDetailRefreshTimer();
  clearCollectionRefreshTimer();
  clearWindowRefreshTimer();
  state.started = false;
  state.transportState = "idle";
}

async function selectProject(projectId: string | null): Promise<void> {
  if (projectId !== state.selectedProjectId) {
    resetRequestDetailState();
  }
  projectSelectionPinned = true;
  state.selectedProjectId = projectId;
  await fetchSnapshot();
  bindStream();
}

async function setWindow(window: string): Promise<void> {
  if (window === state.selectedWindow) {
    return;
  }
  state.selectedWindow = window;
  await fetchSnapshot();
}

async function setRequestFilters(next: Partial<RequestFilters>): Promise<void> {
  const normalized: RequestFilters = {
    path: next.path !== undefined ? normalizeFilterText(next.path) : state.requestFilters.path,
    method: next.method !== undefined ? normalizeFilterText(next.method) : state.requestFilters.method,
    status: next.status !== undefined ? next.status : state.requestFilters.status,
    requestType:
      next.requestType !== undefined ? normalizeFilterText(next.requestType) : state.requestFilters.requestType,
  };
  if (
    normalized.path === state.requestFilters.path
    && normalized.method === state.requestFilters.method
    && normalized.status === state.requestFilters.status
    && normalized.requestType === state.requestFilters.requestType
  ) {
    return;
  }
  state.requestFilters.path = normalized.path;
  state.requestFilters.method = normalized.method;
  state.requestFilters.status = normalized.status;
  state.requestFilters.requestType = normalized.requestType;
  await refreshFilteredCollections();
}

async function clearRequestFilters(): Promise<void> {
  await setRequestFilters({
    path: null,
    method: null,
    status: null,
    requestType: null,
  });
}

async function setErrorFilters(next: Partial<ErrorFilters>): Promise<void> {
  const normalized: ErrorFilters = {
    path: next.path !== undefined ? normalizeFilterText(next.path) : state.errorFilters.path,
    errorType: next.errorType !== undefined ? normalizeFilterText(next.errorType) : state.errorFilters.errorType,
    statusCode: next.statusCode !== undefined ? next.statusCode : state.errorFilters.statusCode,
  };
  if (
    normalized.path === state.errorFilters.path
    && normalized.errorType === state.errorFilters.errorType
    && normalized.statusCode === state.errorFilters.statusCode
  ) {
    return;
  }
  state.errorFilters.path = normalized.path;
  state.errorFilters.errorType = normalized.errorType;
  state.errorFilters.statusCode = normalized.statusCode;
  await refreshFilteredCollections();
}

async function clearErrorFilters(): Promise<void> {
  await setErrorFilters({
    path: null,
    errorType: null,
    statusCode: null,
  });
}

async function setStageFilters(next: Partial<StageFilters>): Promise<void> {
  const normalized: StageFilters = {
    stage: next.stage !== undefined ? normalizeFilterText(next.stage) : state.stageFilters.stage,
  };
  if (normalized.stage === state.stageFilters.stage) {
    return;
  }
  state.stageFilters.stage = normalized.stage;
  await refreshFilteredCollections();
}

async function clearStageFilters(): Promise<void> {
  await setStageFilters({ stage: null });
}

function pauseLive(): void {
  state.livePaused = true;
  streamController?.pause();
}

async function resumeLive(): Promise<void> {
  state.livePaused = false;
  streamController?.resume();
  await fetchSnapshot();
}

async function reload(): Promise<void> {
  state.reloading = true;
  state.errorMessage = null;
  try {
    await reloadProject(state.selectedProjectId);
    await fetchSnapshot();
  } catch (error) {
    state.errorMessage = error instanceof Error ? error.message : "重载失败";
  } finally {
    state.reloading = false;
  }
}

async function selectRequest(requestId: string | null): Promise<void> {
  if (!requestId) {
    resetRequestDetailState();
    return;
  }
  state.selectedRequestId = requestId;
  await fetchRequestDetailById(requestId);
}

const selectedProject = computed(() => state.projects.find((item) => item.project_id === state.selectedProjectId) ?? null);
const selectedRequest = computed(() => state.requests.find((item) => item.request_id === state.selectedRequestId) ?? null);
const requestP95Ms = computed(() => {
  const durations = state.requests
    .map((item) => item.duration_ms)
    .filter((value): value is number => typeof value === "number");
  return percentile(durations, 0.95);
});
const slowestStage = computed(() => state.stages[0] ?? null);

export function useObservabilityStore() {
  return {
    state: readonly(state),
    selectedProject,
    selectedRequest,
    requestP95Ms,
    slowestStage,
    start,
    stop,
    selectProject,
    selectRequest,
    setWindow,
    setRequestFilters,
    clearRequestFilters,
    setErrorFilters,
    clearErrorFilters,
    setStageFilters,
    clearStageFilters,
    pauseLive,
    resumeLive,
    reload,
  };
}
