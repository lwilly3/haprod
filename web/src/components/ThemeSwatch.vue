<script setup lang="ts">
/** L'aperçu d'un design system : « Aa » sur le fond des cartes, dans la couleur du texte, et une pastille d'accent. */
defineProps<{ theme: Record<string, string | number> }>();
</script>

<template>
  <span class="swatch" :style="{
    background: String(theme.card), borderColor: String(theme.line), color: String(theme.text),
    borderRadius: theme.radius === undefined ? undefined : `${Math.min(Number(theme.radius), 12)}px`,
  }">
    Aa<i :style="{ background: String(theme.accent) }" />
  </span>
</template>

<style scoped>
.swatch { position: relative; display: grid; place-items: center; flex: none; width: 44px; height: 30px; border: 1px solid; font-size: 13px; font-weight: 600; }
.swatch i { position: absolute; right: 4px; bottom: 4px; width: 8px; height: 8px; border-radius: 50%; }
</style>
