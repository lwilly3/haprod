<script setup lang="ts">
/**
 * Onglet YouTube : un lien → aperçu (la vidéo rejoint la liste des vidéos prévisualisées) ; on y marque
 * un extrait (boutons « Début ici » / « Fin ici », I / O, clics sur la barre, puis poignées et champs
 * au dixième de seconde pour l'ajuster) ou on prend la vidéo entière, puis on la
 * télécharge dans les assets du projet ou dans les assets communs. On peut aussi n'en prendre que la vignette.
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import Seg from "../../../components/Seg.vue";
import { usePref } from "../../../lib/composables";
import { mmss, mss, mssd, parseTc } from "../../../lib/format";
import { toast } from "../../../lib/toast";
import YoutubePlayer from "./YoutubePlayer.vue";
import { act, store } from "../../store";
import type { AssetDownload } from "../../types";
import CheckBox from "./CheckBox.vue";
import DestPicker from "./DestPicker.vue";

const { t, locale } = useI18n();
const project = computed(() => store.project!);
const videos = computed(() => project.value.assets.videos);
const downloads = computed(() => project.value.runtime.assets.downloads);

// --- aperçu d'un lien
const url = ref("");
const previewing = ref(false);

async function preview() {
  if (previewing.value) return;
  if (!url.value.trim()) return toast(t("sourcing.youtube.pasteFirst"), true);
  previewing.value = true;
  const view = await act("/assets/videos", { url: url.value.trim() });
  previewing.value = false;
  if (view) {
    url.value = "";
    select(view.assets.videos[0]?.id ?? null);
  }
}

// --- vidéo sélectionnée
const selId = ref<string | null>(videos.value[0]?.id ?? null);
const video = computed(() => videos.value.find((v) => v.id === selId.value) ?? videos.value[0] ?? null);
const dur = computed(() => video.value?.duration ?? 0);
const player = ref<InstanceType<typeof YoutubePlayer>>();
const now = computed(() => player.value?.time ?? 0);

function select(id: string | null) {
  selId.value = id;
  mark.value = null;
}

function forget(id: string) {
  if (confirm(t("sourcing.youtube.confirmForget"))) act(`/assets/videos/${id}`, undefined, "DELETE");
}

const extractsOf = (vid: string) => downloads.value.filter((d) => d.video === vid);
const extracts = computed(() => (video.value ? extractsOf(video.value.id) : []));

// --- extrait ou vidéo entière
const clipMode = usePref<"clip" | "full">("assets.clipMode", "clip");
const full = computed(() => clipMode.value === "full");
const mark = ref<{ a: number; b: number | null } | null>(null);
watch(clipMode, () => (mark.value = null));
const complete = computed(() => !!mark.value && mark.value.b != null);
const canDownload = computed(() => full.value || thumb.value || complete.value);

const clipping = computed(() => !full.value && !thumb.value);
const MIN_CLIP = 0.5;
const snap = (t: number) => Math.max(0, Math.min(dur.value || Infinity, Math.round(t * 10) / 10));

/** Pose le début ; une fin déjà posée est gardée si elle reste après. */
function setStart(t: number) {
  t = snap(t);
  const b = mark.value?.b ?? null;
  mark.value = { a: t, b: b != null && b - t >= MIN_CLIP ? b : null };
}

function setEnd(time: number) {
  time = snap(time);
  const m = mark.value;
  if (!m) return toast(t("sourcing.youtube.startFirst"), true);
  if (time - m.a < MIN_CLIP) return toast(t("sourcing.youtube.endAfterStart"), true);
  mark.value = { a: m.a, b: time };
}

/** Décale une borne (champs, boutons ±) et montre l'image correspondante. */
function nudge(which: "a" | "b", delta: number) {
  const m = mark.value;
  if (!m) return;
  if (which === "a") setStart(Math.min(m.a + delta, (m.b ?? Infinity) - MIN_CLIP));
  else if (m.b != null) setEnd(Math.max(m.b + delta, m.a + MIN_CLIP));
  const t = which === "a" ? mark.value!.a : mark.value!.b;
  if (t != null) player.value?.seek(t);
}

