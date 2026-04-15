<script setup lang="ts">
import EmptyState from "@/components/EmptyState.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import { useUiLocaleStore } from "@/stores/ui-locale";
import type { StageStats } from "@/types/observability";
import { formatLatency } from "@/utils/format";
import { stageLabel } from "@/utils/labels";

defineProps<{
  items: readonly StageStats[];
  emptyTitle?: string;
  emptyDescription?: string;
}>();

const locale = useUiLocaleStore();

function confidenceTone(confidence: StageStats["p95_confidence"]): "neutral" | "warning" | "info" {
  if (confidence === "high") {
    return "info";
  }
  if (confidence === "medium") {
    return "warning";
  }
  return "neutral";
}

function confidenceLabel(confidence: StageStats["p95_confidence"]): string {
  if (confidence === "high") {
    return locale.t("confidence_high");
  }
  if (confidence === "medium") {
    return locale.t("confidence_medium");
  }
  return locale.t("confidence_low");
}
</script>

<template>
  <EmptyState
    v-if="items.length === 0"
    :title="emptyTitle ?? locale.t('stage_empty_title')"
    :description="emptyDescription ?? locale.t('stage_empty_desc')"
  />
  <div v-else class="stage-board">
    <article v-for="item in items" :key="`${item.project_id}-${item.stage}`" class="stage-row">
      <div class="stage-row__header">
        <div class="stage-row__title">
          <strong>{{ stageLabel(item.stage, locale.mode.value) }}</strong>
          <span>{{ item.stage }}</span>
        </div>
        <StatusBadge :tone="confidenceTone(item.p95_confidence)" :label="confidenceLabel(item.p95_confidence)" />
      </div>
      <div class="stage-row__bar">
        <div class="stage-row__fill" :style="{ width: `${Math.min(100, Math.max(12, item.p95_ms / 8))}%` }" />
      </div>
      <div class="stage-row__metrics">
        <span>P95 {{ formatLatency(item.p95_ms) }}</span>
        <span>{{ locale.t("mean") }} {{ formatLatency(item.avg_ms) }}</span>
        <span>{{ locale.pair(`${item.count} 个样本`, `${item.count} samples`) }}</span>
      </div>
    </article>
  </div>
</template>

<style scoped>
.stage-board {
  display: grid;
  gap: 0.95rem;
}

.stage-row {
  display: grid;
  gap: 0.65rem;
  padding: 0.95rem 1rem;
  border: 1px solid var(--color-border-strong);
  border-radius: calc(var(--radius-panel) - 0.35rem);
  background: linear-gradient(180deg, rgba(18, 28, 49, 0.92), rgba(11, 18, 33, 0.98));
}

.stage-row__header,
.stage-row__metrics {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.8rem;
}

.stage-row__header strong {
  color: var(--color-text-primary);
}

.stage-row__title {
  display: grid;
  gap: 0.15rem;
}

.stage-row__title span {
  color: var(--color-text-tertiary);
  font-family: var(--font-mono);
  font-size: 0.74rem;
}

.stage-row__bar {
  position: relative;
  height: 0.55rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}

.stage-row__fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--color-brand), var(--color-brand-strong));
}

.stage-row__metrics {
  font-family: var(--font-mono);
  font-size: 0.84rem;
  color: var(--color-text-secondary);
}
</style>
