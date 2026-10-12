<script setup lang="ts">
/**
 * La médiathèque du dérush, comme dans un logiciel de montage : les rushes en vignettes (triés par heure de
 * tournage) et les timelines. On importe en glissant les fichiers ou par le bouton ; on pose un rush ou une
 * timeline sur la timeline ouverte avec « + » ou en le glissant dessus. Ctrl / Maj + clic : plusieurs rushes.
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import ConfirmX from "../../../components/ConfirmX.vue";
import Seg from "../../../components/Seg.vue";
import { mmss } from "../../../lib/format";
import { toast } from "../../../lib/toast";
import { droppedFiles, upload } from "../../../lib/upload";
import { act, refresh, store } from "../../store";
import type { Rush } from "../../types";
import { MEDIA_TYPE, type MediaItem, type useDerush } from "./useDerush";

const props = defineProps<{ derush: ReturnType<typeof useDerush> }>();
const emit = defineEmits<{ open: [tl: string] }>();
const { t } = useI18n();
const project = computed(() => store.project!);
const base = computed(() => `/api/projects/${project.value.id}`);
const d = props.derush;

// --- rushes, triés --------------------------------------------------------------------

type Sort = "time" | "name";
const sort = ref<Sort>("time");
const SORTS = computed(() => [["time", t("derush.pool.sorts.time")], ["name", t("derush.pool.sorts.name")]] as [Sort, string][]);
const byTime = (a: Rush, b: Rush) => (a.shot_at ?? "").localeCompare(b.shot_at ?? "") || a.name.localeCompare(b.name);
const rushes = computed(() => [...project.value.rushes].sort(sort.value === "time" ? byTime
  : (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true })));

/** Les rushes déjà lus par la timeline ouverte (coche, comme dans Filmora). */
const used = computed(() => new Set(d.flat.value.map((c) => c.rush)));

/** Les sections du script dites dans chaque rush (d'après le transcript). */
const sections = computed(() => {
  const a = d.analysis.value, out: Record<string, string[]> = {};
  if (!a?.ready) return out;
  for (const s of a.segs) {
    if (!s.sec) continue;
    const label = a.sections.find((k) => k.id === s.sec)?.label ?? s.sec;
    if (!(out[s.rush] ??= []).includes(label)) out[s.rush].push(label);
  }
  return out;
});

const tiles = computed(() => rushes.value.map((r) => {
  const tr = project.value.runtime.rush_transcripts[r.id];
  const status = tr?.status ?? "none";
  const busy = !["done", "error", "cancelled", "none"].includes(status);
  const lines = [r.name, r.time && t("derush.pool.shotAt", { time: r.time }), sections.value[r.id]?.join(", ")];
  return {
    rush: r, busy, error: status === "error",
    bar: busy ? tr?.progress ?? 0 : 0,
    badge: status === "queued" ? t("derush.pool.queued") : busy ? `${Math.round((tr?.progress ?? 0) * 100)} %` : mmss(r.duration),
    title: lines.filter(Boolean).join("\n"),
  };
}));

// --- sélection et pose sur la timeline ---------------------------------------------------

const selected = ref<string[]>([]);
function pick(e: MouseEvent, id: string) {
  if (e.shiftKey && selected.value.length) {
    const ids = rushes.value.map((r) => r.id), a = ids.indexOf(selected.value[selected.value.length - 1]), b = ids.indexOf(id);
    selected.value = [...new Set([...selected.value, ...ids.slice(Math.min(a, b), Math.max(a, b) + 1)])];
  } else if (e.ctrlKey || e.metaKey) {
    selected.value = selected.value.includes(id) ? selected.value.filter((k) => k !== id) : [...selected.value, id];
  } else selected.value = selected.value.length === 1 && selected.value[0] === id ? [] : [id];
}

/** Les rushes sélectionnés (sinon tous), par heure de tournage, au bout de la timeline ouverte. */
const toPlace = computed(() => {
  const list = project.value.rushes.filter((r) => !selected.value.length || selected.value.includes(r.id));
  return [...list].sort(byTime);
});
function placeByTime() {
  d.add(toPlace.value.map((r) => ({ rush: r.id })));
  selected.value = [];
}

function dragRush(e: DragEvent, id: string) {
  const ids = selected.value.includes(id) ? rushes.value.filter((r) => selected.value.includes(r.id)).map((r) => r.id) : [id];
  setDrag(e, ids.map((rush) => ({ rush })));
}
function setDrag(e: DragEvent, items: MediaItem[]) {
  e.dataTransfer?.setData(MEDIA_TYPE, JSON.stringify(items));
  if (e.dataTransfer) e.dataTransfer.effectAllowed = "copy";
}