function typed(which: "a" | "b", e: Event) {
  const input = e.target as HTMLInputElement;
  const time = parseTc(input.value);
  if (time == null) toast(t("sourcing.youtube.badTime"), true);
  else if (which === "a") setStart(time);
  else setEnd(time);
  input.value = which === "a" ? (mark.value ? mssd(mark.value.a) : "") : (mark.value?.b != null ? mssd(mark.value.b) : "");
  const v = which === "a" ? mark.value?.a : mark.value?.b;
  if (v != null) player.value?.seek(v);
}

function playClip() {
  const m = mark.value;
  if (m?.b != null) player.value?.playRange(m.a, m.b);
}

// --- barre : clic, survol, poignées
const bar = ref<HTMLElement>();
const hoverT = ref<number | null>(null);
const dragging = ref<"a" | "b" | null>(null);
let dragged = false;

function timeAt(clientX: number) {
  const r = bar.value!.getBoundingClientRect();
  return Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * dur.value;
}

/** Tant que l'extrait n'est pas complet, un clic pose le début puis la fin ; ensuite il ne fait que déplacer la lecture. */
function onBar(e: MouseEvent) {
  if (!dur.value || dragged) return void (dragged = false);
  const t = timeAt(e.clientX);
  player.value?.seek(t);
  if (!clipping.value || complete.value) return;
  const m = mark.value;
  if (!m) setStart(t);
  else if (Math.abs(t - m.a) >= MIN_CLIP) mark.value = { a: snap(Math.min(m.a, t)), b: snap(Math.max(m.a, t)) };
}

function onHover(e: MouseEvent) {
  hoverT.value = dur.value ? timeAt(e.clientX) : null;
}

function startDrag(which: "a" | "b", e: PointerEvent) {
  dragging.value = which;
  dragged = false;
  window.addEventListener("pointermove", onDrag);
  window.addEventListener("pointerup", endDrag, { once: true });
  e.preventDefault();
}

function onDrag(e: PointerEvent) {
  const m = mark.value;
  if (!m || m.b == null || !dragging.value) return;
  dragged = true;
  const t = snap(timeAt(e.clientX));
  if (dragging.value === "a") mark.value = { a: Math.min(t, m.b - MIN_CLIP), b: m.b };
  else mark.value = { a: m.a, b: Math.max(t, m.a + MIN_CLIP) };
  player.value?.seek(dragging.value === "a" ? mark.value.a : mark.value.b!);
}

function endDrag() {
  window.removeEventListener("pointermove", onDrag);
  dragging.value = null;
  // le click qui suit un glissé ne doit pas déplacer la lecture
  setTimeout(() => (dragged = false));
}

function onKey(e: KeyboardEvent) {
  if (!video.value?.yt || !clipping.value || e.ctrlKey || e.metaKey || e.altKey) return;
  if ((e.target as HTMLElement).closest("input, select, textarea")) return;
  if (e.key === "i" || e.key === "I") setStart(now.value);
  else if (e.key === "o" || e.key === "O") setEnd(now.value);
  else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
    e.preventDefault();
    const step = (e.shiftKey ? 0.1 : 1) * (e.key === "ArrowLeft" ? -1 : 1);
    player.value?.seek(Math.max(0, Math.min(dur.value, now.value + step)));
  }
}
onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => {
  window.removeEventListener("keydown", onKey);
  window.removeEventListener("pointermove", onDrag);
});

const markLabel = computed(() => {
  if (thumb.value) return t("sourcing.youtube.mark.thumb");
  if (full.value) return t("sourcing.youtube.mark.full", { d: mss(dur.value) });
  const m = mark.value;
  if (!m) return video.value?.yt ? t("sourcing.youtube.mark.hintYt") : t("sourcing.youtube.mark.hint");
  if (m.b == null) return t("sourcing.youtube.mark.start", { a: mssd(m.a) });
  return t("sourcing.youtube.mark.clip", { a: mssd(m.a), b: mssd(m.b), d: dec(m.b - m.a) });
});

/** Nombre à une décimale, au format de la langue. */
const dec = (x: number) => x.toLocaleString(locale.value, { minimumFractionDigits: 1, maximumFractionDigits: 1 });

