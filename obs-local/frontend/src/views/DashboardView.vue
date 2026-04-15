<script setup lang="ts">
import { computed } from "vue";

import { buildStreamUrl } from "@/api/client";
import AppShell from "@/components/AppShell.vue";
import ControlCombobox from "@/components/ControlCombobox.vue";
import ControlSelect from "@/components/ControlSelect.vue";
import ErrorList from "@/components/ErrorList.vue";
import FilterToolbar from "@/components/FilterToolbar.vue";
import LiveBadge from "@/components/LiveBadge.vue";
import ProjectRail from "@/components/ProjectRail.vue";
import RequestDetailDrawer from "@/components/RequestDetailDrawer.vue";
import RequestList from "@/components/RequestList.vue";
import SectionCard from "@/components/SectionCard.vue";
import StageBoard from "@/components/StageBoard.vue";
import StatCard from "@/components/StatCard.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import { useObservabilityStore } from "@/stores/observability";
import { useUiLocaleStore } from "@/stores/ui-locale";
import type { RequestStatus, StalenessState, UiLocaleMode } from "@/types/observability";
import { formatCount, formatLatency, formatRelativeTime } from "@/utils/format";
import type { UiTextKey } from "@/utils/i18n";
import { requestTypeLabel } from "@/utils/labels";

const store = useObservabilityStore();
const locale = useUiLocaleStore();

const windowOptions = [
  { label: "15m", value: "15m" },
  { label: "30m", value: "30m" },
  { label: "1h", value: "1h" },
  { label: "6h", value: "6h" },
] as const;

const windowSelectOptions = computed(() => windowOptions.map((item) => ({ label: item.label, value: item.value })));

const localeOptions = computed(() => [
  { value: "zh" as UiLocaleMode, label: locale.t("language_zh") },
  { value: "en" as UiLocaleMode, label: locale.t("language_en") },
  { value: "bilingual" as UiLocaleMode, label: locale.t("language_bilingual") },
]);

function uniqueText(values: Array<string | null | undefined>): string[] {
  return Array.from(
    new Set(
      values
        .map((value) => value?.trim() ?? "")
        .filter((value) => value.length > 0),
    ),
  ).sort((left, right) => left.localeCompare(right, "zh-CN"));
}

function activeFilterCount(values: Array<string | number | null>): number {
  return values.filter((value) => value !== null && value !== "").length;
}

const heroSubtitle = computed(() => {
  const projectName = store.selectedProject.value?.display_name ?? locale.t("all_projects");
  return locale.pair(
    `围绕 ${projectName} 的本地运行态观测中枢。把请求、错误、阶段雷达和实时流状态压进同一视图，排障时不再来回切页。`,
    `A local observability hub centered on ${projectName}. Requests, errors, stage radar, and live stream state stay in one view so debugging does not bounce across pages.`,
  );
});

const heroTags = computed(() => [
  locale.pair(`窗口 ${store.state.selectedWindow}`, `Window ${store.state.selectedWindow}`),
  store.selectedProject.value?.display_name ?? locale.t("all_projects"),
  locale.pair("实时流", "Live Stream"),
  locale.pair("请求钻取", "Request Drilldown"),
]);

const cards = computed(() => {
  const overview = store.state.overview;
  return [
    {
      eyebrow: locale.pair("请求数", "Requests"),
      value: formatCount(overview?.request_count),
      hint: locale.pair(`${store.state.selectedWindow} 内请求总量`, `Total requests in ${store.state.selectedWindow}`),
      emphasis: "brand" as const,
    },
    {
      eyebrow: locale.pair("错误数", "Errors"),
      value: formatCount(overview?.error_count),
      hint: locale.pair(`${formatCount(overview?.failed_request_count)} 个失败请求`, `${formatCount(overview?.failed_request_count)} failed requests`),
      emphasis: "danger" as const,
    },
    {
      eyebrow: locale.pair("P95 延迟", "P95 Latency"),
      value: formatLatency(store.requestP95Ms.value),
      hint: locale.pair("基于当前请求列表重新计算", "Recomputed from the current request list"),
      emphasis: "warning" as const,
    },
    {
      eyebrow: locale.pair("最慢阶段", "Slowest Stage"),
      value: formatLatency(store.slowestStage.value?.p95_ms),
      hint: store.slowestStage.value?.stage ?? locale.pair("等待阶段样本", "Waiting for stage samples"),
      emphasis: "neutral" as const,
    },
  ];
});

