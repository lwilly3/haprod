<script setup lang="ts">
/**
 * Dérush, façon logiciel de montage : le lecteur, le transcript de la timeline (où l'on retire phrases,
 * mots et silences), la liste des rushes ou le dérush proposé par Daryl, et la timeline : des bouts de rushes qu'on déplace, coupe,
 * rogne ou supprime.
 */
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { api } from "../../lib/api";
import { mmss } from "../../lib/format";
import { toast } from "../../lib/toast";
import { act, failed, running, store } from "../store";
import type { AutoCut, DerushClip, DerushSeg } from "../types";
import AutoDerush from "./derush/AutoDerush.vue";
import { clipAt, clipLen, move, offsets, remove, removeRange, removeRushRanges, splitAt, timeOf, trim, type Selection } from "./derush/clips";
import PlayerFrame from "./derush/PlayerFrame.vue";
import RushPanel from "./derush/RushPanel.vue";
import Timeline, { type Peaks } from "./derush/Timeline.vue";
import Transcript from "./derush/Transcript.vue";
import { useDerush } from "./derush/useDerush";
import { usePlaylist, type Piece } from "./derush/usePlaylist";

const { t, locale } = useI18n();
const router = useRouter();
const project = computed(() => store.project!);
const base = computed(() => `/api/projects/${project.value.id}`);
const derush = useDerush(project);
const { analysis, ready, segsByRush, clips, kept, transcribing, progress } = derush;

const names = computed(() => Object.fromEntries(project.value.rushes.map((r) => [r.id, r.name])));
const durations = computed(() => Object.fromEntries(project.value.rushes.map((r) => [r.id, r.duration ?? 0])));
const PALETTE = ["#3A3B3D", "#2E5E7E", "#5B4B7D", "#2F6B57", "#7A4F31", "#6E3049", "#4D5A2B", "#36507A"];
const colors = computed(() => Object.fromEntries(project.value.rushes.map((r, i) => [r.id, PALETTE[i % PALETTE.length]])));
const media = (rush: string) => `${base.value}/rushes/${rush}/media`;

const pieces = computed<Piece[]>(() => clips.value.map((c) => ({ src: media(c.rush), start: c.in, end: c.out, on: true })));
const player = usePlaylist(pieces);
const selection = ref<Selection>(null);
const tool = ref<"select" | "blade">("select");
const tl = ref<InstanceType<typeof Timeline> | null>(null);
const tab = ref<"transcript" | "rushes" | "daryl">("transcript");

/** La phrase sous la tête de lecture, en sous-titre. */
const caption = computed(() => {
  const hit = clipAt(clips.value, player.t.value);
  if (!hit) return "";
  const s = segsByRush.value[hit.c.rush]?.find((k) => k.start <= hit.at && hit.at < k.end);
  return s && s.type !== "sil" ? s.text : "";
});
const info = computed(() => {
  const raw = mmss(project.value.rushes.reduce((a, r) => a + (r.duration ?? 0), 0));
  return t("derush.info.ready", { raw, kept: mmss(kept.value) });
});

// --- formes d'onde, rush par rush
const peaks = shallowRef<Record<string, Peaks | undefined>>({});
const noPeaks = new Set<string>();
let loadingPeaks = false;
async function loadPeaks() {
  if (loadingPeaks) return;
  loadingPeaks = true;
  try {
    for (;;) {
      const r = project.value.rushes.find((k) => k.duration && !peaks.value[k.id] && !noPeaks.has(k.id));
      if (!r) break;
      try {
        peaks.value = { ...peaks.value, [r.id]: await api<Peaks>(`${base.value}/rushes/${r.id}/peaks`) };
      } catch {
        noPeaks.add(r.id);
      }
    }
  } finally {
    loadingPeaks = false;
  }
}
watch(() => project.value.rushes.map((r) => `${r.id}:${r.duration}`).join(), loadPeaks, { immediate: true });

// --- retouches
const hasSel = computed(() => !!selection.value);

/**
 * Recale la tête de lecture après le retrait des plages `cut` de la timeline : dans une plage retirée,
 * elle revient à son début (là où reprend la suite) ; après, elle suit le contenu qui a glissé.
 */
