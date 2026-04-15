<script setup lang="ts">
import { computed } from "vue";

import EmptyState from "@/components/EmptyState.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import { useUiLocaleStore } from "@/stores/ui-locale";
import type { RequestDetailPayload, RequestSummary, TimelineEvent } from "@/types/observability";
import { formatDateTime, formatLatency, formatRelativeTime } from "@/utils/format";
import { eventLabel, routeLabel, stageLabel } from "@/utils/labels";

const props = defineProps<{
  visible: boolean;
  requestId: string | null;
  detail: RequestDetailPayload | null;
  loading: boolean;
  error: string | null;
  syncedAt: string | null;
}>();

const emit = defineEmits<{
  close: [];
}>();

const locale = useUiLocaleStore();

const summary = computed<RequestSummary | null>(() => props.detail?.summary ?? null);
const timeline = computed(() => props.detail?.timeline ?? []);
const stages = computed(() => props.detail?.stages ?? []);
const errors = computed(() => props.detail?.errors ?? []);

function requestTone(status: RequestSummary["status"] | null): "success" | "warning" | "danger" | "neutral" {
  if (status === "ok") {
    return "success";
  }
  if (status === "partial") {
    return "warning";
  }
  if (status === "failed") {
    return "danger";
  }
  return "neutral";
}

function requestStatusLabel(status: RequestSummary["status"] | null): string {
  if (status === "ok") {
    return locale.t("request_status_ok");
  }
  if (status === "partial") {
    return locale.t("request_status_partial");
  }
  if (status === "failed") {
    return locale.t("request_status_failed");
  }
  return locale.t("request_status_unknown");
}

function timelineTone(item: TimelineEvent): "success" | "warning" | "danger" | "neutral" | "info" {
  if (item.level === "ERROR" || item.status === "error" || item.error_type) {
    return "danger";
  }
  if (item.event_type === "error") {
    return "danger";
  }
  if (item.event_type === "end") {
    return "success";
  }
  if (item.event_type === "start") {
    return "info";
  }
  return "neutral";
}

function eventTypeLabel(eventType: string | null): string {
  if (eventType === "start") {
    return locale.t("event_type_start");
  }
  if (eventType === "end") {
    return locale.t("event_type_end");
  }
  if (eventType === "error") {
    return locale.t("event_type_error");
  }
  return locale.t("event_type_event");
}
</script>