const isInitialLoading = computed(() => {
  return (
    store.state.loading &&
    store.state.requests.length === 0 &&
    store.state.errors.length === 0 &&
    store.state.stages.length === 0
  );
});

const requestPathOptions = computed(() => uniqueText(store.state.requests.map((item) => item.path)));
const requestMethodOptions = computed(() => uniqueText(store.state.requests.map((item) => item.method)));
const requestTypeOptions = computed(() => uniqueText(store.state.requests.map((item) => item.request_type)));
const errorPathOptions = computed(() => uniqueText(store.state.errors.map((item) => item.path)));
const errorTypeOptions = computed(() => uniqueText(store.state.errors.map((item) => item.error_type)));
const errorStatusCodeOptions = computed(() =>
  Array.from(
    new Set(
      store.state.errors
        .map((item) => item.status_code)
        .filter((value): value is number => typeof value === "number"),
    ),
  ).sort((left, right) => left - right),
);
const stageOptions = computed(() => uniqueText(store.state.stages.map((item) => item.stage)));
const requestMethodSelectOptions = computed(() => [
  { label: locale.t("all"), value: "" },
  ...requestMethodOptions.value.map((method) => ({ label: method, value: method })),
]);
const requestStatusSelectOptions = computed(() => [
  { label: locale.t("all"), value: "" },
  { label: locale.t("request_status_ok"), value: "ok" },
  { label: locale.t("request_status_partial"), value: "partial" },
  { label: locale.t("request_status_failed"), value: "failed" },
]);
const errorStatusCodeSelectOptions = computed(() => [
  { label: locale.t("all"), value: "" },
  ...errorStatusCodeOptions.value.map((code) => ({ label: String(code), value: String(code) })),
]);

const requestFilterCount = computed(() =>
  activeFilterCount([
    store.state.requestFilters.path,
    store.state.requestFilters.method,
    store.state.requestFilters.status,
    store.state.requestFilters.requestType,
  ]),
);
const errorFilterCount = computed(() =>
  activeFilterCount([
    store.state.errorFilters.path,
    store.state.errorFilters.errorType,
    store.state.errorFilters.statusCode,
  ]),
);
const stageFilterCount = computed(() => activeFilterCount([store.state.stageFilters.stage]));

const requestEmptyState = computed(() => {
  if (requestFilterCount.value > 0) {
    return {
      title: locale.t("no_matching_requests_title"),
      description: locale.t("no_matching_requests_desc"),
    };
  }
  return {
    title: locale.t("no_requests_title"),
    description: locale.t("no_requests_desc"),
  };
});

const errorEmptyState = computed(() => {
  if (errorFilterCount.value > 0) {
    return {
      title: locale.t("no_matching_errors_title"),
      description: locale.t("no_matching_errors_desc"),
    };
  }
  return {
    title: locale.t("no_errors_label"),
    description: locale.t("no_errors_desc"),
  };
});

const stageEmptyState = computed(() => {
  if (stageFilterCount.value > 0) {
    return {
      title: locale.t("no_matching_stages_title"),
      description: locale.t("no_matching_stages_desc"),
    };
  }
  return {
    title: locale.t("stage_empty_title"),
    description: locale.t("stage_empty_desc"),
  };
});

const streamDebugFacts = computed(() => [
  {
    label: locale.t("last_stream_message"),
    value: formatRelativeTime(store.state.lastStreamMessageAt),
  },
  {
    label: locale.t("last_topic"),
    value: store.state.lastStreamTopic ?? "--",
  },
  {
    label: locale.t("live_paused"),
    value: store.state.livePaused ? locale.t("yes") : locale.t("no"),
  },
  {
    label: locale.t("stream_url"),
    value: buildStreamUrl(store.state.selectedProjectId),
  },
]);

const liveNoticeText = computed(() => {
  const key = store.state.liveNoticeKey;
  if (!key) {
    return locale.t("waiting_live_init");
  }
  return locale.t(key as UiTextKey);
});

