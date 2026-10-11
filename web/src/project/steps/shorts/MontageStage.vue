<script setup lang="ts">
/**
 * L'aperçu du montage : le short monté, les slides et les sous-titres par-dessus, au temps `t`
 * (secondes dans le short). En lecture, c'est la vidéo qui donne le temps.
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import SlideFrame from "./SlideFrame.vue";
import { SIZES, type Captions, type MediaPart, type Slide } from "./types";

const props = defineProps<{
  slides: Slide[]; selectedId: string | null; format: keyof typeof SIZES; media: MediaPart[];
  captions: Captions | null; busy: boolean; label?: string;
}>();
const t = defineModel<number>("t", { required: true });
const playing = defineModel<boolean>("playing", { required: true });
const { t: tr } = useI18n();

const stage = ref<HTMLElement>();
const video = ref<HTMLVideoElement>();
const width = ref(0);
const scale = computed(() => width.value / SIZES[props.format][0]);
const total = computed(() => props.media.reduce((n, p) => Math.max(n, p.start + p.duration), 0));

const part = computed(() => props.media.find((p) => t.value >= p.start && t.value < p.start + p.duration) ?? props.media[0]);
const inside = (s: Slide) => t.value >= s.start && t.value < s.end;
// la slide choisie reste chargée (pour être prête), les autres seulement quand elles jouent
const mounted = computed(() => props.slides.filter((s) => s.id === props.selectedId || (!s.discarded && inside(s))));
const selected = computed(() => props.slides.find((s) => s.id === props.selectedId));
// les sous-titres : une composition sur toute la vidéo, au-dessus des slides
const captionTrack = computed<Slide | null>(() => (props.captions ? {
  id: "captions", start: 0, end: total.value, title: "Sous-titres", kind: "", idea: "", why: "",
  discarded: false, url: props.captions.url,
} : null));

const observer = new ResizeObserver(([entry]) => { width.value = entry.contentRect.width; });
onMounted(() => stage.value && observer.observe(stage.value));
onUnmounted(() => observer.disconnect());

function syncVideo() {
  const v = video.value, p = part.value;
  if (!v || !p) return;
  const target = Math.max(0, t.value - p.start);
  if (Math.abs(v.currentTime - target) > 0.05) v.currentTime = target;
}

let raf = 0;
let last = 0;
function tick(now: number) {
  const v = video.value;
  if (v && part.value && !v.paused) t.value = part.value.start + v.currentTime;
  else if (!v || !part.value) t.value += (now - last) / 1000;
  last = now;
  if (total.value && t.value >= total.value) {
    playing.value = false;
    t.value = 0;
  } else raf = requestAnimationFrame(tick);
}

watch(playing, (on) => {
  cancelAnimationFrame(raf);
  const v = video.value;
  if (on) {
    syncVideo();
    v?.play().catch(() => {});
    last = performance.now();
    raf = requestAnimationFrame(tick);
  } else {
    v?.pause();
  }
});
// déplacement à la main (slide choisie, timeline) : la vidéo suit
watch(t, () => { if (!playing.value) syncVideo(); });
watch(() => part.value?.url, () => setTimeout(syncVideo));
onUnmounted(() => cancelAnimationFrame(raf));
</script>

<template>
  <div ref="stage" class="stage hatch-dark" :class="format">
    <video
      v-if="part" ref="video" :src="part.url" preload="auto" playsinline
      @loadedmetadata="syncVideo" @ended="playing = false" @click="playing = !playing"
    />
    <SlideFrame
      v-for="s in mounted" :key="s.id" :slide="s" :local="t - s.start" :format="format"
      :scale="scale" :visible="inside(s) && (!s.discarded || s.id === selectedId)"
    />
    <SlideFrame
      v-if="captionTrack" :key="captionTrack.url!" :slide="captionTrack" :local="t" :format="format"
      :scale="scale" :visible="true"
    />
    <span v-if="label" class="label mono">{{ label }}</span>
    <div v-if="selected && !selected.url && inside(selected)" class="pending">
      <span class="kind mono">{{ selected.kind || tr("shortEditing.slideKind") }}</span>
      <span class="what">{{ selected.title }}</span>
      <span class="state">{{ busy ? tr("shortEditing.stage.coding") : tr("shortEditing.stage.noComposition") }}</span>
    </div>
    <div class="pbar"><div :style="{ width: `${total ? (t / total) * 100 : 0}%` }" /></div>
  </div>
</template>

<style scoped>
.stage { position: relative; overflow: hidden; flex-shrink: 0; }
.stage.short { height: 440px; aspect-ratio: 9 / 16; }
.stage.youtube { width: 560px; max-width: 100%; aspect-ratio: 16 / 9; }
video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; cursor: pointer; }
.label { position: absolute; top: 10px; left: 10px; font-size: 10.5px; color: #9A9B97; pointer-events: none; }
.pending {
  position: absolute; left: 8%; right: 8%; top: 12%; display: flex; flex-direction: column; gap: 4px;
  background: rgba(24, 25, 27, .85); border: 1px dashed var(--faint); border-radius: 4px; padding: 12px 14px;
  pointer-events: none;
}
.pending .kind { font-size: 10.5px; text-transform: uppercase; letter-spacing: .06em; color: var(--red); }
.pending .what { font-size: 14px; font-weight: 600; color: #fff; }
.pending .state { font-size: 12px; color: var(--off); }
.pbar { position: absolute; left: 0; right: 0; bottom: 0; height: 3px; background: rgba(255, 255, 255, .2); pointer-events: none; }
.pbar > div { height: 3px; background: var(--red); }
</style>
