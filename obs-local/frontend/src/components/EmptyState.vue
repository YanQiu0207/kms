<script setup lang="ts">
defineProps<{
  title: string;
  description: string;
}>();
</script>

<template>
  <div class="empty-state">
    <p class="empty-state__title">{{ title }}</p>
    <p class="empty-state__description">{{ description }}</p>
  </div>
</template>

<style scoped>
.empty-state {
  display: grid;
  place-items: center;
  gap: 0.4rem;
  min-height: 11rem;
  border: 1px dashed var(--color-border-strong);
  border-radius: calc(var(--radius-panel) - 0.3rem);
  background:
    radial-gradient(circle at top, rgba(76, 201, 215, 0.08), transparent 44%),
    linear-gradient(180deg, rgba(16, 26, 46, 0.9), rgba(10, 16, 31, 0.96));
  text-align: center;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
}

.empty-state__title {
  margin: 0;
  font-size: 1rem;
  font-weight: 700;
  color: var(--color-text-primary);
}

.empty-state__description {
  margin: 0;
  max-width: 24rem;
  color: var(--color-text-secondary);
  line-height: 1.6;
}
</style>