function handleSelectRequest(requestId: string): void {
  void store.selectRequest(requestId);
}

function handleRequestStatusChange(value: string): void {
  void store.setRequestFilters({
    status: (value || null) as RequestStatus | null,
  });
}

function handleErrorStatusCodeChange(value: string): void {
  void store.setErrorFilters({
    statusCode: value ? Number(value) : null,
  });
}

function handleLocaleSelect(mode: UiLocaleMode): void {
  locale.setMode(mode);
}

function stalenessTone(staleness: StalenessState | null): "success" | "warning" | "danger" | "neutral" {
  if (staleness === "live") {
    return "success";
  }
  if (staleness === "idle") {
    return "neutral";
  }
  if (staleness === "stale") {
    return "warning";
  }
  return "danger";
}

function stalenessLabel(staleness: StalenessState | null): string {
  if (staleness === "live") {
    return locale.t("staleness_fresh");
  }
  if (staleness === "idle") {
    return locale.t("staleness_idle");
  }
  if (staleness === "stale") {
    return locale.t("staleness_stale");
  }
  return locale.t("staleness_offline");
}

function stalenessHint(staleness: StalenessState | null): string {
  if (staleness === "live") {
    return locale.pair(
      "当前项目最近仍有新事件进入窗口，页面展示的数据是新鲜的。",
      "Recent events are still entering the selected window, so the dashboard data is fresh.",
    );
  }
  if (staleness === "idle") {
    return locale.pair(
      "数据源当前在线，但最近一段时间没有新的业务事件进入窗口。",
      "The source is online, but no new business events have entered the selected window recently.",
    );
  }
  if (staleness === "stale") {
    return locale.pair(
      "数据源未完全离线，但最新事件已经偏旧，需要留意 tail 或上游服务。",
      "The source is not fully offline, but its latest events are old enough to warrant checking the tail or upstream service.",
    );
  }
  return locale.pair(
    "当前没有可用数据源，或项目尚未产生可观测事件。",
    "No data source is currently available, or the project has not emitted observable events yet.",
  );
}
</script>

