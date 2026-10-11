<script setup lang="ts">
/**
 * La popup des médias à poser au curseur : rushes, assets du projet et bibliothèque commune, par onglet et par
 * recherche. On écoute ou regarde l'élément choisi avant de le poser au-dessus de l'A-roll, ou (vidéo) de l'insérer
 * dans l'A-roll. On peut aussi le glisser sur la timeline : la popup s'efface le temps du glisser.
 * ↑ ↓ choisissent, Entrée pose au curseur, Échap ferme.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import Seg from "../../../components/Seg.vue";
import { duration as fmtDur } from "../../../lib/format";
import { isVideo, MEDIA_DRAG } from "./ops";
import { tcd, type AvailableMedia, type MediaTab } from "./types";

const props = defineProps<{ available: AvailableMedia[]; t: number }>();
const emit = defineEmits<{ add: [AvailableMedia]; insert: [AvailableMedia] }>();
const tab = defineModel<MediaTab | null>({ required: true });
const { t: tr } = useI18n();

const query = ref("");
const current = ref<AvailableMedia | null>(null);
const dragging = ref(false);
const search = ref<HTMLInputElement | null>(null);
const listEl = ref<HTMLElement | null>(null);

const TABS = computed(() => {
  const n = (c: MediaTab) => props.available.filter((m) => c === "all" || m.category === c).length;
  return ([["all", "tabAll"], ["rush", "tabRush"], ["broll", "tabBroll"], ["sfx", "tabSfx"], ["musique", "tabMusic"]] as const)
    .map(([k, label]) => [k, `${tr(`editing.picker.${label}`)} · ${n(k)}`] as const);
});
const list = computed(() => {
  const words = query.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return props.available.filter((m) => (tab.value === "all" || m.category === tab.value)
    && words.every((w) => `${m.name} ${m.description ?? ""}`.toLowerCase().includes(w)));
});
const shown = computed(() => list.value.slice(0, 300));

// à l'ouverture : la recherche prend le clavier ; on repart d'une recherche vide
watch(tab, (v, old) => {
  if (!v) return;
  if (!old) {
    query.value = "";
    current.value = null;
    dragging.value = false;
    nextTick(() => search.value?.focus());
  }
});
// le premier de la liste est choisi, tant qu'on n'en a pas choisi un autre qui y est encore
watch(list, (l) => { if (!current.value || !l.includes(current.value)) current.value = l[0] ?? null; }, { immediate: true });

function close() { tab.value = null; }
function add(m: AvailableMedia) { emit("add", m); close(); }
function insert(m: AvailableMedia) { emit("insert", m); close(); }

function move(d: number) {
  const l = shown.value;
  if (!l.length) return;
  const i = current.value ? l.indexOf(current.value) : -1;
  current.value = l[Math.max(0, Math.min(l.length - 1, i + d))];
  nextTick(() => listEl.value?.querySelector(".m.on")?.scrollIntoView({ block: "nearest" }));
}
function onKey(e: KeyboardEvent) {
  if (!tab.value) return;
  // popup ouverte : les raccourcis du montage (Suppr, lame, flèches…) ne passent pas
  e.stopPropagation();
  if (e.key === "Escape") close();
  else if (e.key === "ArrowDown") move(1);
  else if (e.key === "ArrowUp") move(-1);
  else if (e.key === "Enter" && current.value && (e.target as HTMLElement).tagName !== "BUTTON") add(current.value);
  else return;
  e.preventDefault();
}
onMounted(() => document.addEventListener("keydown", onKey, true));
onBeforeUnmount(() => document.removeEventListener("keydown", onKey, true));

function dragStart(e: DragEvent, m: AvailableMedia) {
  e.dataTransfer?.setData(MEDIA_DRAG, JSON.stringify(m));
  if (e.dataTransfer) e.dataTransfer.effectAllowed = "copy";
  // pas tout de suite : le navigateur prend l'image du glisser après ce gestionnaire
  requestAnimationFrame(() => (dragging.value = true));
}
function dragEnd(e: DragEvent) {
  dragging.value = false;
  if (e.dataTransfer?.dropEffect !== "none") close();
}

const label = (c: AvailableMedia["category"]) => tr(`editing.picker.${{ rush: "tabRush", broll: "tabBroll", sfx: "tabSfx", musique: "tabMusic" }[c]}`);
</script>

<template>
  <Teleport to="body">
    <template v-if="tab">
      <div class="backdrop" :class="{ dragging }" @click="close" />
      <div class="picker" :class="{ dragging }" role="dialog">
        <div class="head">
          <span class="eyebrow">{{ tr("editing.picker.title", { tc: tcd(t) }) }}</span>
          <span class="spacer" />
          <button class="x-btn" :title="tr('common.close')" @click="close">×</button>
        </div>
        <input ref="search" v-model="query" class="input search" :placeholder="tr('editing.picker.search')">
        <Seg v-model="tab" :options="TABS" size="sm" />
        <div class="body">
          <div ref="listEl" class="list">
            <div v-for="m in shown" :key="m.src" class="m" :class="{ on: m === current }" draggable="true" :title="m.src"
              @click="current = m" @dblclick="add(m)" @dragstart="dragStart($event, m)" @dragend="dragEnd">
              <span class="n">{{ m.name }}</span>
              <span class="mono d">{{ m.duration ? fmtDur(m.duration) : "" }}</span>
              <span class="w">{{ tab === "all" ? label(m.category) : m.where }}</span>
            </div>
            <span v-if="!list.length" class="hint empty">{{ tr("editing.picker.empty") }}</span>
            <span v-else-if="list.length > shown.length" class="hint empty">{{ tr("editing.picker.more", { n: list.length - shown.length }) }}</span>
          </div>
          <div class="side">
            <template v-if="current">
              <video v-if="current.kind === 'Vidéo'" :key="current.url" :src="current.url" controls preload="metadata" />
              <audio v-else-if="current.kind === 'Audio'" :key="current.url" :src="current.url" controls preload="metadata" />
              <span class="t" :title="current.name">{{ current.name }}</span>
              <span class="mono sub">{{ [label(current.category), current.where, current.duration ? fmtDur(current.duration) : ""].filter(Boolean).join(" · ") }}</span>
              <p v-if="current.description" class="desc">{{ current.description }}</p>
              <div class="row">
                <button class="btn sm" @click="add(current)">{{ tr("editing.picker.add") }}</button>
                <button v-if="isVideo(current)" class="btn sm" :title="tr('editing.inspector.insertArollTitle', { tc: tcd(t) })"
                  @click="insert(current)">{{ tr("editing.inspector.insertAroll") }}</button>
              </div>
            </template>
          </div>
        </div>
        <p class="hint">{{ tr("editing.picker.hint") }}</p>
      </div>
    </template>
  </Teleport>
</template>

<style scoped>
.backdrop { position: fixed; inset: 0; z-index: 40; background: rgba(24, 25, 27, .45); }
.picker {
  position: fixed; z-index: 41; top: 50%; left: 50%; transform: translate(-50%, -50%); width: min(980px, 92vw); height: min(640px, 86vh);
  background: #fff; border-radius: 6px; box-shadow: 0 16px 48px rgba(0, 0, 0, .3); padding: 16px;
  display: flex; flex-direction: column; gap: 10px;
}
/* pendant un glisser vers la timeline, la popup laisse passer la souris */
.dragging { opacity: 0; pointer-events: none; }
.head { display: flex; align-items: center; gap: 10px; }
.input.search { height: 36px; padding: 0 10px; font-size: 14px; }
.body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 14px; }
.list { overflow-y: auto; border: 1px solid var(--line-soft); border-radius: 3px; }
.m { display: flex; align-items: baseline; gap: 10px; padding: 7px 10px; cursor: grab; border-bottom: 1px solid var(--line-soft); }
.m:hover { background: var(--bg-soft); }
.m.on { background: var(--ink); color: #fff; }
.m.on .d, .m.on .w { color: rgba(255, 255, 255, .7); }
.m .n { flex: 1; min-width: 0; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.m .d { font-size: 11px; color: var(--faint); }
.m .w { font-size: 10.5px; color: var(--off); white-space: nowrap; }
.side { display: flex; flex-direction: column; gap: 8px; min-width: 0; overflow-y: auto; }
.side video { width: 100%; aspect-ratio: 16 / 9; background: #111; border-radius: 4px; }
.side audio { width: 100%; }
.t { font-size: 14px; font-weight: 600; word-break: break-all; }
.sub { font-size: 12px; color: var(--muted); }
.desc { margin: 0; font-size: 12.5px; color: var(--muted); line-height: 1.5; }
.row { display: flex; gap: 8px; flex-wrap: wrap; }
.hint { margin: 0; font-size: 12px; color: var(--faint); line-height: 1.5; }
.empty { display: block; padding: 10px; }
</style>
