<script lang="ts">
// API IFrame YouTube : chargée une seule fois, à la première ouverture d'un lecteur
declare global {
  interface Window { YT?: any; onYouTubeIframeAPIReady?: () => void }
}

let apiReady: Promise<void> | undefined;
function loadApi(): Promise<void> {
  apiReady ??= new Promise((resolve) => {
    if (window.YT?.Player) return resolve();
    window.onYouTubeIframeAPIReady = () => resolve();
    const script = document.createElement("script");
    script.src = "https://www.youtube.com/iframe_api";
    document.head.appendChild(script);
  });
  return apiReady;
}
</script>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";

// changer de vidéo = recréer le composant (:key="videoId")
const props = defineProps<{ videoId: string }>();

const target = ref<HTMLDivElement>();
const time = ref(0);
let player: any;
let ready = false;
let stopAt: number | null = null;
let timer: ReturnType<typeof setInterval> | undefined;
let unmounted = false;

onMounted(async () => {
  await loadApi();
  if (unmounted || !target.value) return;
  player = new window.YT!.Player(target.value, {
    videoId: props.videoId,
    playerVars: { rel: 0 },
    events: { onReady: () => (ready = true) },
  });
  timer = setInterval(tick, 100);
});

onUnmounted(() => {
  unmounted = true;
  clearInterval(timer);
  player?.destroy();
});

function tick() {
  if (!ready) return;
  time.value = player.getCurrentTime();
  // relecture d'un clip : on s'arrête à sa fin
  if (stopAt != null && time.value >= stopAt) {
    player.pauseVideo();
    stopAt = null;
  }
}

function seek(sec: number) {
  if (!ready) return;
  stopAt = null;
  player.seekTo(sec, true);
}

function playRange(start: number, end: number) {
  if (!ready) return;
  player.seekTo(start, true);
  player.playVideo();
  stopAt = end;
}

defineExpose({ time, seek, playRange });
</script>

<template>
  <div class="yt-player"><div ref="target" /></div>
</template>

<style scoped>
.yt-player { aspect-ratio: 16/9; width: 100%; background: #000; border-radius: 8px; overflow: hidden; }
.yt-player :deep(iframe) { width: 100%; height: 100%; display: block; }
</style>