function cutAndFollow(cut: [number, number][], fn: (list: typeof clips.value) => typeof clips.value) {
  const here = player.t.value;
  let to = here;
  for (const [a, b] of cut) {
    if (here >= b) to -= b - a;
    else if (here > a) to -= here - a;
  }
  derush.edit(fn);
  selection.value = null;
  player.seek(Math.max(0, to));
}

/** Suppr : retire de la timeline les bouts sélectionnés, ou la plage. */
function cutSelection() {
  const s = selection.value;
  if (!s) return;
  if ("clips" in s) {
    const o = offsets(clips.value);
    const cut = clips.value.flatMap((c, k): [number, number][] => (s.clips.includes(c.id) ? [[o[k], o[k] + c.out - c.in]] : []));
    cutAndFollow(cut, (list) => remove(list, s.clips));
  } else removeSpan(s.range[0], s.range[1]);
}

function removeSpan(a: number, b: number) {
  cutAndFollow([[Math.min(a, b), Math.max(a, b)]], (list) => removeRange(list, a, b));
}

function onMove(ids: string[], before: string | null) {
  derush.edit((list) => move(list, ids, before));
}

function onTrim(id: string, side: "in" | "out", value: number) {
  const c = clips.value.find((k) => k.id === id);
  if (c) derush.edit((list) => trim(list, id, side, value, durations.value[c.rush] || c.out));
}

function onSplit(at: number) {
  derush.edit((list) => splitAt(list, at));
}

/** Les silences (ou prises ratées) encore présents dans la timeline, rush par rush. */
function present(type: DerushSeg["type"]) {
  const out: Record<string, [number, number][]> = {};
  let n = 0, dur = 0;
  for (const [rush, segs] of Object.entries(segsByRush.value)) {
    const mine = clips.value.filter((c) => c.rush === rush);
    for (const s of segs) {
      if (s.type !== type) continue;
      const inside = mine.reduce((a, c) => a + Math.max(0, Math.min(c.out, s.end) - Math.max(c.in, s.start)), 0);
      if (inside < 0.05) continue;
      (out[rush] ??= []).push([s.start, s.end]);
      n++;
      dur += inside;
    }
  }
  return { ranges: out, n, dur };
}
const silences = computed(() => present("sil"));
const retakes = computed(() => present("retake"));
const hasRetakes = computed(() => Object.values(segsByRush.value).some((l) => l.some((s) => s.type === "retake")));
const silLabel = computed(() => {
  const { n, dur } = silences.value;
  if (!n) return t("derush.silences.done");
  return t("derush.silences.cut", { n, dur: dur.toLocaleString(locale.value, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) });
});

function cutAll(found: { ranges: Record<string, [number, number][]>; n: number }, key: string) {
  if (!found.n) return;
  derush.edit((list) => Object.entries(found.ranges).reduce((acc, [rush, r]) => removeRushRanges(acc, rush, r), list));
  toast(t(key, { n: found.n }));
}

// --- dérush automatique (onglet Daryl)
/** En dessous, un bout laissé entre deux coupes ne ferait qu'un flash : il part avec elles. */
const MIN_KEEP = 0.3;

function applyAuto(cuts: AutoCut[]) {
  const byRush: Record<string, [number, number][]> = {};
  for (const c of cuts) (byRush[c.rush] ??= []).push([c.start, c.end]);
  derush.edit((list) => {
    const before = new Map(list.map((c) => [c.id, c]));
    const next = Object.entries(byRush).reduce((acc, [rush, r]) => removeRushRanges(acc, rush, r), list);
    const same = (c: DerushClip) => before.get(c.id)?.in === c.in && before.get(c.id)?.out === c.out;
    return next.filter((c) => clipLen(c) >= MIN_KEEP || same(c));
  });
}

/** Écoute un passage d'un rush : un peu avant, pour entendre ce qui précède la coupe. */
function seekRush(rush: string, t: number) {
  const at = timeOf(clips.value, rush, t);
  if (at == null) return;
  player.seek(Math.max(0, at - 1));
  if (!player.playing.value) player.toggle();
}

