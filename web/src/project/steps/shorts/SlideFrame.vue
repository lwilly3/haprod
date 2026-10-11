<script setup lang="ts">
/**
 * Une composition HyperFrames dans une iframe, figée à l'instant `local` (secondes depuis
 * le début de la slide) : on pilote directement sa timeline GSAP, comme le fera le rendu.
 * La page est servie par notre API, donc de même origine : on peut lire sa fenêtre.
 */
import { ref, watch } from "vue";
import { SIZES, type Slide } from "./types";

interface Timeline { seek(t: number, suppressEvents?: boolean): unknown; duration(): number }
type HfWindow = Window & { __timelines?: Record<string, Timeline> };

const props = defineProps<{ slide: Slide; local: number; format: keyof typeof SIZES; scale: number; visible: boolean }>();

const frame = ref<HTMLIFrameElement>();
let timeline: Timeline | null = null;

function seek() {
  // seek avec les événements : les compteurs (onUpdate) se mettent à jour
  timeline?.seek(Math.max(0, Math.min(props.local, props.slide.end - props.slide.start)), false);
}

function onLoad() {
  const win = frame.value?.contentWindow as HfWindow | null;
  timeline = win?.__timelines?.[props.slide.id] ?? null;
  seek();
}

watch(() => props.local, seek);
watch(() => props.slide.url, () => { timeline = null; });
</script>

<template>
  <iframe
    v-if="slide.url" ref="frame" :src="slide.url" class="slide-frame" :class="{ hidden: !visible }"
    :width="SIZES[format][0]" :height="SIZES[format][1]" :style="{ transform: `scale(${scale})` }"
    tabindex="-1" @load="onLoad"
  />
</template>

<style scoped>
.slide-frame {
  position: absolute; top: 0; left: 0; border: 0; transform-origin: 0 0;
  background: transparent; pointer-events: none; color-scheme: normal;
}
.slide-frame.hidden { visibility: hidden; }
</style>
