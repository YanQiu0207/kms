<script setup lang="ts">
import StatusBadge from "@/components/StatusBadge.vue";
import { useUiLocaleStore } from "@/stores/ui-locale";
import type { ProjectInfo } from "@/types/observability";
import { formatRelativeTime } from "@/utils/format";

defineProps<{
  projects: readonly ProjectInfo[];
  selectedProjectId: string | null;
}>();

const emit = defineEmits<{
  select: [projectId: string | null];
}>();

const locale = useUiLocaleStore();

function stalenessTone(staleness: ProjectInfo["staleness"]): "success" | "warning" | "danger" | "neutral" {
  if (staleness === "live") {
    return "success";
  }
  if (staleness === "idle") {
    return "neutral";
  }
  if (staleness === "stale") {
    return "warning";
  }
  return "danger";
}

function stalenessLabel(staleness: ProjectInfo["staleness"]): string {
  if (staleness === "live") {
    return locale.t("staleness_fresh");
  }
  if (staleness === "idle") {
    return locale.t("staleness_idle");
  }
  if (staleness === "stale") {
    return locale.t("staleness_stale");
  }
  return locale.t("staleness_offline");
}
</script>

<template>
  <aside class="project-rail">
    <button
      class="project-rail__project"
      :class="{ 'project-rail__project--active': selectedProjectId === null }"
      type="button"
      @click="emit('select', null)"
    >
      <div>
        <strong>{{ locale.t("all_projects") }}</strong>
        <p>{{ locale.t("cross_project_overview") }}</p>
      </div>
      <StatusBadge tone="info" :label="locale.t('global_badge')" :hint="locale.t('global_badge_hint')" />
    </button>

    <button
      v-for="project in projects"
      :key="project.project_id"
      class="project-rail__project"
      :class="{ 'project-rail__project--active': selectedProjectId === project.project_id }"
      type="button"
      @click="emit('select', project.project_id)"
    >
      <div>
        <strong>{{ project.display_name || project.name }}</strong>
        <p>{{ formatRelativeTime(project.last_event_at) }}</p>
      </div>
      <StatusBadge
        :tone="stalenessTone(project.staleness)"
        :label="stalenessLabel(project.staleness)"
        :hint="locale.pair(
          '项目级新鲜度标签。新鲜表示最近仍有事件进入，陈旧表示事件已经明显变旧。',
          'Project freshness label. Fresh means new events are still arriving, while stale means they are noticeably old.'
        )"
      />
    </button>
  </aside>
</template>

<style scoped>
.project-rail {
  display: grid;
  gap: 0.85rem;
}

.project-rail__project {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem 1rem 1.05rem;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-card);
  background:
    linear-gradient(180deg, rgba(18, 28, 49, 0.9), rgba(11, 17, 31, 0.96)),
    var(--color-surface-panel);
  text-align: left;
  cursor: pointer;
  transition:
    transform 160ms ease,
    border-color 160ms ease,
    box-shadow 160ms ease;
}

.project-rail__project:hover {
  transform: translateY(-2px);
  border-color: color-mix(in srgb, var(--color-brand) 58%, var(--color-border-strong) 42%);
  box-shadow: var(--shadow-soft);
}

.project-rail__project--active {
  border-color: color-mix(in srgb, var(--color-brand) 72%, var(--color-border-strong) 28%);
  background:
    linear-gradient(135deg, rgba(76, 201, 215, 0.16), transparent 65%),
    linear-gradient(180deg, rgba(18, 31, 55, 0.98), rgba(10, 18, 33, 0.98));
}

.project-rail__project strong {
  display: block;
  margin-bottom: 0.18rem;
  font-size: 0.96rem;
  color: var(--color-text-primary);
}

.project-rail__project p {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 0.84rem;
}
</style>
