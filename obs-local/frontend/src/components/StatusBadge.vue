<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  tone: "neutral" | "success" | "warning" | "danger" | "info";
  label: string;
  hint?: string;
}>();

const badgeClass = computed(() => `status-badge status-badge--${props.tone}`);
</script>

<template>
  <span :class="badgeClass" :title="hint">
    <span>{{ label }}</span>
    <span v-if="hint" class="status-badge__tooltip" role="tooltip">{{ hint }}</span>
  </span>
</template>

<style scoped>
.status-badge {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  min-height: 1.75rem;
  padding: 0.2rem 0.72rem;
  border: 1px solid var(--color-border-strong);
  border-radius: 999px;
  font-size: 0.76rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  white-space: nowrap;
  cursor: default;
}

.status-badge--neutral {
  color: var(--color-text-secondary);
  background: color-mix(in srgb, var(--color-surface-raised) 92%, white 8%);
}

.status-badge--success {
  color: var(--color-semantic-success-strong);
  background: var(--color-semantic-success-soft);
}

.status-badge--warning {
  color: var(--color-semantic-warning-strong);
  background: var(--color-semantic-warning-soft);
}

.status-badge--danger {
  color: var(--color-semantic-danger-strong);
  background: var(--color-semantic-danger-soft);
}

.status-badge--info {
  color: var(--color-brand-strong);
  background: var(--color-brand-soft);
}

.status-badge__tooltip {
  position: absolute;
  left: 50%;
  bottom: calc(100% + 0.65rem);
  z-index: 12;
  width: max-content;
  max-width: min(22rem, 60vw);
  padding: 0.7rem 0.85rem;
  border: 1px solid color-mix(in srgb, var(--color-border-strong) 80%, transparent 20%);
  border-radius: 0.9rem;
  background: rgba(33, 31, 26, 0.94);
  box-shadow: 0 16px 36px rgba(22, 18, 13, 0.22);
  color: #fffaf1;
  font-size: 0.77rem;
  font-weight: 500;
  letter-spacing: 0.01em;
  line-height: 1.5;
  text-transform: none;
  white-space: normal;
  opacity: 0;
  pointer-events: none;
  transform: translate(-50%, 0.35rem);
  transition:
    opacity 140ms ease,
    transform 140ms ease;
}

.status-badge__tooltip::after {
  content: "";
  position: absolute;
  left: 50%;
  top: 100%;
  width: 0.8rem;
  height: 0.8rem;
  border-right: 1px solid color-mix(in srgb, var(--color-border-strong) 80%, transparent 20%);
  border-bottom: 1px solid color-mix(in srgb, var(--color-border-strong) 80%, transparent 20%);
  background: rgba(33, 31, 26, 0.94);
  transform: translate(-50%, -50%) rotate(45deg);
}

.status-badge:hover .status-badge__tooltip,
.status-badge:focus-visible .status-badge__tooltip {
  opacity: 1;
  transform: translate(-50%, 0);
}
</style>
