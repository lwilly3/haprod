<script setup lang="ts">
import { toastState } from "../lib/toast";
</script>

<template>
  <div v-if="toastState.visible" class="toast" :class="{ err: toastState.error }">{{ toastState.message }}</div>
</template>

<style scoped>
.toast {
  position: fixed; left: 50%; bottom: 28px; transform: translateX(-50%); z-index: 50;
  background: #18191B; color: #fff; font: 13.5px 'IBM Plex Sans', system-ui, sans-serif;
  padding: 10px 16px; border-radius: 4px; box-shadow: 0 8px 24px rgba(0, 0, 0, .18); max-width: 80vw;
}
.toast.err { background: #B8333A; }
</style>
