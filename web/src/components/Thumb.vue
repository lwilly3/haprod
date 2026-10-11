<script setup lang="ts">
/** Aperçu d'un fichier dans une liste : l'image, la première seconde d'une vidéo, sinon des hachures. */
import { computed, ref, watch } from "vue";

const props = defineProps<{ src: string; kind: string; name: string }>();

const broken = ref(false);
watch(() => props.src, () => (broken.value = false));

// le navigateur n'affiche pas les .psd
const image = computed(() => props.kind === "Images" && !/\.psd$/i.test(props.name));
</script>

<template>
  <img v-if="image && !broken" class="thumb" :src="src" alt="" loading="lazy" @error="broken = true">
  <video v-else-if="kind === 'Vidéo' && !broken" class="thumb" :src="`${src}#t=1`" preload="metadata" muted @error="broken = true" />
  <div v-else class="thumb hatch" />
</template>

<style scoped>
.thumb { height: 40px; width: 72px; object-fit: cover; display: block; background: var(--bg-soft); }
</style>