// --- clavier, comme dans un logiciel de montage
const fps = computed(() => project.value.rushes[0]?.fps || 25);
const nudge = (d: number) => player.seek(Math.max(0, player.t.value + d));
/** Saute au début du bout précédent / suivant. */
function jump(dir: 1 | -1) {
  const here = player.t.value, bounds = [...offsets(clips.value), kept.value];
  const to = dir > 0 ? bounds.find((b) => b > here + 1e-3) : bounds.reverse().find((b) => b < here - 1e-3);
  if (to != null) player.seek(to);
}
function mark(side: 0 | 1) {
  const now = player.t.value, s = selection.value;
  const r: [number, number] = s && "range" in s ? [...s.range] : [now, now];
  selection.value = { range: side ? [Math.min(r[0], now), now] : [now, Math.max(r[1], now)] };
}

function onKey(e: KeyboardEvent) {
  const el = e.target as HTMLElement | null;
  if (el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))) return;
  const ctrl = e.ctrlKey || e.metaKey, k = e.key.toLowerCase();
  let done = true;
  if (ctrl && k === "z" && !e.shiftKey) derush.undo();
  else if (ctrl && (k === "y" || (k === "z" && e.shiftKey))) derush.redo();
  else if (ctrl && k === "b") onSplit(player.t.value);
  else if (ctrl || e.altKey) done = false;
  else if (e.key === "Delete" || e.key === "Backspace") cutSelection();
  else if (e.key === "ArrowLeft") nudge(e.shiftKey ? -1 : -1 / fps.value);
  else if (e.key === "ArrowRight") nudge(e.shiftKey ? 1 : 1 / fps.value);
  else if (e.key === "ArrowUp") jump(-1);
  else if (e.key === "ArrowDown") jump(1);
  else if (e.key === "Escape") selection.value = null;
  else if (k === "i") mark(0);
  else if (k === "o") mark(1);
  else if (k === "a") tool.value = "select";
  else if (k === "b") tool.value = "blade";
  else if (k === "s") onSplit(player.t.value);
  else if (k === "z" && e.shiftKey) tl.value?.fit();
  else if (e.key === "+" || e.key === "=") tl.value?.zoomBy(1.5);
  else if (e.key === "-") tl.value?.zoomBy(1 / 1.5);
  else done = false;
  if (done) e.preventDefault();
}
onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));

// --- export et validation
const exportOpen = ref(false);
const menu = ref<HTMLElement | null>(null);
function closeMenu(e: PointerEvent) {
  if (exportOpen.value && !menu.value?.contains(e.target as Node)) exportOpen.value = false;
}
onMounted(() => document.addEventListener("pointerdown", closeMenu));
onUnmounted(() => document.removeEventListener("pointerdown", closeMenu));

const render = computed(() => project.value.runtime.jobs.render ?? null);
const renderPct = computed(() => Math.round((render.value?.progress ?? 0) * 100));

function exportXml() {
  exportOpen.value = false;
  toast(t("derush.export.xmlDone", { d: mmss(kept.value) }));
}

async function exportMp4() {
  exportOpen.value = false;
  if (await act("/derush/export.mp4")) toast(t("derush.export.mp4Started", { d: mmss(kept.value) }));
}

async function validate() {
  if (await act("/steps/derush", { done: true })) router.push(`/p/${project.value.id}/transcript`);
}
</script>