<template>
  <Transition name="detail-drawer">
    <aside v-if="visible" class="request-detail-drawer">
      <header class="request-detail-drawer__header">
        <div>
          <p>{{ locale.t("request_detail") }}</p>
          <h2>{{ requestId ?? locale.pair("未选择请求", "No Request Selected") }}</h2>
        </div>
        <button type="button" @click="emit('close')">{{ locale.t("close") }}</button>
      </header>

      <div v-if="summary" class="request-detail-drawer__summary">
        <div class="request-detail-drawer__summary-row">
          <strong>{{ routeLabel(summary.path, summary.request_type, locale.mode.value) }}</strong>
          <StatusBadge :tone="requestTone(summary.status)" :label="requestStatusLabel(summary.status)" />
        </div>
        <dl>
          <div>
            <dt>{{ locale.t("start_time") }}</dt>
            <dd>{{ formatDateTime(summary.started_at) }}</dd>
          </div>
          <div>
            <dt>{{ locale.t("end_time") }}</dt>
            <dd>{{ formatDateTime(summary.ended_at) }}</dd>
          </div>
          <div>
            <dt>{{ locale.t("duration") }}</dt>
            <dd>{{ formatLatency(summary.duration_ms) }}</dd>
          </div>
          <div>
            <dt>{{ locale.t("last_sync") }}</dt>
            <dd>{{ formatRelativeTime(syncedAt) }}</dd>
          </div>
        </dl>
      </div>

      <p v-if="error" class="request-detail-drawer__error">{{ error }}</p>

      <div v-if="loading && !detail" class="request-detail-drawer__loading">
        {{ locale.t("loading_request_detail") }}
      </div>

      <EmptyState
        v-else-if="!detail"
        :title="locale.t('request_detail_empty_title')"
        :description="locale.t('request_detail_empty_desc')"
      />

      <div v-else class="request-detail-drawer__sections">
        <section class="request-detail-drawer__section">
          <h3>{{ locale.t("timeline") }}</h3>
          <ol class="timeline-list">
            <li
              v-for="(item, index) in timeline"
              :key="`${index}-${item.timestamp}-${item.event}`"
              class="timeline-list__item"
            >
              <div class="timeline-list__meta">
                <span>{{ formatDateTime(item.timestamp) }}</span>
                <StatusBadge :tone="timelineTone(item)" :label="eventTypeLabel(item.event_type)" />
              </div>
              <strong>{{ eventLabel(item.event || item.span_name, locale.t("unknown_event"), locale.mode.value) }}</strong>
              <p>
                {{ item.summary || item.path || locale.t("no_extra_summary") }}
              </p>
              <div class="timeline-list__facts">
                <span>{{ item.status_code ?? "--" }}</span>
                <span>{{ formatLatency(item.duration_ms) }}</span>
                <span>{{ item.error_type || locale.t("request_status_ok") }}</span>
              </div>
            </li>
          </ol>
        </section>

        <section class="request-detail-drawer__section">
          <h3>{{ locale.t("stage") }}</h3>
          <ul class="stage-list">
            <li v-for="(stage, index) in stages" :key="`${index}-${stage.stage}-${stage.timestamp}`">
              <span>{{ stageLabel(stage.stage, locale.mode.value) }} <small>{{ stage.stage }}</small></span>
              <span>{{ formatLatency(stage.self_duration_ms ?? stage.duration_ms) }}</span>
            </li>
          </ul>
        </section>

        <section class="request-detail-drawer__section">
          <h3>{{ locale.t("errors") }}</h3>
          <ul v-if="errors.length" class="error-list">
            <li
              v-for="(item, index) in errors"
              :key="`${index}-${item.timestamp}-${item.event}-${item.error_type}`"
            >
              <strong>{{ item.error_type || eventLabel(item.event, locale.t("error_generic"), locale.mode.value) }}</strong>
              <p>{{ item.message || item.detail || locale.t("no_extra_error") }}</p>
            </li>
          </ul>
          <p v-else class="request-detail-drawer__empty-text">{{ locale.t("no_error_events") }}</p>
        </section>
      </div>
    </aside>
  </Transition>
</template>

<style scoped>
.request-detail-drawer {
  position: fixed;
  top: 0.85rem;
  right: 0.85rem;
  bottom: 0.85rem;
  z-index: 32;
  width: min(32.5rem, calc(100vw - 1.7rem));
  display: grid;
  grid-template-rows: auto auto auto minmax(0, 1fr);
  gap: 0.95rem;
  padding: 1rem;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-panel);
  background:
    linear-gradient(180deg, rgba(14, 22, 39, 0.98), rgba(9, 15, 28, 0.99)),
    var(--color-surface-raised);
  box-shadow: 0 26px 65px rgba(2, 8, 23, 0.45);
  overflow: hidden;
}

.request-detail-drawer__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.request-detail-drawer__header p {
  margin: 0;
  color: var(--color-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 0.75rem;
}

.request-detail-drawer__header h2 {
  margin: 0.35rem 0 0;
  font-size: 1.05rem;
  font-family: var(--font-mono);
}

.request-detail-drawer__header button {
  min-height: 2.2rem;
  padding: 0 0.85rem;
  border: 1px solid var(--color-border-strong);
  border-radius: 999px;
  background: transparent;
  cursor: pointer;
}

.request-detail-drawer__summary {
  padding: 0.9rem;
  border-radius: calc(var(--radius-card) - 0.2rem);
  border: 1px solid var(--color-border-strong);
  background: color-mix(in srgb, var(--color-brand-soft) 80%, transparent 20%);
}

.request-detail-drawer__summary-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.8rem;
}