// --- timelines ---------------------------------------------------------------------------

const timelines = computed(() => d.timelines.value.map((k) => ({
  id: k.id, name: d.nameOf(k.id), main: k.id === d.mainId.value, open: k.id === d.current.value,
  length: d.lengthOf(k.id), nestable: d.canNest(k.id),
})));

/** Nouvelle timeline : avec les rushes sélectionnés (par heure de tournage), sinon vide. */
function newTimeline() {
  const n = d.timelines.value.length + 1;
  const list = selected.value.length
    ? toPlace.value.filter((r) => r.duration).map((r) => ({ id: `c${Math.random().toString(36).slice(2, 10)}`, rush: r.id, in: 0, out: r.duration! }))
    : [];
  emit("open", d.create(t("derush.timelines.defaultName", { n }), list));
  selected.value = [];
}

// --- import ------------------------------------------------------------------------------

const importing = computed(() => project.value.runtime.importing.filter((f) => f.target === "rushes"));
/** Fichiers en cours d'envoi au serveur. */
const uploads = ref<{ name: string; pct: number }[]>([]);
const over = ref(false);
const input = ref<HTMLInputElement | null>(null);

async function send(files: File[]): Promise<void> {
  if (!files.length) return;
  uploads.value.push(...files.map((f) => ({ name: f.name, pct: 0 })));
  const mine = uploads.value.slice(-files.length);
  try {
    await upload(`${base.value}/rushes/upload`, files, "files", {}, (f) => {
      for (const u of mine) u.pct = Math.round(f * 100);
    });
    await refresh();
  } catch (err) {
    toast((err as Error).message, true);
  } finally {
    uploads.value = uploads.value.filter((u) => !mine.includes(u));
  }
}

function onPick(e: Event) {
  const el = e.target as HTMLInputElement;
  send(Array.from(el.files ?? []));
  el.value = "";
}

/** Des fichiers glissés depuis l'explorateur (pas une vignette de la médiathèque). */
function onDragOver(e: DragEvent) {
  if (!e.dataTransfer?.types.includes("Files")) return;
  e.preventDefault();
  over.value = true;
}
function onDrop(e: DragEvent) {
  over.value = false;
  send(droppedFiles(e));
}
</script>