<template>
  <div v-if="!project.rushes.length" class="empty">
    <div class="dashed-box">{{ t("derush.empty") }}</div>
    <div class="side"><RushPanel /></div>
  </div>

  <div v-else class="derush">
    <div class="top">
      <PlayerFrame :player="player" :height="300" :caption="caption">{{ info }}</PlayerFrame>

      <div class="pane">
        <div class="tabs">
          <button class="tab" :class="{ on: tab === 'transcript' }" @click="tab = 'transcript'">{{ t("derush.transcript") }}</button>
          <button class="tab" :class="{ on: tab === 'rushes' }" @click="tab = 'rushes'">{{ t("derush.tabs.rushes", { n: project.rushes.length }) }}</button>
          <button class="tab" :class="{ on: tab === 'daryl' }" @click="tab = 'daryl'">{{ t("common.assistant") }}</button>
          <div class="spacer" />
          <span v-if="tab === 'transcript' && ready" class="hint">{{ t("derush.hint") }}</span>
        </div>
        <div class="pane-body">
          <template v-if="tab === 'transcript'">
            <Transcript v-if="ready" v-model:selection="selection" :clips="clips" :segs="segsByRush" :player="player"
              :names="names" @remove="removeSpan" />
            <div v-else-if="transcribing" class="state">
              <span class="state-label">{{ t("derush.transcribing", { p: progress }) }}</span>
              <div class="progress bar"><div :style="{ width: `${progress}%` }" /></div>
            </div>
            <div v-else-if="analysis" class="state">
              <span class="state-text">{{ t("derush.intro") }}</span>
              <button class="btn dark gen" @click="act('/rushes/transcribe')">{{ t("derush.generate") }}</button>
            </div>
          </template>
          <AutoDerush v-else-if="tab === 'daryl'" :clips="clips" :names="names" :ready="ready"
            @apply="applyAuto" @seek="seekRush" />
          <div v-else class="scroll"><RushPanel embedded @append="derush.append" /></div>
        </div>
      </div>
    </div>

    <div class="toolbar">
      <div class="group">
        <button class="btn sm" :class="{ on: tool === 'select' }" :title="`${t('derush.tools.select')} (A)`" @click="tool = 'select'">{{ t("derush.tools.select") }}</button>
        <button class="btn sm" :class="{ on: tool === 'blade' }" :title="`${t('derush.tools.blade')} (B)`" @click="tool = 'blade'">✂ {{ t("derush.tools.blade") }}</button>
      </div>
      <div class="group">
        <button class="btn sm" :title="t('derush.tools.splitKey')" @click="onSplit(player.t.value)">{{ t("derush.tools.split") }}</button>
        <button class="btn sm" :disabled="!hasSel" :title="t('derush.tools.cutKey')" @click="cutSelection">{{ t("derush.tools.cut") }}</button>
      </div>
      <div class="group">
        <button class="btn sm icon" :disabled="!derush.canUndo.value" :title="t('derush.tools.undo')" @click="derush.undo()">↶</button>
        <button class="btn sm icon" :disabled="!derush.canRedo.value" :title="t('derush.tools.redo')" @click="derush.redo()">↷</button>
      </div>
      <div v-if="ready" class="group">
        <button v-if="hasRetakes" class="btn sm" :class="{ spent: !retakes.n }" @click="cutAll(retakes, 'derush.retakes.toast')">
          {{ retakes.n ? t("derush.retakes.cut", { n: retakes.n }) : t("derush.retakes.done") }}
        </button>
        <button class="btn sm" :class="{ spent: !silences.n }" @click="cutAll(silences, 'derush.silences.toast')">{{ silLabel }}</button>
      </div>
      <div class="spacer" />
      <div class="group">
        <button class="btn sm icon" :title="t('derush.tools.zoomOut')" @click="tl?.zoomBy(1 / 1.5)">−</button>
        <button class="btn sm icon" :title="t('derush.tools.zoomIn')" @click="tl?.zoomBy(1.5)">+</button>
        <button class="btn sm" :title="`${t('derush.tools.fit')} (Maj + Z)`" @click="tl?.fit()">{{ t("derush.tools.fit") }}</button>
      </div>
    </div>

    <Timeline ref="tl" v-model:selection="selection" :clips="clips" :player="player" :names="names" :colors="colors"
      :durations="durations" :segs="segsByRush" :peaks="peaks" :tool="tool"
      @move="onMove" @trim="onTrim" @split="onSplit" />

    <div class="footer">
      <span class="keys" :title="t('derush.shortcuts')">{{ t("derush.shortcuts") }}</span>
      <span v-if="running('render')" class="render">
        {{ t("derush.rendering", { p: renderPct }) }}
        <span class="progress bar-sm"><div :style="{ width: `${renderPct}%` }" /></span>
      </span>
      <span v-else-if="failed('render')" class="render error" :title="failed('render') ?? ''">{{ t("derush.renderFailed") }}</span>
      <span v-else-if="render?.status === 'done'" class="render">
        <a :href="`${base}/derush/export.mp4`" download>derush.mp4</a>
        <template v-if="!project.runtime.render_current">{{ t("derush.cutsChanged") }}</template>
      </span>
      <div ref="menu" class="menu-wrap">
        <button class="btn md export" @click="exportOpen = !exportOpen">{{ t("derush.export.button") }}</button>
        <div v-if="exportOpen" class="menu">
          <a class="opt" :href="`${base}/derush/export.fcpxml`" download @click="exportXml">
            <span class="opt-t">{{ t("derush.export.resolve") }}</span>
            <span class="opt-d">{{ t("derush.export.resolveDesc") }}</span>
          </a>
          <a class="opt" :href="`${base}/derush/export.xml`" download @click="exportXml">
            <span class="opt-t">{{ t("derush.export.premiere") }}</span>
            <span class="opt-d">{{ t("derush.export.premiereDesc") }}</span>
          </a>
          <div class="opt" @click="exportMp4">
            <span class="opt-t">{{ t("derush.export.mp4") }}</span>
            <span class="opt-d">{{ t("derush.export.mp4Desc", { d: mmss(kept) }) }}</span>
          </div>
        </div>
      </div>
      <button v-if="ready" class="btn md red" @click="validate">{{ t("derush.validate") }}</button>
    </div>
  </div>
