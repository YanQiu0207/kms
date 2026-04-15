<script setup lang="ts">
import { onMounted, onUnmounted } from "vue";
import { RouterView } from "vue-router";

import { useObservabilityStore } from "@/stores/observability";
import { useUiLocaleStore } from "@/stores/ui-locale";

const store = useObservabilityStore();
const uiLocale = useUiLocaleStore();

onMounted(() => {
  void uiLocale.start();
  void store.start();
});

onUnmounted(() => {
  store.stop();
});
</script>

<template>
  <RouterView />
</template>