<template>
  <AppShell
    :title="locale.t('brand_title')"
    :eyebrow="locale.t('brand_eyebrow')"
    :signature="locale.t('brand_signature')"
    brand-mark="脉"
    :subtitle="heroSubtitle"
    :tags="heroTags"
  >
    <template #hero-side>
      <div class="dashboard-view__hero-panel">
        <div class="dashboard-view__status-row">
          <div class="dashboard-view__status-group">
            <LiveBadge :state="store.state.transportState" />
            <StatusBadge
              :tone="stalenessTone(store.state.staleness)"
              :label="stalenessLabel(store.state.staleness)"
              :hint="stalenessHint(store.state.staleness)"
            />
          </div>
          <div class="dashboard-view__locale-switch" :aria-label="locale.t('language_label')" role="group">
            <button
              v-for="item in localeOptions"
              :key="item.value"
              type="button"
              class="dashboard-view__locale-pill"
              :class="{ 'dashboard-view__locale-pill--active': locale.mode.value === item.value }"
              @click="handleLocaleSelect(item.value)"
            >
              {{ item.label }}
            </button>
          </div>
        </div>
        <p class="dashboard-view__live-notice">{{ liveNoticeText }}</p>
        <dl class="dashboard-view__facts">
          <div>
            <dt>{{ locale.t("latest_event") }}</dt>
            <dd>{{ formatRelativeTime(store.state.overview?.last_event_at ?? store.selectedProject.value?.last_event_at) }}</dd>
          </div>
          <div>
            <dt>{{ locale.t("last_sync") }}</dt>
            <dd>{{ formatRelativeTime(store.state.lastSyncAt) }}</dd>
          </div>
          <div>
            <dt>{{ locale.t("reconnect_count") }}</dt>
            <dd>{{ formatCount(store.state.reconnectCount) }}</dd>
          </div>
          <div>
            <dt>{{ locale.t("last_disconnect") }}</dt>
            <dd>{{ formatRelativeTime(store.state.lastDisconnectAt) }}</dd>
          </div>
        </dl>
        <div class="dashboard-view__controls">
          <label>
            <span>{{ locale.t("window_label") }}</span>
            <ControlSelect
              :model-value="store.state.selectedWindow"
              :options="windowSelectOptions"
              :aria-label="locale.t('window_label')"
              min-width="6.5rem"
              @update:model-value="store.setWindow"
            />
          </label>
          <button type="button" :disabled="store.state.reloading" @click="store.reload()">
            {{ store.state.reloading ? locale.t("reloading") : locale.t("reload") }}
          </button>
          <button v-if="!store.state.livePaused" type="button" class="button--ghost" @click="store.pauseLive()">
            {{ locale.t("pause_live") }}
          </button>
          <button v-else type="button" class="button--ghost" @click="store.resumeLive()">
            {{ locale.t("resume_live") }}
          </button>
        </div>
        <dl class="dashboard-view__debug-panel">
          <div v-for="fact in streamDebugFacts" :key="fact.label">
            <dt>{{ fact.label }}</dt>
            <dd>{{ fact.value }}</dd>
          </div>
        </dl>
      </div>
    </template>

    <template #sidebar>
      <ProjectRail
        :projects="store.state.projects"
        :selected-project-id="store.state.selectedProjectId"
        @select="store.selectProject"
      />
    </template>

    <div class="dashboard-view">
      <div v-if="store.state.errorMessage" class="dashboard-view__error">
        {{ store.state.errorMessage }}
      </div>

      <div v-if="isInitialLoading" class="dashboard-view__loading-banner">
        {{ locale.t("loading_home_snapshot") }}
      </div>

      <div class="dashboard-view__stats">
        <StatCard
          v-for="card in cards"
          :key="card.eyebrow"
          :eyebrow="card.eyebrow"
          :value="card.value"
          :hint="card.hint"
          :emphasis="card.emphasis"
        />
      </div>

      <div class="dashboard-view__grid">
        <SectionCard :title="locale.t('request_feed')" :subtitle="locale.t('request_feed_subtitle')">
          <template #header>
            <FilterToolbar :active-count="requestFilterCount" @clear="store.clearRequestFilters()">
              <label>
                <span>{{ locale.t("path") }}</span>
                <ControlCombobox
                  :model-value="store.state.requestFilters.path ?? ''"
                  :options="requestPathOptions"
                  :aria-label="locale.t('path')"
                  placeholder="/ask"
                  min-width="12rem"
                  @update:model-value="store.setRequestFilters({ path: $event })"
                />
              </label>
              <label>
                <span>{{ locale.t("method") }}</span>
                <ControlSelect
                  :model-value="store.state.requestFilters.method ?? ''"
                  :options="requestMethodSelectOptions"
                  :aria-label="locale.t('method')"
                  min-width="8rem"
                  @update:model-value="store.setRequestFilters({ method: $event || null })"
                />
              </label>
              <label>
                <span>{{ locale.t("status") }}</span>
                <ControlSelect
                  :model-value="store.state.requestFilters.status ?? ''"
                  :options="requestStatusSelectOptions"
                  :aria-label="locale.t('status')"
                  min-width="8rem"
                  @update:model-value="handleRequestStatusChange"
                />
              </label>
              <label>
                <span>{{ locale.t("type") }}</span>
                <ControlCombobox
                  :model-value="store.state.requestFilters.requestType ?? ''"
                  :options="requestTypeOptions"
                  :aria-label="locale.t('type')"
                  :placeholder="requestTypeLabel('ask', locale.mode.value)"
                  min-width="11rem"
                  @update:model-value="store.setRequestFilters({ requestType: $event })"
                />
              </label>
            </FilterToolbar>
          </template>
          <RequestList
            :items="store.state.requests"
            :selected-request-id="store.state.selectedRequestId"
            :empty-title="requestEmptyState.title"
            :empty-description="requestEmptyState.description"
            @select="handleSelectRequest"
          />
        </SectionCard>

        <SectionCard :title="locale.t('error_feed')" :subtitle="locale.t('error_feed_subtitle')">
          <template #header>
            <FilterToolbar :active-count="errorFilterCount" @clear="store.clearErrorFilters()">
              <label>
                <span>{{ locale.t("path") }}</span>
                <ControlCombobox
                  :model-value="store.state.errorFilters.path ?? ''"
                  :options="errorPathOptions"
                  :aria-label="locale.t('path')"
                  placeholder="/search"
                  min-width="12rem"
                  @update:model-value="store.setErrorFilters({ path: $event })"
                />
              </label>
              <label>
                <span>{{ locale.t("error_type") }}</span>
                <ControlCombobox
                  :model-value="store.state.errorFilters.errorType ?? ''"
                  :options="errorTypeOptions"
                  :aria-label="locale.t('error_type')"
                  :placeholder="locale.pair('超时错误', 'TimeoutError')"
                  min-width="13rem"
                  @update:model-value="store.setErrorFilters({ errorType: $event })"
                />
              </label>
              <label>
                <span>{{ locale.t("status_code") }}</span>
                <ControlSelect
                  :model-value="store.state.errorFilters.statusCode !== null ? String(store.state.errorFilters.statusCode) : ''"
                  :options="errorStatusCodeSelectOptions"
                  :aria-label="locale.t('status_code')"
                  min-width="8rem"
                  @update:model-value="handleErrorStatusCodeChange"
                />
              </label>
            </FilterToolbar>
          </template>
          <ErrorList
            :items="store.state.errors"
            :empty-title="errorEmptyState.title"
            :empty-description="errorEmptyState.description"
          />
        </SectionCard>
      </div>

      <SectionCard :title="locale.t('stage_radar')" :subtitle="locale.t('stage_radar_subtitle')">
        <template #header>
          <FilterToolbar :active-count="stageFilterCount" @clear="store.clearStageFilters()">
            <label>
              <span>{{ locale.t("stage") }}</span>
              <ControlCombobox
                :model-value="store.state.stageFilters.stage ?? ''"
                :options="stageOptions"
                :aria-label="locale.t('stage')"
                placeholder="query.plan.fetch"
                min-width="13rem"
                @update:model-value="store.setStageFilters({ stage: $event })"
              />
            </label>
          </FilterToolbar>
        </template>
        <StageBoard
          :items="store.state.stages"
          :empty-title="stageEmptyState.title"
          :empty-description="stageEmptyState.description"
        />
      </SectionCard>
    </div>

    <RequestDetailDrawer
      :visible="store.state.selectedRequestId !== null"
      :request-id="store.state.selectedRequestId"
      :detail="store.state.requestDetail"
      :loading="store.state.requestDetailLoading"
      :error="store.state.requestDetailError"
      :synced-at="store.state.requestDetailSyncedAt"
      @close="store.selectRequest(null)"
    />
  </AppShell>