</template>

<style scoped>
.empty { padding: 20px 32px 32px; display: flex; flex-wrap: wrap; gap: 32px; align-items: flex-start; }
.empty .dashed-box { flex: 1 1 520px; }
.empty .side { flex: 0 1 320px; min-width: 260px; }

.derush { padding: 16px 24px 24px 32px; display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.top { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 16px; align-items: stretch; }
.pane { display: flex; flex-direction: column; min-width: 0; border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }
.tabs { display: flex; align-items: center; gap: 2px; padding: 0 10px; border-bottom: 1px solid var(--line); background: var(--bg-soft); min-height: 38px; }
.tab {
  height: 38px; padding: 0 12px; border: none; background: transparent; cursor: pointer;
  font-size: 13px; color: var(--muted); border-bottom: 2px solid transparent; margin-bottom: -1px;
}
.tab.on { color: var(--ink); font-weight: 600; border-bottom-color: var(--red); }
.tab:hover:not(.on) { color: var(--ink); }
.hint { font-size: 12px; color: var(--faint); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.pane-body { position: relative; flex: 1; min-height: 300px; }
.scroll { position: absolute; inset: 0; overflow-y: auto; padding: 12px; }

.state {
  position: absolute; inset: 16px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px;
  padding: 20px; border: 1px dashed var(--dash); border-radius: 4px; text-align: center;
}
.state-text { font-size: 14px; color: var(--muted); max-width: 440px; line-height: 1.5; text-wrap: pretty; }
.state-label { font-family: var(--mono); font-size: 12.5px; color: var(--muted); }
.progress.bar { width: 260px; }
.btn.gen { height: 38px; padding: 0 18px; font-size: 13.5px; }

.toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding-top: 4px; }
.toolbar .group { display: flex; gap: 4px; }
.btn.sm { height: 28px; padding: 0 10px; font-size: 12.5px; }
.btn.sm.icon { width: 28px; padding: 0; font-size: 14px; }
.btn.sm.on { background: var(--ink); border-color: var(--ink); color: #fff; }
.btn.sm:disabled { color: var(--off); }
.btn.sm.spent { color: var(--faint); }

.footer { display: flex; align-items: center; gap: 16px; padding-top: 2px; }
.keys { flex: 1 1 0; min-width: 0; font-size: 11.5px; color: var(--faint); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.render { display: flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 12px; color: var(--muted); }
.render.error { color: var(--red-ink); }
.progress.bar-sm { width: 80px; }
.menu-wrap { position: relative; }
.btn.export { border-color: var(--line-input); }
.btn.export:hover { border-color: var(--ink); }
.menu {
  position: absolute; right: 0; bottom: 42px; width: 300px; z-index: 10; padding: 4px;
  display: flex; flex-direction: column; background: #fff; border: 1px solid var(--line-strong);
  border-radius: 4px; box-shadow: 0 6px 20px rgba(0, 0, 0, 0.08);
}
.opt { display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; border-radius: 3px; cursor: pointer; }
.opt:hover { background: var(--bg-soft); }
a.opt, a.opt:hover { color: var(--ink); text-decoration: none; }
.opt-t { font-size: 13.5px; font-weight: 600; }
.opt-d { font-size: 12px; color: var(--muted); line-height: 1.4; }
.btn.red.md { padding: 0 16px; }
</style>
