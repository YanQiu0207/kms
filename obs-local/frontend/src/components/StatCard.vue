<script setup lang="ts">
defineProps<{
  eyebrow: string;
  value: string;
  hint: string;
  emphasis?: "brand" | "danger" | "warning" | "neutral";
}>();
</script>

<template>
  <article class="stat-card" :data-emphasis="emphasis ?? 'neutral'">
    <p class="stat-card__eyebrow">{{ eyebrow }}</p>
    <strong class="stat-card__value">{{ value }}</strong>
    <p class="stat-card__hint">{{ hint }}</p>
  </article>
</template>

<style scoped>
.stat-card {
  position: relative;
  display: grid;
  gap: 0.5rem;
  min-height: 9.75rem;
  padding: 1.3rem 1.35rem 1.25rem;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-panel);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.03) 0%, transparent 100%),
    linear-gradient(180deg, rgba(18, 28, 49, 0.92), rgba(10, 16, 31, 0.96));
  box-shadow: var(--shadow-panel);
  overflow: hidden;
}

.stat-card::after {
  content: "";
  position: absolute;
  inset: auto -1.5rem -2.5rem auto;
  width: 7.5rem;
  height: 7.5rem;
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-brand) 36%, transparent 64%);
  opacity: 0.9;
  filter: blur(10px);
}

.stat-card[data-emphasis="danger"]::after {
  background: color-mix(in srgb, var(--color-semantic-danger-strong) 26%, transparent 74%);
}

.stat-card[data-emphasis="warning"]::after {
  background: color-mix(in srgb, var(--color-semantic-warning-strong) 26%, transparent 74%);
}

.stat-card[data-emphasis="brand"]::after {
  background: color-mix(in srgb, var(--color-brand) 34%, transparent 66%);
}

.stat-card__eyebrow {
  margin: 0;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--color-text-tertiary);
}

.stat-card__value {
  position: relative;
  z-index: 1;
  font-family: var(--font-display);
  font-size: clamp(2rem, 3vw, 2.85rem);
  line-height: 1;
  color: var(--color-text-primary);
}

.stat-card__hint {
  position: relative;
  z-index: 1;
  margin: 0;
  font-size: 0.92rem;
  line-height: 1.55;
  color: var(--color-text-secondary);
}
</style>