</template>

<style scoped>
.dashboard-view {
  display: grid;
  gap: 1.25rem;
}

.dashboard-view__hero-panel {
  display: grid;
  gap: 0.9rem;
}

.dashboard-view__locale-switch {
  display: inline-grid;
  grid-auto-flow: column;
  align-items: center;
  gap: 0.28rem;
  margin-left: auto;
  border-radius: 999px;
  background:
    linear-gradient(135deg, rgba(76, 201, 215, 0.08), rgba(96, 165, 250, 0.06)),
    linear-gradient(180deg, rgba(16, 25, 44, 0.92), rgba(10, 17, 31, 0.96));
  border: 1px solid color-mix(in srgb, var(--color-border-strong) 82%, rgba(122, 230, 242, 0.28) 18%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.05),
    0 10px 26px rgba(2, 8, 23, 0.22);
  padding: 0.22rem;
}

.dashboard-view__locale-pill {
  min-height: 1.95rem;
  min-width: 4.7rem;
  padding: 0 0.82rem;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-secondary);
  font: inherit;
  font-size: 0.76rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  cursor: pointer;
  transition:
    color 140ms ease,
    background 140ms ease,
    box-shadow 140ms ease,
    transform 140ms ease;
}

.dashboard-view__locale-pill:hover {
  color: var(--color-text-primary);
  background: rgba(255, 255, 255, 0.04);
}

.dashboard-view__locale-pill--active {
  color: #effbff;
  background:
    linear-gradient(135deg, rgba(76, 201, 215, 0.22), rgba(96, 165, 250, 0.16)),
    linear-gradient(180deg, rgba(27, 45, 78, 0.96), rgba(15, 26, 48, 0.98));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    0 6px 16px rgba(5, 12, 24, 0.22),
    0 0 0 1px rgba(122, 230, 242, 0.18);
}

