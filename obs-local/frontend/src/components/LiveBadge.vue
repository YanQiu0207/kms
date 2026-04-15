<script setup lang="ts">
import { computed } from "vue";

import StatusBadge from "@/components/StatusBadge.vue";
import { useUiLocaleStore } from "@/stores/ui-locale";
import type { TransportState } from "@/types/observability";

const props = defineProps<{
  state: TransportState;
}>();

const locale = useUiLocaleStore();

const tone = computed(() => {
  if (props.state === "live") {
    return "success";
  }
  if (props.state === "paused") {
    return "neutral";
  }
  if (props.state === "reconnecting" || props.state === "connecting") {
    return "warning";
  }
  if (props.state === "error") {
    return "danger";
  }
  return "info";
});

const label = computed(() => {
  if (props.state === "live") {
    return locale.t("status_live");
  }
  if (props.state === "paused") {
    return locale.t("status_paused");
  }
  if (props.state === "reconnecting") {
    return locale.t("status_reconnecting");
  }
  if (props.state === "connecting") {
    return locale.t("status_connecting");
  }
  if (props.state === "error") {
    return locale.t("status_degraded");
  }
  return locale.t("status_idle");
});

const hint = computed(() => {
  if (props.state === "live") {
    return locale.pair(
      "实时流连接正常，页面正在接收 obs-local 的 SSE 更新。",
      "The live stream is healthy and the page is receiving SSE updates from obs-local.",
    );
  }
  if (props.state === "paused") {
    return locale.pair(
      "实时流已被手动暂停，页面只显示最后一次同步结果。",
      "Live updates are paused manually, so the page is showing the last synced snapshot.",
    );
  }
  if (props.state === "reconnecting") {
    return locale.pair(
      "实时流连接暂时中断，前端正在等待浏览器重新建立 SSE 连接。",
      "The live stream is temporarily interrupted while the browser re-establishes the SSE connection.",
    );
  }
  if (props.state === "connecting") {
    return locale.pair(
      "页面正在初始化实时流连接，马上会开始接收更新。",
      "The page is initializing the live stream and should start receiving updates shortly.",
    );
  }
  if (props.state === "error") {
    return locale.pair(
      "实时流当前不可用，界面可能只能显示快照数据。",
      "The live stream is unavailable, so the dashboard may only show snapshot data.",
    );
  }
  return locale.pair(
    "实时流尚未启动，页面还没有进入 live 模式。",
    "The live stream has not started yet, so the page is not in live mode.",
  );
});
</script>

<template>
  <StatusBadge :tone="tone" :label="label" :hint="hint" />
</template>