const pct = (t: number) => `${(t / (dur.value || 1)) * 100}%`;
const width = (a: number, b: number) => `${Math.max(0.6, ((b - a) / (dur.value || 1)) * 100)}%`;

// --- options (celles de l'ancien écran YouTube)
const mode = usePref<"video" | "audio" | "thumbnail">("assets.mode", "video");
const thumb = computed(() => mode.value === "thumbnail");
const maxHeight = usePref<number | null>("assets.maxHeight", 1080);
const transcribe = usePref("assets.transcribe", false);
const precise = usePref("assets.precise", true);
const QUALITIES = [2160, 1440, 1080, 720, 480];
const qualities = computed(() => {
  const best = video.value?.heights[0];
  return best ? QUALITIES.filter((q) => q <= best) : QUALITIES;
});

// --- destination
const common = usePref("assets.ytCommon", false);
const category = usePref("assets.ytCategory", "broll");
const projectCategory = computed(() => (mode.value === "audio" ? "musique" : thumb.value ? "images" : "broll"));

async function download() {
  const v = video.value;
  if (!v || !canDownload.value) return toast(t("sourcing.youtube.placeBounds"), true);
  const clip = full.value || thumb.value ? null : { start: mark.value!.a, end: mark.value!.b! };
  const view = await act("/assets/downloads", {
    video: v.id, clip, mode: mode.value, max_height: mode.value === "audio" ? null : maxHeight.value,
    transcribe: transcribe.value, precise: precise.value,
    common: common.value, category: common.value ? category.value : projectCategory.value,
  });
  if (view) {
    mark.value = null;
    toast(t("sourcing.youtube.started", { dest: view.runtime.assets.downloads.at(-1)?.dest ?? "" }));
  }
}

function cancelOrRemove(d: AssetDownload) {
  act(`/assets/downloads/${d.id}`, undefined, "DELETE");
}

function play(d: AssetDownload) {
  if (d.start != null && d.end != null) player.value?.playRange(d.start, d.end);
}

function statusText(d: AssetDownload): string {
  switch (d.status) {
    case "queued": return t("sourcing.youtube.status.queued");
    case "running": case "probing": return t("sourcing.youtube.status.probing");
    // un extrait est lu par ffmpeg : yt-dlp ne remonte pas d'avancement
    case "downloading": return d.mode === "thumbnail" ? t("sourcing.youtube.status.downloading")
      : d.start != null ? t("sourcing.youtube.status.extracting")
      : t("sourcing.youtube.status.percent", { p: Math.round(d.progress * 100) });
    case "processing": return d.mode === "audio" ? t("sourcing.youtube.status.audio") : t("sourcing.youtube.status.merging");
    case "done": return d.transcribe ? t("sourcing.youtube.status.doneTranscribe") : t("sourcing.youtube.status.done");
    case "error": return t("sourcing.youtube.status.error", { e: d.error ?? "" });
    case "cancelled": return t("sourcing.youtube.status.cancelled");
    default: return d.status;
  }
}

const metaLine = (v: { duration: number | null; heights: number[] }, n: number) =>
  [v.duration ? mss(v.duration) : null, v.heights[0] ? `${v.heights[0]}p` : null, t("sourcing.youtube.clips", n)]
    .filter(Boolean).join(" · ");
</script>

