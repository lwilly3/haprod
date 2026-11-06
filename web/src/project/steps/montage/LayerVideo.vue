<script setup lang="ts">
/** Une vidéo muette de l'aperçu (un B-roll), calée sur `time` (secondes dans le média) et sur la lecture. */
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { releaseMedia } from "../../../lib/media";

const props = defineProps<{ src: string; time: number; playing: boolean }>();
const el = ref<HTMLVideoElement | null>(null);

function sync() {
  const v = el.value;
  if (!v) return;
  const want = Math.max(0, props.time);
  if (Math.abs(v.currentTime - want) > (props.playing ? 0.3 : 0.001)) v.currentTime = want;
  if (props.playing && v.paused) v.play().catch(() => {});
  if (!props.playing && !v.paused) v.pause();
}
watch(() => [props.time, props.playing, props.src], sync);
onMounted(sync);
onBeforeUnmount(() => releaseMedia(el.value));
</script>

<template>
  <video ref="el" :src="src || undefined" muted playsinline preload="auto" @loadeddata="sync" />
</template>
