<script setup lang="ts">
defineProps<{
  title: string;
  subtitle: string;
}>();
</script>

<template>
  <section class="section-card">
    <header class="section-card__header">
      <div>
        <h2>{{ title }}</h2>
        <p>{{ subtitle }}</p>
      </div>
      <slot name="header" />
    </header>
    <div class="section-card__body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.section-card {
  padding: 1.25rem;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-panel);
  background:
    linear-gradient(180deg, rgba(17, 26, 46, 0.94), rgba(10, 16, 31, 0.96)),
    var(--color-surface-panel);
  box-shadow: var(--shadow-panel);
  backdrop-filter: blur(18px);
}

.section-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.section-card__header h2 {
  margin: 0;
  font-size: 1.02rem;
  letter-spacing: 0.01em;
  color: var(--color-text-primary);
}

.section-card__header p {
  margin: 0.3rem 0 0;
  color: var(--color-text-secondary);
  font-size: 0.9rem;
}

.section-card__body {
  min-height: 2rem;
}
</style>
