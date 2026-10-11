<script setup lang="ts">
/** Colonne Rushes du dérush : import (même après coup), ordre de lecture, transcription et plans détectés. */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import ConfirmX from "../../../components/ConfirmX.vue";
import Seg from "../../../components/Seg.vue";
import { api } from "../../../lib/api";
import { mmss } from "../../../lib/format";
import { toast } from "../../../lib/toast";
import { droppedFiles, upload } from "../../../lib/upload";
import { act, refresh, store, update } from "../../store";
import type { DerushAnalysis, Project, Rush } from "../../types";

defineProps<{ embedded?: boolean }>();
const emit = defineEmits<{ append: [rush: string] }>();
const { t } = useI18n();
const project = computed(() => store.project!);
const base = computed(() => `/api/projects/${project.value.id}`);

// --- ordre --------------------------------------------------------------------------

type Sort = Project["rush_sort"];
const SORTS = computed(() => [
  ["Script", t("derush.panel.sorts.script")],
  ["Heure", t("derush.panel.sorts.time")],
  ["Manuel", t("derush.panel.sorts.manual")],
] as [Sort, string][]);

/** « Manuel » ne se choisit pas : il s'applique dès qu'on déplace un rush. */
const sort = computed<Sort>({
  get: () => project.value.rush_sort,
  set: (mode) => {
    if (mode !== "Manuel" && mode !== project.value.rush_sort) act("/rushes/sort", { mode });
  },
});

function move(i: number, d: number): void {
  const ids = project.value.rushes.map((r) => r.id), j = i + d;
  if (j < 0 || j >= ids.length) return;
  [ids[i], ids[j]] = [ids[j], ids[i]];
  update({ rush_order: ids, rush_sort: "Manuel" });
}

/** Glisser-déposer d'une carte sur une autre : le rush prend sa place. */
const dragFrom = ref<number | null>(null);
const dragOver = ref<number | null>(null);
function dropOn(i: number): void {
  const from = dragFrom.value;
  dragFrom.value = dragOver.value = null;
  if (from == null || from === i) return;
  const ids = project.value.rushes.map((r) => r.id);
  const [id] = ids.splice(from, 1);
  ids.splice(i, 0, id);
  update({ rush_order: ids, rush_sort: "Manuel" });
}

function retranscribe(r: Rush): void {
  act(`/rushes/${r.id}/transcribe`);
}

function remove(r: Rush): void {
  act(`/rushes/${r.id}`, undefined, "DELETE");
}

// --- plans détectés (dérush), une fois tout transcrit --------------------------------

const derush = ref<DerushAnalysis | null>(null);
const transcribed = computed(() => {
  const p = project.value;
  return p.rushes.length > 0 && p.rushes.every((r) => p.runtime.rush_transcripts[r.id]?.status === "done");
});

watch(
  () => (transcribed.value
    ? project.value.rushes.map((r) => r.id).sort().join() + project.value.runtime.docs["script.md"]
    : ""),
  async (key) => {
    if (!key) {
      derush.value = null;
      return;
    }
    try {
      derush.value = await api<DerushAnalysis>(`${base.value}/derush`);
    } catch {
      derush.value = null;
    }
  },
  { immediate: true },
);

/** Libellés des sections du script dites dans ce rush. */
function sectionsOf(rid: string): string[] {
  const d = derush.value;
  if (!d) return [];
  const ids = [...new Set(d.segs.filter((s) => s.rush === rid && s.sec).map((s) => s.sec as string))];
  return ids.map((id) => d.sections.find((s) => s.id === id)?.label ?? id);
}

const cards = computed(() => project.value.rushes.map((r, i) => {
  const tr = project.value.runtime.rush_transcripts[r.id];
  const status = tr?.status ?? "none";
  const busy = !["done", "error", "cancelled", "none"].includes(status);
  const secs = sectionsOf(r.id);
  const detected = secs.length ? secs.join(", ")
    : busy ? t("derush.panel.transcribingShort") : t("derush.panel.shotNotDetected");
  return {
    rush: r,
    status: status === "error" ? t("derush.panel.error") : status === "queued" ? t("derush.panel.queued")
      : busy ? t("derush.panel.transcription", { p: Math.round((tr?.progress ?? 0) * 100) }) : mmss(r.duration),
    meta: [r.time && t("derush.panel.shotAt", { time: r.time }), detected].filter(Boolean).join(" · "),
    bar: status === "done" ? 1 : busy ? tr?.progress ?? 0 : 0,
    busy,
    first: i === 0,
    last: i === project.value.rushes.length - 1,
  };
}));

// --- import --------------------------------------------------------------------------

const importing = computed(() => project.value.runtime.importing.filter((f) => f.target === "rushes"));
/** Fichiers glissés en cours d'envoi au serveur. */
const uploads = ref<{ name: string; pct: number }[]>([]);
const over = ref(false);

function browse(): void {
  act("/rushes/browse");
}