.dashboard-view__locale-pill:focus-visible {
  outline: none;
  color: var(--color-text-primary);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    0 0 0 2px rgba(76, 201, 215, 0.16);
}

.dashboard-view__locale-pill:active {
  transform: translateY(1px);
}

.dashboard-view__status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.65rem;
  flex-wrap: wrap;
}

.dashboard-view__status-group {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  flex-wrap: wrap;
}

.dashboard-view__live-notice {
  margin: 0;
  color: var(--color-text-secondary);
  line-height: 1.65;
}

.dashboard-view__facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.8rem;
  margin: 0;
}

.dashboard-view__facts div {
  padding: 0.85rem 0.95rem;
  border-radius: var(--radius-card);
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.04);
}

.dashboard-view__facts dt {
  margin-bottom: 0.3rem;
  color: var(--color-text-tertiary);
  font-size: 0.76rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.dashboard-view__facts dd {
  margin: 0;
  color: var(--color-text-primary);
  font-family: var(--font-mono);
}

.dashboard-view__controls {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  flex-wrap: wrap;
}

.dashboard-view__controls label {
  display: inline-flex;
  align-items: center;
  gap: 0.55rem;
}

.dashboard-view__controls span {
  font-size: 0.86rem;
  color: var(--color-text-secondary);
}

.dashboard-view__controls select,
.dashboard-view__controls button {
  min-height: 2.65rem;
  padding: 0 0.95rem;
  border: 1px solid var(--color-border-strong);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.05);
  color: var(--color-text-primary);
  font: inherit;
}

.dashboard-view__controls button {
  cursor: pointer;
}

.dashboard-view__controls .button--ghost {
  background: transparent;
}

.dashboard-view__debug-panel {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.65rem;
  margin: 0;
}

.dashboard-view__debug-panel div {
  padding: 0.75rem 0.85rem;
  border-radius: var(--radius-card);
  border: 1px dashed color-mix(in srgb, var(--color-border-strong) 68%, transparent 32%);
  background: rgba(255, 255, 255, 0.03);
}

.dashboard-view__debug-panel dt {
  margin-bottom: 0.28rem;
  color: var(--color-text-tertiary);
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.dashboard-view__debug-panel dd {
  margin: 0;
  color: var(--color-text-primary);
  font-family: var(--font-mono);
  font-size: 0.83rem;
  line-height: 1.45;
  word-break: break-all;
}

.dashboard-view__error {
  padding: 0.9rem 1rem;
  border: 1px solid color-mix(in srgb, var(--color-semantic-danger-strong) 25%, var(--color-border-subtle) 75%);
  border-radius: var(--radius-card);
  background: var(--color-semantic-danger-soft);
  color: var(--color-semantic-danger-strong);
}

.dashboard-view__loading-banner {
  padding: 0.74rem 0.86rem;
  border-radius: calc(var(--radius-card) - 0.2rem);
  border: 1px dashed var(--color-border-strong);
  color: var(--color-text-secondary);
  background: color-mix(in srgb, var(--color-brand-soft) 80%, transparent 20%);
}

.dashboard-view__stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1rem;
}

.dashboard-view__stats :deep(.stat-card) {
  animation: dashboard-rise 520ms ease both;
}

.dashboard-view__stats :deep(.stat-card:nth-child(2)) {
  animation-delay: 80ms;
}

.dashboard-view__stats :deep(.stat-card:nth-child(3)) {
  animation-delay: 160ms;
}

.dashboard-view__stats :deep(.stat-card:nth-child(4)) {
  animation-delay: 240ms;
}

.dashboard-view__grid {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(18rem, 1fr);
  gap: 1.25rem;
}

@media (max-width: 1180px) {
  .dashboard-view__stats,
  .dashboard-view__grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .dashboard-view__facts {
    grid-template-columns: 1fr;
  }

  .dashboard-view__debug-panel {
    grid-template-columns: 1fr;
  }
}

@keyframes dashboard-rise {
  from {
    opacity: 0;
    transform: translateY(18px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
