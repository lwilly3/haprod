<script setup lang="ts">
/** Le lecteur sombre : vidéo 16/9, sous-titre de la phrase en cours, début / ±1 s / lecture / temps. */
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { mmss } from "../../../lib/format";
import type { Playlist } from "./usePlaylist";

const { t } = useI18n();
const props = defineProps<{ player: Playlist; height: number; caption?: string }>();

const el = ref<HTMLVideoElement | null>(null);
onMounted(() => { props.player.video.value = el.value; });
onBeforeUnmount(() => { props.player.video.value = null; });
const step = (s: number) => props.player.seek(Math.max(0, Math.min(props.player.t.value + s, props.player.rawTotal.value)));
</script>

<template>
  <div class="player">
    <div class="stage">
      <div class="screen hatch-dark" :style="{ height: `${height}px` }">
        <video ref="el" preload="metadata" playsinline @click="player.toggle()" />
        <span v-if="caption" class="caption"><span>{{ caption }}</span></span>
      </div>
    </div>
    <div class="bar">
      <button class="ctl" :title="t('derush.player.restart')" @click="player.restart()">⏮</button>
      <button class="ctl wide" :title="t('derush.player.back1')" @click="step(-1)">−1 s</button>
      <button class="ctl play" :title="t('derush.player.playPause')" @click="player.toggle()">{{ player.playing.value ? "❚❚" : "▶" }}</button>
      <button class="ctl wide" :title="t('derush.player.fwd1')" @click="step(1)">+1 s</button>
      <span class="time now">{{ mmss(player.elapsed.value) }}</span>
      <span class="time dim">/ {{ mmss(player.total.value) }}</span>
      <div class="spacer" />
      <span class="info"><slot /></span>
    </div>
  </div>
</template>

<style scoped>
.player { display: flex; flex-direction: column; background: var(--ink); border-radius: 6px; overflow: hidden; }
.stage { display: flex; justify-content: center; padding: 16px 16px 0; }
.screen {
  position: relative; max-width: 100%; aspect-ratio: 16 / 9;
  display: flex; align-items: center; justify-content: center;
}
video { width: 100%; height: 100%; object-fit: contain; display: block; cursor: pointer; }
.caption {
  position: absolute; left: 10%; right: 10%; bottom: 16px; text-align: center;
  font-size: 14px; line-height: 1.5; color: #fff; text-wrap: pretty; pointer-events: none;
}
.caption > span {
  background: rgba(0, 0, 0, 0.65); padding: 2px 6px;
  -webkit-box-decoration-break: clone; box-decoration-break: clone;
}
.bar { display: flex; align-items: center; gap: 8px; padding: 12px 16px; }
.ctl {
  width: 34px; height: 34px; border: none; border-radius: 4px; background: transparent;
  color: #fff; font-size: 13px; cursor: pointer;
}
.ctl:hover { background: var(--ink-2); }
.ctl.wide { width: auto; padding: 0 8px; font-family: var(--mono); font-size: 12px; }
.ctl.play { width: 42px; background: #fff; color: var(--ink); }
.time { font-family: var(--mono); font-size: 13px; color: #fff; }
.time.now { padding-left: 6px; }
.time.dim { color: var(--faint); }
.info { font-family: var(--mono); font-size: 12px; color: var(--faint); }
</style>