async function onDrop(e: DragEvent): Promise<void> {
  over.value = false;
  const files = droppedFiles(e);
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

const pad = (n: number) => String(n).padStart(2, "0");
</script>

<template>
  <div class="rushes">
    <div class="head">
      <span v-if="!embedded" class="eyebrow">{{ t("derush.panel.title") }}</span>
      <div v-else class="spacer" />
      <button class="btn dark" @click="browse">{{ t("derush.panel.import") }}</button>
    </div>
    <div class="order">
      <div class="order-row">
        <span>{{ t("derush.panel.order") }}</span>
        <Seg v-model="sort" :options="SORTS" size="sm" />
      </div>
      <span class="note">{{ t("derush.panel.note") }}</span>
    </div>

    <div v-for="(c, i) in cards" :key="c.rush.id" class="card" draggable="true"
      :class="{ dragging: dragFrom === i, over: dragOver === i && dragFrom !== i }"
      @dragstart="dragFrom = i" @dragend="dragFrom = dragOver = null"
      @dragover="dragFrom != null && ($event.preventDefault(), dragOver = i)" @drop.prevent="dropOn(i)">
      <div class="line1">
        <span class="name-wrap">
          <span class="idx mono">{{ pad(i + 1) }}</span>
          <span class="name mono" :title="c.rush.name">{{ c.rush.name }}</span>
        </span>
        <span class="status">{{ c.status }}</span>
        <ConfirmX :label="t('derush.panel.removeConfirm')" :title="t('derush.panel.removeTitle')" @confirm="remove(c.rush)" />
      </div>
      <div class="line2">
        <span class="meta">{{ c.meta }}</span>
        <div class="moves">
          <button v-if="embedded" class="add" :title="t('derush.panel.appendTitle')" @click="emit('append', c.rush.id)">{{ t("derush.panel.append") }}</button>
          <button :disabled="c.busy" :title="t('derush.panel.retranscribe')" @click="retranscribe(c.rush)">↻</button>
          <button :disabled="c.first" :title="t('derush.panel.moveUp')" @click="move(i, -1)">↑</button>
          <button :disabled="c.last" :title="t('derush.panel.moveDown')" @click="move(i, 1)">↓</button>
        </div>
      </div>
      <div class="progress"><div :style="{ width: `${c.bar * 100}%` }" /></div>
    </div>

    <div v-for="(f, j) in importing" :key="`imp-${f.name}`" class="card">
      <div class="line1">
        <span class="name-wrap">
          <span class="idx mono">{{ pad(cards.length + j + 1) }}</span>
          <span class="name mono" :title="f.name">{{ f.name }}</span>
        </span>
        <span class="status">{{ f.error ? t("derush.panel.error") : t("derush.panel.importing", { p: f.pct }) }}</span>
      </div>
      <div class="progress red"><div :style="{ width: `${f.pct}%` }" /></div>
    </div>

    <div v-for="(u, j) in uploads" :key="`up-${j}-${u.name}`" class="card">
      <div class="line1">
        <span class="name-wrap">
          <span class="idx mono">{{ pad(cards.length + importing.length + j + 1) }}</span>
          <span class="name mono" :title="u.name">{{ u.name }}</span>
        </span>
        <span class="status">{{ t("derush.panel.importing", { p: u.pct }) }}</span>
      </div>
      <div class="progress red"><div :style="{ width: `${u.pct}%` }" /></div>
    </div>

    <div class="drop-zone" :class="{ over }" @click="browse" @dragover.prevent="over = true"
      @dragleave="over = false" @drop.prevent="onDrop">
      {{ t("derush.panel.drop") }}
    </div>
  </div>
</template>

<style scoped>
.rushes { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.head { display: flex; justify-content: space-between; align-items: center; padding-bottom: 4px; }
.head .btn { padding: 0 14px; }
.order { display: flex; flex-direction: column; gap: 6px; }
.order-row { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--muted); }
.note { font-size: 12px; color: var(--faint); line-height: 1.45; }
.card { display: flex; flex-direction: column; gap: 7px; padding: 12px; border: 1px solid var(--line); border-radius: 4px; cursor: grab; background: #fff; }
.card.dragging { opacity: .4; }
.card.over { border-color: #3B82C4; box-shadow: 0 -3px 0 #3B82C4; }
.line1 { display: flex; align-items: baseline; gap: 8px; font-size: 13.5px; }
.name-wrap { display: flex; gap: 8px; min-width: 0; flex: 1; }
.idx { font-size: 11.5px; color: var(--faint); }
.name { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.status { color: var(--muted); flex-shrink: 0; }
.line1 > :last-child { align-self: center; }
.line2 { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.meta { font-size: 12.5px; color: var(--muted); min-width: 0; }
.moves { display: flex; gap: 4px; flex-shrink: 0; }
.moves button {
  width: 26px; height: 26px; padding: 0; border: 1px solid var(--line-strong); border-radius: 3px;
  background: #fff; font-size: 12px; cursor: pointer; color: var(--ink);
}
.moves button:hover:not(:disabled) { border-color: var(--faint); }
.moves button:disabled { color: var(--dash); cursor: default; }
.moves button.add { width: auto; padding: 0 8px; font-size: 11.5px; }
.progress { background: var(--line-soft); }
.drop-zone { padding: 24px; }
</style>
