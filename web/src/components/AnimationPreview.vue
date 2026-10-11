<script setup lang="ts">
/**
 * Une animation type (composition HyperFrames) réduite à la largeur de son cadre. Au repos elle
 * est figée sur son moment fort ; au survol, on rejoue sa timeline GSAP en boucle. La page est
 * servie par notre API, donc de même origine : on peut piloter sa fenêtre.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

interface Timeline { seek(t: number, suppressEvents?: boolean): unknown; duration(): number }
type HfWindow = Window & { __timelines?: Record<string, Timeline> };

const props = defineProps<{ src: string; id: string; format: "youtube" | "short"; hero: number | null; playing: boolean }>();

const size = computed(() => (props.format === "short" ? [1080, 1920] : [1920, 1080]));
const box = ref<HTMLDivElement>();
const frame = ref<HTMLIFrameElement>();
const scale = ref(0.2);
let timeline: Timeline | null = null;
let raf = 0;
let started = 0;

const observer = new ResizeObserver(([entry]) => (scale.value = entry.contentRect.width / size.value[0]));
onMounted(() => box.value && observer.observe(box.value));
onBeforeUnmount(() => {
  observer.disconnect();
  cancelAnimationFrame(raf);
});

function rest() {
  cancelAnimationFrame(raf);
  // sans moment fort déclaré : aux deux tiers, quand les entrées sont passées
  timeline?.seek(props.hero ?? (timeline.duration() || 0) * 0.66, false);
}

function tick(now: number) {
  if (!timeline) return;
  const d = timeline.duration() || 1;
  // seek avec les événements : les compteurs (onUpdate) se mettent à jour
  timeline.seek(((now - started) / 1000) % d, false);
  raf = requestAnimationFrame(tick);
}

function play() {
  cancelAnimationFrame(raf);
  started = performance.now();
  raf = requestAnimationFrame(tick);
}

function onLoad() {
  timeline = (frame.value?.contentWindow as HfWindow | null)?.__timelines?.[props.id] ?? null;
  if (props.playing) play();
  else rest();
}

watch(() => props.playing, (on) => (on ? play() : rest()));
</script>

<template>
  <div ref="box" class="anim" :style="{ aspectRatio: `${size[0]} / ${size[1]}` }">
    <iframe
      ref="frame" :src="src" :width="size[0]" :height="size[1]" :style="{ transform: `scale(${scale})` }"
      tabindex="-1" loading="lazy" @load="onLoad"
    />
  </div>
</template>

<style scoped>
/* les animations sont des surcouches transparentes : un fond neutre tient lieu de vidéo */
.anim { position: relative; overflow: hidden; background: linear-gradient(135deg, #9a9d9f, #55595d); }
iframe { position: absolute; top: 0; left: 0; border: 0; transform-origin: 0 0; pointer-events: none; color-scheme: normal; }
</style>
