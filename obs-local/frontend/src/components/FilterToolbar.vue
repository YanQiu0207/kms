<script setup lang="ts">
import { computed } from "vue";

import { useUiLocaleStore } from "@/stores/ui-locale";

defineEmits<{
  clear: [];
}>();

const props = defineProps<{
  activeCount: number;
}>();

const locale = useUiLocaleStore();

const summaryText = computed(() => {
  if (props.activeCount > 0) {
    return locale.pair(`${props.activeCount} 个条件`, `${props.activeCount} filters`);
  }
  return locale.t("all_data");
});
</script>

<template>
  <div class="filter-toolbar">
    <div class="filter-toolbar__summary">
      <span class="filter-toolbar__eyebrow">{{ locale.t("filter") }}</span>
      <strong>{{ summaryText }}</strong>
    </div>
    <div class="filter-toolbar__controls">
      <slot />
    </div>
    <button
      v-if="activeCount > 0"
      type="button"
      class="filter-toolbar__clear"
      @click="$emit('clear')"
    >
      {{ locale.t("clear") }}
    </button>
  </div>
</template>

<style scoped>
.filter-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.filter-toolbar__summary {
  display: grid;
  gap: 0.08rem;
  min-width: 6.5rem;
}

.filter-toolbar__eyebrow {
  color: var(--color-text-tertiary);
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.filter-toolbar__summary strong {
  color: var(--color-text-primary);
  font-size: 0.84rem;
}

.filter-toolbar__controls {
  display: flex;
  align-items: flex-end;
  justify-content: flex-end;
  gap: 0.65rem;
  flex-wrap: wrap;
}

.filter-toolbar__controls :deep(label) {
  display: grid;
  gap: 0.28rem;
  min-width: 7.4rem;
}

.filter-toolbar__controls :deep(label > span) {
  color: var(--color-text-tertiary);
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.filter-toolbar__controls :deep(input),
.filter-toolbar__controls :deep(select) {
  min-height: 2.35rem;
  padding: 0 0.78rem;
  border: 1px solid var(--color-border-strong);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.04);
  color: var(--color-text-primary);
  font: inherit;
}

.filter-toolbar__clear {
  min-height: 2.35rem;
  padding: 0 0.9rem;
  border: 1px solid color-mix(in srgb, var(--color-brand) 58%, var(--color-border-subtle) 42%);
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-brand-soft) 88%, transparent 12%);
  color: var(--color-brand-strong);
  font: inherit;
  cursor: pointer;
}

@media (max-width: 1180px) {
  .filter-toolbar {
    justify-content: flex-start;
  }
}
</style>
