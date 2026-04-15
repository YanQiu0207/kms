<script setup lang="ts">
import EmptyState from "@/components/EmptyState.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import { useUiLocaleStore } from "@/stores/ui-locale";
import type { ErrorSummary } from "@/types/observability";
import { formatDateTime, truncateText } from "@/utils/format";
import { eventLabel } from "@/utils/labels";

defineProps<{
  items: readonly ErrorSummary[];
  emptyTitle?: string;
  emptyDescription?: string;
}>();

const locale = useUiLocaleStore();
</script>

<template>
  <EmptyState
    v-if="items.length === 0"
    :title="emptyTitle ?? locale.t('no_errors_label')"
    :description="emptyDescription ?? locale.t('no_errors_desc')"
  />
  <div v-else class="error-list">
    <article v-for="item in items" :key="`${item.project_id}-${item.timestamp}-${item.event}-${item.request_id}`" class="error-row">
      <div class="error-row__meta">
        <p>{{ formatDateTime(item.timestamp) }}</p>
        <StatusBadge tone="danger" :label="item.error_type || item.level || locale.t('error_generic')" />
      </div>
      <strong>{{ eventLabel(item.event, locale.t("unknown_error"), locale.mode.value) }}</strong>
      <p>{{ item.path || locale.t("unbound_path") }}</p>
      <span>{{ truncateText(item.message || item.detail || item.request_id || locale.t("no_extra_info"), 88) }}</span>
    </article>
  </div>
</template>

<style scoped>
.error-list {
  display: grid;
  gap: 0.85rem;
}

.error-row {
  display: grid;
  gap: 0.42rem;
  padding: 0.95rem 1rem;
  border: 1px solid color-mix(in srgb, var(--color-semantic-danger-strong) 20%, var(--color-border-subtle) 80%);
  border-radius: calc(var(--radius-panel) - 0.35rem);
  background:
    linear-gradient(180deg, rgba(43, 23, 31, 0.88), rgba(26, 14, 21, 0.96)),
    var(--color-surface-panel);
}

.error-row__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.8rem;
}

.error-row__meta p,
.error-row span,
.error-row > p {
  margin: 0;
  color: var(--color-text-secondary);
}

.error-row strong {
  color: var(--color-text-primary);
}
</style>
