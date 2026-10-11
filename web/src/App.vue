<script setup lang="ts">
import { useRoute } from "vue-router";
import ToastHost from "./components/ToastHost.vue";
import TopBar from "./project/TopBar.vue";

const route = useRoute();
</script>

<template>
  <RouterView v-if="route.meta.bare" :key="route.fullPath" />
  <div v-else class="app shell">
    <TopBar />
    <main>
      <RouterView :key="route.name === 'step' ? 'step' : route.fullPath" />
    </main>
  </div>
  <ToastHost />
</template>

<style scoped>
.shell { height: 100vh; min-width: 1200px; display: flex; flex-direction: column; background: #fff; }
main { flex: 1; min-height: 0; display: flex; flex-direction: column; }
</style>