<template>
  <div class="yt">
    <div class="url-bar">
      <input v-model="url" :placeholder="t('sourcing.youtube.urlPlaceholder')" @keydown.enter="preview">
      <button :disabled="previewing" @click="preview">{{ previewing ? t("common.loading") : t("sourcing.youtube.preview") }}</button>
      <div v-if="previewing" class="loading" />
    </div>

    <div v-if="video" class="grid">
      <div class="list">
        <span class="eyebrow">{{ t("sourcing.youtube.previewed") }}</span>
        <div v-for="v in videos" :key="v.id" class="vid" :class="{ on: v.id === video.id }" @click="select(v.id)">
          <span class="t">{{ v.title }}</span>
          <span class="mono faint m">{{ metaLine(v, extractsOf(v.id).length) }}</span>
          <button class="x-btn" :title="t('sourcing.youtube.removeFromList')" @click.stop="forget(v.id)">×</button>
        </div>
      </div>

      <div class="panel">
        <div class="head">
          <YoutubePlayer v-if="video.yt" ref="player" :key="video.yt" :video-id="video.yt" class="player" />
          <img v-else-if="video.thumbnail" :src="video.thumbnail" class="player thumb" alt="" referrerpolicy="no-referrer">
          <div v-else class="player hatch mono faint ph">{{ t("sourcing.youtube.previewPh") }}</div>
          <div class="info">
            <a class="title" :href="video.url" target="_blank" rel="noreferrer">{{ video.title }}</a>
            <span class="mono faint meta">{{ [video.uploader, video.duration ? mss(video.duration) : null].filter(Boolean).join(" · ") }}</span>
            <Seg v-if="!thumb" v-model="clipMode" :options="[['clip', t('sourcing.youtube.clipMode.clip')], ['full', t('sourcing.youtube.clipMode.full')]]" size="sm" class="seg" />
            <span class="muted mark-label">{{ markLabel }}</span>
          </div>
        </div>

        <div ref="bar" class="bar" :class="{ full, dragging }" @click="onBar" @mousemove="onHover" @mouseleave="hoverT = null">
          <div v-for="e in extracts.filter((x) => x.start != null)" :key="e.id" class="extract"
            :style="{ left: pct(e.start!), width: width(e.start!, e.end!) }" />
          <div v-if="full && !thumb" class="mark" style="left: 0; width: 100%; opacity: .25" />
          <div v-else-if="mark && !thumb" class="mark" :style="{ left: pct(mark.a), width: mark.b != null ? width(mark.a, mark.b) : '2px' }" />
          <template v-if="clipping && complete">
            <div class="handle" :style="{ left: pct(mark!.a) }" :title="t('sourcing.youtube.dragStart')" @pointerdown="startDrag('a', $event)" @click.stop />
            <div class="handle" :style="{ left: pct(mark!.b!) }" :title="t('sourcing.youtube.dragEnd')" @pointerdown="startDrag('b', $event)" @click.stop />
          </template>
          <div v-if="video.yt" class="head-line" :style="{ left: pct(now) }" />
          <span v-if="hoverT != null && !dragging" class="hover-t mono" :style="{ left: pct(hoverT) }">{{ mssd(hoverT) }}</span>
        </div>

        <div v-if="clipping" class="clip-ctl">
          <div v-for="w in (['a', 'b'] as const)" :key="w" class="bound">
            <span class="eyebrow">{{ w === "a" ? t("sourcing.youtube.start") : t("sourcing.youtube.end") }}</span>
            <input class="mono tc" :value="w === 'a' ? (mark ? mssd(mark.a) : '') : (mark?.b != null ? mssd(mark.b) : '')"
              :disabled="w === 'b' && !mark" placeholder="—" @change="typed(w, $event)" @keydown.enter="($event.target as HTMLInputElement).blur()">
            <div class="nudges">
              <button v-for="d in [-1, -0.1, 0.1, 1]" :key="d" class="btn sm" :disabled="!mark || (w === 'b' && mark.b == null)"
                @click="nudge(w, d)">{{ d > 0 ? "+" : "−" }}{{ Math.abs(d) === 1 ? "1" : dec(0.1) }}</button>
            </div>
            <button v-if="video.yt" class="btn sm dark" @click="w === 'a' ? setStart(now) : setEnd(now)">
              {{ w === "a" ? t("sourcing.youtube.startHere") : t("sourcing.youtube.endHere") }}
            </button>
          </div>
          <button v-if="video.yt" class="btn sm" :disabled="!complete" @click="playClip">{{ t("sourcing.youtube.replay") }}</button>
          <span v-if="video.yt" class="faint keys">{{ t("sourcing.youtube.keys") }}</span>
        </div>

        <div class="options">
          <Seg v-model="mode" :options="[['video', t('sourcing.youtube.modes.video')], ['audio', t('sourcing.youtube.modes.audio')], ['thumbnail', t('sourcing.youtube.modes.thumbnail')]]" size="sm" />
          <select v-if="mode === 'video'" v-model="maxHeight" class="select" :title="t('sourcing.youtube.maxRes')">
            <option :value="null">{{ t("sourcing.youtube.bestQuality") }}</option>
            <option v-for="q in qualities" :key="q" :value="q">{{ t("sourcing.youtube.qualityMax", { q }) }}</option>
          </select>
          <CheckBox v-if="!thumb" v-model="transcribe">{{ t("sourcing.youtube.transcribe") }}</CheckBox>
          <CheckBox v-if="!full && !thumb" v-model="precise">{{ t("sourcing.youtube.precise") }}</CheckBox>
        </div>

        <div class="actions">
          <DestPicker v-model:common="common" v-model:category="category" :project-category="projectCategory" />
          <span class="spacer" />
          <button v-if="mark && !full && !thumb" class="btn md" @click="mark = null">{{ t("common.cancel") }}</button>
          <button class="btn red md" :disabled="!canDownload" @click="download">
            {{ thumb ? t("sourcing.youtube.downloadThumb") : full ? t("sourcing.youtube.downloadVideo") : t("sourcing.youtube.downloadClip") }}
          </button>
        </div>

        <div v-if="extracts.length" class="done-list">
          <span class="eyebrow">{{ t("sourcing.youtube.downloaded") }}</span>
          <div v-for="(e, i) in extracts" :key="e.id" class="row">
            <span class="n">{{ e.mode === "thumbnail" ? t("sourcing.youtube.rowThumb") : e.start == null ? t("sourcing.youtube.rowFull") : t("sourcing.youtube.rowClip", { n: i + 1 }) }}</span>
            <button v-if="e.start != null" class="mono range" :disabled="!video.yt" :title="t('sourcing.youtube.replayTitle')" @click="play(e)">
              {{ mmss(e.start) }} → {{ mmss(e.end) }}
            </button>
            <span v-else class="mono range">{{ e.mode === "thumbnail" ? "" : mss(video.duration) }}</span>
            <span class="mono faint">{{ e.mode === "thumbnail" ? "jpg" : e.mode === "audio" ? "audio" : e.start != null ? `${Math.round(e.end! - e.start)} s` : "" }}</span>
            <span class="status" :class="{ err: e.status === 'error' }" :title="e.name ?? ''">{{ statusText(e) }}</span>
            <span class="dest muted">{{ e.dest }}</span>
            <button class="x-btn" :title="e.finished ? t('sourcing.youtube.removeKeepFile') : t('common.cancel')" @click="cancelOrRemove(e)">×</button>
            <div v-if="!e.finished && e.status === 'downloading' && e.start == null && e.mode !== 'thumbnail'" class="progress red row-progress">
              <div :style="{ width: `${Math.round(e.progress * 100)}%` }" />
            </div>
          </div>
        </div>
      </div>
    </div>
    <div v-else class="dashed-box empty muted">{{ t("sourcing.youtube.empty") }}</div>
  </div>
