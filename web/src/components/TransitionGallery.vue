<script setup lang="ts">
/**
 * La galerie des transitions, par famille : chaque vignette est la démo rendue par ffmpeg (A → B), figée au
 * milieu de la transition, qui se joue au survol. `pickable` : un clic choisit la transition.
 */
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { demoUrl, fxName, loadTransitions, type FxCatalog } from "../lib/transitions";

const props = defineProps<{ selected?: string | null; pickable?: boolean; small?: boolean }>();
const emit = defineEmits<{ pick: [string] }>();
const { t } = useI18n();

const catalog = ref<FxCatalog | null>(null);
const group = ref("all");
onMounted(async () => { catalog.value = await loadTransitions(); });

const groups = computed(() => catalog.value?.groups ?? []);
const shown = computed(() => (catalog.value?.items ?? []).filter((x) => group.value === "all" || x.group === group.value));

// le milieu de la démo : 0,5 s de A, 1 s de transition, 0,5 s de B
const MID = 1;
function play(e: Event) {
  const v = e.currentTarget as HTMLElement;
  const video = v.querySelector("video");
  if (!video) return;
  video.currentTime = 0;
  video.play().catch(() => {});
}
function rest(e: Event) {
  const video = (e.currentTarget as HTMLElement).querySelector("video");
  if (!video) return;
  video.pause();
  video.currentTime = MID;
}
</script>

<template>
  <div class="gallery" :class="{ small }">
    <div class="groups">
      <button :class="{ on: group === 'all' }" @click="group = 'all'">{{ t("transitions.all") }}</button>
      <button v-for="g in groups" :key="g" :class="{ on: group === g }" @click="group = g">{{ t(`transitions.groups.${g}`) }}</button>
    </div>
    <div class="grid">
      <component :is="pickable ? 'button' : 'div'" v-for="x in shown" :key="x.fx" class="tile" :class="{ on: selected === x.fx, pickable }"
        :title="fxName(x.fx)" @mouseenter="play" @mouseleave="rest" @click="pickable && emit('pick', x.fx)">
        <video :src="`${demoUrl(x.fx)}#t=${MID}`" muted loop playsinline preload="metadata" />
        <span class="name">{{ fxName(x.fx) }}</span>
      </component>
    </div>
  </div>
</template>

<style scoped>
.gallery { display: flex; flex-direction: column; gap: 14px; min-height: 0; }
.groups { display: flex; flex-wrap: wrap; gap: 4px; }
.groups button {
  padding: 5px 10px; border: 1px solid var(--line-strong); border-radius: 4px; background: #fff;
  font-size: 12.5px; color: var(--ink-2); cursor: pointer;
}
.groups button.on { background: var(--ink); border-color: var(--ink); color: #fff; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 14px; }
.small .grid { grid-template-columns: repeat(auto-fill, minmax(132px, 1fr)); gap: 10px; }
.tile {
  display: flex; flex-direction: column; gap: 6px; padding: 0; border: none; background: none; text-align: left; font: inherit;
}
.tile.pickable { cursor: pointer; }
.tile video {
  width: 100%; aspect-ratio: 16 / 9; display: block; border-radius: 4px; background: #1d1e20;
  outline: 2px solid transparent; outline-offset: 2px;
}
.tile.pickable:hover video { outline-color: var(--line-strong); }
.tile.on video { outline-color: var(--red); }
.name { font-size: 12.5px; color: var(--ink-2); }
.tile.on .name { color: var(--ink); font-weight: 600; }
.small .name { font-size: 12px; }
</style>