<template>
  <div class="pool" :class="{ over }" @dragover="onDragOver" @dragleave.self="over = false" @drop.prevent="onDrop">
    <div class="bar">
      <button class="btn sm dark" @click="input?.click()">{{ t("derush.pool.import") }}</button>
      <input ref="input" type="file" multiple hidden accept="video/*,.mov,.mp4,.mxf,.mkv,.mts,.m4v,.avi,.webm" @change="onPick">
      <Seg v-model="sort" :options="SORTS" size="sm" />
      <div class="spacer" />
      <button class="btn sm" :disabled="!toPlace.length" :title="t('derush.pool.placeTitle')" @click="placeByTime">
        {{ selected.length ? t("derush.pool.placeSelected", { n: selected.length }) : t("derush.pool.placeAll") }}
      </button>
      <button class="btn sm" :title="t('derush.pool.newTimelineTitle')" @click="newTimeline">{{ t("derush.pool.newTimeline") }}</button>
    </div>

    <div class="eyebrow">{{ t("derush.pool.timelines") }}</div>
    <div class="grid">
      <div v-for="k in timelines" :key="k.id" class="tile" :class="{ open: k.open }" :draggable="k.nestable"
        :title="k.open ? t('derush.pool.openNow') : t('derush.pool.openTimeline')"
        @dragstart="setDrag($event, [{ tl: k.id }])" @click="emit('open', k.id)">
        <div class="thumb seq">
          <span class="seq-icon">⧉</span>
          <span v-if="k.main" class="main-badge">{{ t("derush.timelines.global") }}</span>
          <span class="dur mono">{{ mmss(k.length) }}</span>
          <button v-if="k.nestable" class="plus" :title="t('derush.pool.nest')" @click.stop="d.add([{ tl: k.id }])">+</button>
        </div>
        <div class="name">{{ k.name }}</div>
      </div>
    </div>

    <div class="eyebrow">{{ t("derush.pool.rushes", { n: rushes.length }) }}</div>
    <div class="grid">
      <div class="tile add" @click="input?.click()">
        <div class="thumb">+</div>
        <div class="name">{{ t("derush.pool.drop") }}</div>
      </div>
      <div v-for="k in tiles" :key="k.rush.id" class="tile" :class="{ on: selected.includes(k.rush.id) }" draggable="true"
        :title="k.title" @dragstart="dragRush($event, k.rush.id)" @click="pick($event, k.rush.id)">
        <div class="thumb">
          <img :src="`${base}/rushes/${k.rush.id}/thumb`" alt="" loading="lazy" draggable="false"
            @error="($event.target as HTMLImageElement).style.visibility = 'hidden'">
          <span class="dur mono" :class="{ error: k.error }">{{ k.error ? t("derush.pool.error") : k.badge }}</span>
          <span v-if="used.has(k.rush.id)" class="check" :title="t('derush.pool.used')">✓</span>
          <div class="tools" @click.stop>
            <button :disabled="k.busy" :title="t('derush.pool.retranscribe')" @click="act(`/rushes/${k.rush.id}/transcribe`)">↻</button>
            <ConfirmX :label="t('derush.pool.removeConfirm')" :title="t('derush.pool.removeTitle')"
              @confirm="act(`/rushes/${k.rush.id}`, undefined, 'DELETE')" />
          </div>
          <button class="plus" :title="t('derush.pool.append')" @click.stop="d.add([{ rush: k.rush.id }])">+</button>
          <div v-if="k.busy" class="progress red"><div :style="{ width: `${k.bar * 100}%` }" /></div>
        </div>
        <div class="name mono">{{ k.rush.name }}</div>
        <div v-if="k.rush.time" class="time mono">{{ k.rush.time }}</div>
      </div>
      <div v-for="(f, j) in [...importing.map((x) => ({ name: x.name, pct: x.pct })), ...uploads]" :key="`up-${j}-${f.name}`" class="tile">
        <div class="thumb pending">
          <span class="dur mono">{{ t("derush.pool.importing", { p: f.pct }) }}</span>
          <div class="progress red"><div :style="{ width: `${f.pct}%` }" /></div>
        </div>
        <div class="name mono">{{ f.name }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pool { display: flex; flex-direction: column; gap: 10px; min-height: 100%; border-radius: 4px; }
.pool.over { outline: 2px dashed var(--ink); outline-offset: -2px; background: var(--bg-softer); }
.bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.spacer { flex: 1; }
.eyebrow { padding-top: 4px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px 10px; }

.tile { display: flex; flex-direction: column; gap: 4px; min-width: 0; cursor: pointer; }
.thumb {
  position: relative; aspect-ratio: 16 / 9; border-radius: 4px; overflow: hidden; background: #2B2C2E;
  display: flex; align-items: center; justify-content: center; color: #fff; outline: 2px solid transparent; outline-offset: 1px;
}
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.tile.on .thumb { outline-color: var(--red); }
.tile.open .thumb { outline-color: #3B82C4; }
.tile.add .thumb { background: var(--bg-soft); color: var(--muted); font-size: 28px; border: 1px dashed var(--dash); }
.tile.add:hover .thumb { border-color: var(--ink); color: var(--ink); }
.thumb.seq { background: repeating-linear-gradient(135deg, #2B3440 0 10px, #323C49 10px 20px); }
.thumb.pending { background: var(--bg-soft); }
.seq-icon { font-size: 26px; opacity: .8; }
.main-badge { position: absolute; top: 5px; left: 5px; font-size: 10.5px; padding: 1px 6px; border-radius: 3px; background: var(--red); color: #fff; }
.dur {
  position: absolute; left: 5px; bottom: 5px; font-size: 10.5px; padding: 1px 5px; border-radius: 3px;
  background: rgba(0, 0, 0, .65); color: #fff;
}
.thumb.pending .dur { background: none; color: var(--muted); position: static; }
.dur.error { background: var(--red); }
.check {
  position: absolute; right: 5px; bottom: 5px; width: 18px; height: 18px; border-radius: 50%;
  background: #3E9E6E; color: #fff; font-size: 11px; display: flex; align-items: center; justify-content: center;
}
.plus {
  position: absolute; right: 5px; bottom: 5px; width: 24px; height: 24px; border-radius: 50%; border: none; cursor: pointer;
  background: #fff; color: var(--ink); font-size: 16px; line-height: 1; display: none;
}
.tile:hover .plus { display: block; }
.tile:hover .check { display: none; }
.tools { position: absolute; top: 4px; right: 4px; display: none; gap: 2px; align-items: center; padding: 1px 3px; border-radius: 3px; background: rgba(255, 255, 255, .92); }
.tile:hover .tools { display: flex; }
.tools button:not(.armed):not(.x-btn) { border: none; background: none; cursor: pointer; font-size: 13px; color: var(--ink); padding: 0 3px; }
.tools button:disabled { color: var(--dash); cursor: default; }
.thumb .progress { position: absolute; left: 0; right: 0; bottom: 0; }
.name { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.name.mono { font-size: 11.5px; }
.time { font-size: 10.5px; color: var(--faint); margin-top: -3px; }
</style>
