<script setup lang="ts">
import EmptyState from "@/components/EmptyState.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import { useUiLocaleStore } from "@/stores/ui-locale";
import type { RequestSummary } from "@/types/observability";
import { formatDateTime, formatLatency, truncateText } from "@/utils/format";
import { routeLabel, stageLabel } from "@/utils/labels";

defineProps<{
  items: readonly RequestSummary[];
  selectedRequestId: string | null;
  emptyTitle?: string;
  emptyDescription?: string;
}>();

const emit = defineEmits<{
  select: [requestId: string];
}>();

const locale = useUiLocaleStore();

function statusTone(status: RequestSummary["status"]): "success" | "warning" | "danger" {
  if (status === "ok") {
    return "success";
  }
  if (status === "partial") {
    return "warning";
  }
  return "danger";
}

function statusLabel(status: RequestSummary["status"]): string {
  if (status === "ok") {
    return locale.t("request_status_ok");
  }
  if (status === "partial") {
    return locale.t("request_status_partial");
  }
  return locale.t("request_status_failed");
}
</script>

<template>
  <EmptyState
    v-if="items.length === 0"
    :title="emptyTitle ?? locale.t('no_requests_title')"
    :description="emptyDescription ?? locale.t('no_requests_desc')"
  />
  <div v-else class="request-list">
    <article
      v-for="item in items"
      :key="item.request_id"
      class="request-row"
      :class="{ 'request-row--active': selectedRequestId === item.request_id }"
      role="button"
      tabindex="0"
      @click="emit('select', item.request_id)"
      @keyup.enter="emit('select', item.request_id)"
      @keyup.space.prevent="emit('select', item.request_id)"
    >
      <div class="request-row__meta">
        <p>{{ formatDateTime(item.last_event_at || item.started_at) }}</p>
        <StatusBadge :tone="statusTone(item.status)" :label="statusLabel(item.status)" />
      </div>
      <div class="request-row__main">
        <div>
          <strong>{{ routeLabel(item.path, item.request_type, locale.mode.value) }}</strong>
          <p>
            {{ `${item.method || "?"} ${item.path || item.request_type || locale.t("unknown_route")}` }}
            <template v-if="item.summary"> · {{ truncateText(item.summary, 64) }}</template>
          </p>
        </div>
        <div class="request-row__metrics">
          <span class="request-row__metric">{{ item.status_code ?? "--" }}</span>
          <span class="request-row__metric">{{ formatLatency(item.duration_ms) }}</span>
        </div>
      </div>
      <div class="request-row__foot">
        <span>{{ locale.t("request_id") }} {{ item.request_id }}</span>
      </div>
      <ul class="request-row__stages">
        <li v-for="stage in item.top_stages.slice(0, 3)" :key="`${item.request_id}-${stage.stage}`">
          {{ stageLabel(stage.stage, locale.mode.value) }} · {{ formatLatency(stage.self_duration_ms ?? stage.duration_ms) }}
        </li>
      </ul>
    </article>
  </div>
</template>

<style scoped>
.request-list {
  display: grid;
  gap: 0.9rem;
}

.request-row {
  display: grid;
  gap: 0.75rem;
  padding: 0.95rem 1rem;
  border: 1px solid var(--color-border-strong);
  border-radius: calc(var(--radius-panel) - 0.35rem);
  background: linear-gradient(180deg, rgba(19, 31, 56, 0.92), rgba(11, 18, 33, 0.98));
  cursor: pointer;
  transition:
    border-color 140ms ease,
    transform 140ms ease,
    box-shadow 140ms ease;
}

.request-row:hover {
  border-color: color-mix(in srgb, var(--color-brand) 62%, var(--color-border-subtle) 38%);
  transform: translateY(-2px);
  box-shadow: var(--shadow-soft);
}

.request-row--active {
  border-color: color-mix(in srgb, var(--color-brand-strong) 72%, var(--color-border-strong) 28%);
  background:
    linear-gradient(132deg, rgba(76, 201, 215, 0.16), transparent 68%),
    linear-gradient(180deg, rgba(18, 31, 55, 0.98), rgba(11, 18, 33, 0.98));
}

.request-row__meta,
.request-row__main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.request-row__meta p {
  margin: 0;
  font-size: 0.84rem;
  color: var(--color-text-secondary);
}

.request-row__main strong {
  display: block;
  color: var(--color-text-primary);
}

.request-row__main p {
  margin: 0.26rem 0 0;
  color: var(--color-text-secondary);
}

.request-row__metrics {
  display: flex;
  align-items: center;
  gap: 0.8rem;
}

.request-row__foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
}

.request-row__foot span {
  color: var(--color-text-tertiary);
  font-family: var(--font-mono);
  font-size: 0.75rem;
}

.request-row__metric {
  min-width: 5.8rem;
  text-align: right;
  font-family: var(--font-mono);
  font-size: 0.92rem;
  color: var(--color-text-primary);
}

.request-row__stages {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.request-row__stages li {
  padding: 0.35rem 0.65rem;
  border-radius: 999px;
  background: var(--color-surface-pill);
  color: var(--color-text-secondary);
  font-size: 0.8rem;
}
</style>