</template>

<style scoped>
.yt { display: flex; flex-direction: column; gap: 22px; }
.url-bar { position: relative; display: flex; height: 46px; border: 1px solid var(--line-input); border-radius: 4px; overflow: hidden; }
.url-bar input { flex: 1; min-width: 0; border: none; padding: 0 14px; font-family: var(--mono); font-size: 13.5px; }
.url-bar button { min-width: 150px; padding: 0 20px; border: none; border-left: 1px solid var(--line-input); background: #fff; font-size: 14px; font-weight: 500; cursor: pointer; }
.url-bar button:disabled { color: var(--faint); cursor: default; }
.loading { position: absolute; left: 0; bottom: 0; height: 2px; width: 30%; background: var(--red); animation: slide 1.1s ease-in-out infinite; }
@keyframes slide { from { left: -30%; } to { left: 100%; } }
.grid { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 24px; align-items: start; }
.list { display: flex; flex-direction: column; gap: 8px; }
.vid { position: relative; display: flex; flex-direction: column; gap: 2px; padding: 10px 26px 10px 12px; border: 1px solid var(--line); border-radius: 4px; cursor: pointer; }
.vid.on { border-color: var(--ink); }
.vid .t { font-size: 13.5px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.vid .m { font-size: 11px; }
.vid .x-btn { position: absolute; top: 8px; right: 6px; visibility: hidden; }
.vid:hover .x-btn { visibility: visible; }
.panel { display: flex; flex-direction: column; gap: 14px; padding: 16px; border: 1px solid var(--line); border-radius: 4px; min-width: 0; }
.head { display: flex; gap: 16px; flex-wrap: wrap; }
.player { width: 400px; max-width: 100%; flex-shrink: 0; aspect-ratio: 16/9; border-radius: 0; }
.thumb { object-fit: cover; background: #000; }
.ph { display: flex; align-items: center; justify-content: center; font-size: 11px; }
.info { display: flex; flex-direction: column; gap: 6px; min-width: 0; flex: 1 1 220px; }
.info .title { font-size: 16px; font-weight: 600; color: var(--ink); }
.meta { font-size: 12px; }
.seg { margin-top: 10px; }
.mark-label { font-size: 13px; margin-top: 4px; }
.bar { position: relative; height: 34px; background: var(--line-soft); cursor: crosshair; }
.bar.full { cursor: pointer; }
.extract { position: absolute; top: 0; bottom: 0; background: var(--red); opacity: .55; }
.mark { position: absolute; top: -3px; bottom: -3px; background: var(--ink); opacity: .85; }
.head-line { position: absolute; top: -4px; bottom: -4px; width: 2px; margin-left: -1px; background: var(--red); pointer-events: none; }
.bar.dragging, .bar.dragging .handle { cursor: ew-resize; }
.handle { position: absolute; top: -7px; bottom: -7px; width: 14px; margin-left: -7px; cursor: ew-resize; touch-action: none; z-index: 1; }
.handle::after { content: ""; position: absolute; left: 4px; right: 4px; top: 0; bottom: 0; background: var(--ink); border: 1px solid #fff; border-radius: 3px; }
.hover-t { position: absolute; bottom: calc(100% + 8px); transform: translateX(-50%); padding: 2px 6px; border-radius: 3px; background: var(--ink); color: #fff; font-size: 11px; white-space: nowrap; pointer-events: none; z-index: 2; }
.clip-ctl { display: flex; align-items: center; gap: 10px 22px; flex-wrap: wrap; }
.bound { display: flex; align-items: center; gap: 8px; }
.tc { width: 76px; height: 28px; border: 1px solid var(--line-strong); border-radius: 4px; padding: 0 8px; font-size: 13px; }
.nudges { display: flex; }
.nudges .btn { padding: 0 7px; border-radius: 0; margin-left: -1px; }
.nudges .btn:first-child { border-radius: 4px 0 0 4px; margin-left: 0; }
.nudges .btn:last-child { border-radius: 0 4px 4px 0; }
.keys { font-size: 12px; }
.options { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.select { height: 30px; border: 1px solid var(--line-strong); border-radius: 4px; background: #fff; font-size: 13px; padding: 0 6px; cursor: pointer; }
.actions { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; padding-top: 12px; border-top: 1px solid var(--line-soft); }
.done-list { display: flex; flex-direction: column; }
.done-list .eyebrow { padding-bottom: 6px; }
.row { display: grid; grid-template-columns: 110px 150px 56px minmax(0, 1fr) auto 20px; gap: 8px; align-items: center; font-size: 13px; padding: 7px 0; border-top: 1px solid var(--bg-soft); }
.row .n { font-weight: 500; }
.range { font-size: 12px; border: none; background: none; padding: 0; text-align: left; color: var(--ink); cursor: pointer; }
.range:disabled { cursor: default; }
.row .mono.faint { font-size: 12px; }
.status { font-size: 12.5px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.status.err { color: var(--red-ink); }
.dest { font-size: 12.5px; text-align: right; white-space: nowrap; }
.row-progress { grid-column: 1 / -1; }
.empty { padding: 40px 20px; text-align: center; font-size: 13px; }
</style>