.request-detail-drawer__summary-row strong {
  font-size: 0.98rem;
}

.request-detail-drawer__summary dl {
  margin: 0.72rem 0 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.65rem;
}

.request-detail-drawer__summary dt {
  margin: 0 0 0.22rem;
  color: var(--color-text-tertiary);
  font-size: 0.74rem;
}

.request-detail-drawer__summary dd {
  margin: 0;
  color: var(--color-text-primary);
  font-size: 0.84rem;
}

.request-detail-drawer__error {
  margin: 0;
  padding: 0.72rem 0.8rem;
  border-radius: calc(var(--radius-card) - 0.25rem);
  border: 1px solid color-mix(in srgb, var(--color-semantic-danger-strong) 30%, var(--color-border-subtle) 70%);
  color: var(--color-semantic-danger-strong);
  background: var(--color-semantic-danger-soft);
}

.request-detail-drawer__loading {
  padding: 0.8rem 0.9rem;
  border: 1px dashed var(--color-border-strong);
  border-radius: calc(var(--radius-card) - 0.2rem);
  color: var(--color-text-secondary);
}

.request-detail-drawer__sections {
  min-height: 0;
  overflow: auto;
  display: grid;
  gap: 0.9rem;
  padding-right: 0.25rem;
}

.request-detail-drawer__section {
  padding: 0.9rem;
  border-radius: calc(var(--radius-card) - 0.2rem);
  border: 1px solid var(--color-border-strong);
  background: rgba(255, 255, 255, 0.03);
}

.request-detail-drawer__section h3 {
  margin: 0 0 0.6rem;
  font-size: 0.92rem;
}

.timeline-list {
  display: grid;
  gap: 0.68rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.timeline-list__item {
  display: grid;
  gap: 0.35rem;
  padding: 0.68rem 0.72rem;
  border: 1px solid var(--color-border-strong);
  border-radius: calc(var(--radius-card) - 0.35rem);
  background: rgba(255, 255, 255, 0.04);
}

.timeline-list__meta,
.timeline-list__facts {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
  font-size: 0.8rem;
  color: var(--color-text-secondary);
}

.timeline-list__item p {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 0.82rem;
}

.stage-list,
.error-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 0.55rem;
}

.stage-list li {
  display: flex;
  justify-content: space-between;
  gap: 0.8rem;
  padding: 0.45rem 0.55rem;
  border-radius: 0.55rem;
  background: var(--color-surface-pill);
  font-size: 0.83rem;
}

.stage-list small {
  margin-left: 0.45rem;
  color: var(--color-text-tertiary);
  font-family: var(--font-mono);
  font-size: 0.73rem;
}

.error-list li {
  padding: 0.55rem 0.62rem;
  border-radius: 0.55rem;
  border: 1px solid color-mix(in srgb, var(--color-semantic-danger-strong) 20%, var(--color-border-subtle) 80%);
  background: color-mix(in srgb, var(--color-semantic-danger-soft) 62%, white 38%);
}

.error-list p {
  margin: 0.25rem 0 0;
  color: var(--color-text-secondary);
  font-size: 0.82rem;
}

.request-detail-drawer__empty-text {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 0.84rem;
}

.detail-drawer-enter-active,
.detail-drawer-leave-active {
  transition:
    transform 220ms ease,
    opacity 220ms ease;
}

.detail-drawer-enter-from,
.detail-drawer-leave-to {
  transform: translateX(22px);
  opacity: 0;
}

@media (max-width: 880px) {
  .request-detail-drawer {
    top: auto;
    left: 0.55rem;
    right: 0.55rem;
    bottom: 0.55rem;
    width: auto;
    max-height: min(85vh, 41rem);
  }
}
</style>
