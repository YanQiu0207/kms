<script setup lang="ts">
import { useUiLocaleStore } from "@/stores/ui-locale";

defineProps<{
  title: string;
  subtitle: string;
  eyebrow?: string;
  signature?: string;
  tags?: readonly string[];
  brandMark?: string;
}>();

const locale = useUiLocaleStore();
</script>

<template>
  <div class="app-shell">
    <header class="app-shell__hero">
      <div class="app-shell__hero-copy app-shell__hero-copy--centered">
        <div class="app-shell__brand-row">
          <div class="app-shell__brand-mark">
            <span>{{ brandMark ?? "SD" }}</span>
          </div>
          <div class="app-shell__brand-copy">
            <p class="app-shell__eyebrow">{{ eyebrow ?? locale.t("brand_eyebrow") }}</p>
            <p class="app-shell__signature">{{ signature ?? locale.pair("obs-local 运行控制台", "obs-local runtime console") }}</p>
          </div>
        </div>
        <div class="app-shell__title-wrap">
          <h1>{{ title }}</h1>
          <p>{{ subtitle }}</p>
        </div>
        <div v-if="tags?.length" class="app-shell__tag-row">
          <span v-for="tag in tags" :key="tag">{{ tag }}</span>
        </div>
      </div>
      <div class="app-shell__hero-side">
        <slot name="hero-side" />
      </div>
    </header>

    <div class="app-shell__layout">
      <aside class="app-shell__sidebar">
        <slot name="sidebar" />
      </aside>
      <main class="app-shell__content">
        <slot />
      </main>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  max-width: min(1480px, calc(100vw - 3rem));
  margin: 0 auto;
  padding: 2rem 0 2.75rem;
}

.app-shell__hero {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(21rem, 0.75fr);
  gap: 1.5rem;
  align-items: stretch;
  margin-bottom: 1.5rem;
}

.app-shell__hero-copy,
.app-shell__hero-side {
  position: relative;
  padding: 1.55rem 1.65rem;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-hero);
  background:
    radial-gradient(circle at top right, rgba(76, 201, 215, 0.18), transparent 28%),
    radial-gradient(circle at bottom left, rgba(96, 165, 250, 0.14), transparent 34%),
    linear-gradient(180deg, rgba(14, 22, 39, 0.94), rgba(9, 15, 28, 0.96));
  box-shadow: var(--shadow-panel);
  overflow: hidden;
}

.app-shell__hero-copy--centered {
  display: grid;
  align-content: center;
  justify-items: center;
  text-align: center;
}

.app-shell__hero-copy::after,
.app-shell__hero-side::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  border: 1px solid rgba(255, 255, 255, 0.03);
  pointer-events: none;
}

.app-shell__brand-row {
  display: flex;
  align-items: center;
  gap: 1rem;
  justify-content: center;
  animation: shell-fade-up 520ms ease both;
}

.app-shell__brand-mark {
  display: grid;
  place-items: center;
  width: 3.5rem;
  height: 3.5rem;
  border: 1px solid rgba(122, 230, 242, 0.24);
  border-radius: 1.15rem;
  background:
    radial-gradient(circle at top, rgba(122, 230, 242, 0.34), transparent 58%),
    linear-gradient(180deg, rgba(19, 34, 61, 0.96), rgba(10, 19, 37, 0.96));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    0 16px 28px rgba(0, 0, 0, 0.28);
  animation: brand-breathe 4.6s ease-in-out infinite;
}

.app-shell__brand-mark span {
  font-family: var(--font-display);
  font-size: 1.18rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--color-brand-strong);
}

.app-shell__brand-copy {
  display: grid;
  gap: 0.18rem;
  justify-items: start;
  text-align: left;
}

.app-shell__eyebrow {
  margin: 0;
  color: var(--color-text-tertiary);
  font-size: 0.76rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.app-shell__signature {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 0.92rem;
}

.app-shell__title-wrap {
  margin-top: 1.25rem;
  display: grid;
  gap: 0.9rem;
  justify-items: center;
  animation: shell-fade-up 640ms ease 80ms both;
}

.app-shell__hero-copy h1 {
  margin: 0;
  font-family: var(--font-display);
  font-size: clamp(3rem, 6vw, 5.6rem);
  line-height: 0.92;
  letter-spacing: -0.04em;
  color: var(--color-text-primary);
}

.app-shell__title-wrap > p {
  margin: 0;
  max-width: 50rem;
  color: var(--color-text-secondary);
  font-size: 1.02rem;
  line-height: 1.75;
}

.app-shell__tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
  margin-top: 1.25rem;
  justify-content: center;
  animation: shell-fade-up 760ms ease 160ms both;
}

.app-shell__tag-row span {
  display: inline-flex;
  align-items: center;
  min-height: 2rem;
  padding: 0 0.8rem;
  border: 1px solid rgba(122, 230, 242, 0.14);
  border-radius: 999px;
  background: rgba(122, 230, 242, 0.08);
  color: var(--color-text-secondary);
  font-size: 0.78rem;
  letter-spacing: 0.03em;
  animation: tag-float 5.4s ease-in-out infinite;
}

.app-shell__tag-row span:nth-child(2) {
  animation-delay: 0.6s;
}

.app-shell__tag-row span:nth-child(3) {
  animation-delay: 1.2s;
}

.app-shell__tag-row span:nth-child(4) {
  animation-delay: 1.8s;
}

.app-shell__layout {
  display: grid;
  grid-template-columns: minmax(17rem, 21rem) minmax(0, 1fr);
  gap: 1.25rem;
  align-items: start;
}

.app-shell__sidebar,
.app-shell__content {
  min-width: 0;
}

@keyframes shell-fade-up {
  from {
    opacity: 0;
    transform: translateY(18px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes brand-breathe {
  0%,
  100% {
    transform: translateY(0) scale(1);
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.08),
      0 16px 28px rgba(0, 0, 0, 0.28);
  }

  50% {
    transform: translateY(-2px) scale(1.02);
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.08),
      0 18px 34px rgba(0, 0, 0, 0.34),
      0 0 0 1px rgba(122, 230, 242, 0.18);
  }
}

@keyframes tag-float {
  0%,
  100% {
    transform: translateY(0);
  }

  50% {
    transform: translateY(-3px);
  }
}

@media (max-width: 1080px) {
  .app-shell {
    max-width: calc(100vw - 1.5rem);
    padding-top: 1rem;
  }

  .app-shell__hero,
  .app-shell__layout {
    grid-template-columns: 1fr;
  }
}
</style>
