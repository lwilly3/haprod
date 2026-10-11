<script setup lang="ts">
/**
 * La timeline du montage, façon DaVinci Resolve : Ctrl + molette zoome autour de la tête de lecture, la molette
 * fait défiler, Maj + Z ajuste à la fenêtre. On glisse les éléments, on tire leurs bords pour les
 * rogner (avec aimantation), la lame coupe ; glisser sur une zone vide sélectionne une plage.
 * Seule la partie visible est dessinée : vignettes et forme d'onde suivent le zoom.
 * Un média glissé depuis l'inspecteur s'insère dans l'A-roll s'il est lâché sur sa piste, sinon il se pose au-dessus.
 * Les beats du storyboard pas encore faits (en pointillés sur leur piste) se glissent et se tirent aussi :
 * leurs bords s'aimantent aux mots (le début un peu avant un mot, la fin un peu après).
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { fxName } from "../../../lib/transitions";
import { MEDIA_DRAG, trimAroll } from "./ops";
import {
  clipStarts, clone, fxMax, type AvailableMedia, fxSpan, prevJoined, spanOf, type Broll, type FxEnd, type Motion, type MontageView, type Selection, type Timeline,
  type Track,
} from "./types";

const props = defineProps<{
  tl: Timeline; total: number; t: number; tool: "select" | "blade";
  sourceDuration: number; analysis: MontageView["analysis"]; peaks: number[] | null;
  media: MontageView["media"]; motions: MontageView["motions"]; playing: boolean;
  /** les beats du storyboard, en pointillés sur leur piste (motion, zooms ou B-roll), à leur couleur */
  ghosts?: { id: string; at: number; dur: number; label: string; on: boolean; track: "motion" | "zooms" | "broll"; color: string }[];
  /** le beat sélectionné */
  beatSel?: string | null;
  /** les mots de la timeline [début, fin], et l'avance / la traîne d'un beat sur ses mots */
  words?: [number, number][]; lead?: number; tail?: number;
}>();
const emit = defineEmits<{
  seek: [number]; edit: [(t: Timeline) => void]; commit: []; hold: [boolean]; blade: [Track, string, number];
  /** un beat cliqué ; déplacé ou tiré (début, durée), puis lâché */
  ghost: [string]; beat: [string, number, number]; beatCommit: [];
  /** un média lâché à l'instant t : dans l'A-roll (aroll), ou au-dessus */
  drop: [AvailableMedia, number, boolean];
}>();
const sel = defineModel<Selection | null>("selection", { required: true });
const { t: tr } = useI18n();

const LABEL_W = 92;
const ROWS = [
  { key: "chapters", h: 22 },
  { key: "texts", h: 24 },
  { key: "motion", h: 30 },
  { key: "zooms", h: 22 },
  { key: "broll", h: 34 },
  { key: "aroll", h: 52 },
  { key: "voice", h: 38 },
  { key: "music", h: 24 },
  { key: "sfx", h: 24 },
] as const;
type RowKey = (typeof ROWS)[number]["key"];
const rowH = Object.fromEntries(ROWS.map((r) => [r.key, r.h])) as Record<RowKey, number>;
const RULER = 22;
const tops = (() => {
  let y = RULER;
  return Object.fromEntries(ROWS.map((r) => { const o = y; y += r.h + 2; return [r.key, o]; })) as Record<RowKey, number>;
})();
const height = RULER + ROWS.reduce((n, r) => n + r.h + 2, 0);

// --- zoom et défilement
const scroller = ref<HTMLElement>();
const viewW = ref(800);
const scrollX = ref(0);
const pps = ref(4);
const minPps = computed(() => Math.max(0.02, (viewW.value - 40) / Math.max(props.total, 1)));
const MAX_PPS = 600;
const width = computed(() => Math.max(props.total * pps.value + 80, viewW.value));
const x = (sec: number) => sec * pps.value;
const v0 = computed(() => scrollX.value / pps.value - 2);
const v1 = computed(() => (scrollX.value + viewW.value) / pps.value + 2);
const visible = (a: number, b: number) => b >= v0.value && a <= v1.value;

function setZoom(next: number, anchor: number, anchorPx: number) {
  pps.value = Math.min(MAX_PPS, Math.max(minPps.value, next));
  nextTick(() => {
    if (scroller.value) scroller.value.scrollLeft = Math.max(0, anchor * pps.value - anchorPx);
  });
}
// la tête de lecture garde sa place à l'écran ; hors champ, on la ramène au centre
function zoomBy(factor: number, anchor = props.t) {
  const px = x(anchor) - scrollX.value;
  setZoom(pps.value * factor, anchor, px >= 0 && px <= viewW.value ? px : viewW.value / 2);
}
function fit() {
  setZoom(minPps.value, 0, 0);
}
defineExpose({ zoomBy, fit });

function onWheel(e: WheelEvent) {
  if (e.ctrlKey || e.metaKey) {
    e.preventDefault();
    zoomBy(Math.pow(1.0015, -e.deltaY));
  } else if (!e.shiftKey && Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
    e.preventDefault();
    scroller.value!.scrollLeft += e.deltaY;
  }
}

const ro = new ResizeObserver(([entry]) => { viewW.value = entry.contentRect.width; });
onMounted(() => {
  ro.observe(scroller.value!);
  viewW.value = scroller.value!.clientWidth;
  fit();
});
onUnmounted(() => ro.disconnect());
watch(() => props.total, (n, old) => { if (!old && n) nextTick(fit); else if (pps.value < minPps.value) pps.value = minPps.value; });

// la lecture reste visible : on tourne la page quand la tête sort de l'écran
watch(() => props.t, (t) => {
  const el = scroller.value;
  if (!el || !props.playing) return;
  const px = x(t);
  if (px > scrollX.value + viewW.value - 30 || px < scrollX.value) el.scrollLeft = Math.max(0, px - 60);
});

// --- règle
const STEPS = [0.04, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1200];
const ticks = computed(() => {
  const step = STEPS.find((s) => s * pps.value >= 70) ?? 1200;
  const minor = STEPS.slice().reverse().find((s) => s < step && s * pps.value >= 10) ?? step;
  const out: { t: number; major: boolean }[] = [];
  const first = Math.max(0, Math.floor(v0.value / minor) * minor);
  for (let t = first; t <= Math.min(v1.value, props.total + minor); t += minor) {
    const r = Math.round(t * 1000) / 1000;
    out.push({ t: r, major: Math.abs(r / step - Math.round(r / step)) < 1e-6 });
  }
  return { out, step };
});
function label(t: number, step: number) {
  const m = Math.floor(t / 60), s = t - m * 60;
  return step < 1 ? `${m}:${s.toFixed(step < 0.1 ? 2 : 1).padStart(step < 0.1 ? 5 : 4, "0")}` : `${m}:${String(Math.round(s)).padStart(2, "0")}`;
}

// --- éléments affichés
const starts = computed(() => clipStarts(props.tl));
const isSel = (track: Track, id: string) => !!sel.value && "item" in sel.value && sel.value.item.track === track
  && sel.value.item.id === id && !sel.value.item.fx;
const range = computed(() => (sel.value && "range" in sel.value ? sel.value.range : null));

const arollV = computed(() => props.tl.aroll.map((c, i) => ({ c, a: starts.value[i], b: starts.value[i] + c.out - c.in }))
  .filter((v) => visible(v.a, v.b)));
const itemsV = <T extends { id: string; at: number }>(list: T[], end: (x: T) => number) =>
  list.map((it) => ({ it, a: it.at, b: it.at + end(it) })).filter((v) => visible(v.a, v.b));
const zoomsV = computed(() => itemsV(props.tl.zooms, (z) => z.dur));
const brollV = computed(() => itemsV(props.tl.broll, (b) => b.out - b.in));
const motionV = computed(() => itemsV(props.tl.motion, (m) => m.dur));
const textsV = computed(() => itemsV(props.tl.texts, (x) => x.dur));
const ghostsV = computed(() => itemsV(props.ghosts ?? [], (g) => g.dur));
const musicV = computed(() => itemsV(props.tl.audio.filter((s) => s.role === "music"), (s) => s.out - s.in));
const sfxV = computed(() => itemsV(props.tl.audio.filter((s) => s.role === "sfx"), (s) => s.out - s.in));
const chaptersV = computed(() => {
  const ch = props.tl.markers.filter((m) => m.kind === "chapter");
  return ch.map((m, i) => ({ m, a: m.t, b: ch[i + 1]?.t ?? props.total })).filter((v) => visible(v.a, v.b));
});
// les transitions : sur la moitié basse de leur piste, pour laisser les bords des plans à portée de souris
type FxTrack = "aroll" | "broll" | "motion";
const fxV = computed(() => {
  const out: { track: FxTrack; id: string; fx: FxEnd; name: string; a: number; b: number; centered: boolean }[] = [];
  const add = (track: FxTrack, id: string, fx: FxEnd, name: string, centered: boolean) => {
    const span = fxSpan(props.tl, track, id, fx, props.sourceDuration);
    if (span && visible(span[0], span[1])) out.push({ track, id, fx, name, a: span[0], b: span[1], centered });
  };
  for (const c of props.tl.aroll) if (c.transition) add("aroll", c.id, "transition", c.transition.fx, true);
  for (const track of ["broll", "motion"] as const) {
    for (const it of props.tl[track] as (Broll | Motion)[]) {
      if (it.enter) add(track, it.id, "enter", it.enter.fx, !!prevJoined(props.tl, track, it.id));
      if (it.exit) add(track, it.id, "exit", it.exit.fx, false);
    }
  }
  return out;
});
function fxBox(track: FxTrack) {
  const h = ROWS.find((r) => r.key === track)!.h;
  return { top: tops[track] + Math.round(h / 2), height: Math.floor(h / 2) - 1 };
}
const isFxSel = (track: Track, id: string, fx: FxEnd) => !!sel.value && "item" in sel.value
  && sel.value.item.track === track && sel.value.item.id === id && sel.value.item.fx === fx;

const nameOf = (src: string) => props.media[src]?.name ?? src.split("/").pop() ?? src;

// --- vignettes de la vidéo source, sur chaque clip
const TILE_H = 44;
const tiles = computed(() => {
  const fs = props.analysis.filmstrip;
  if (!fs) return [];
  const tileW = (fs.width * TILE_H) / fs.height;
  const out: { key: string; left: number; w: number; pos: string }[] = [];
  for (const { c, a, b } of arollV.value) {
    // un clip inséré d'un autre média n'a pas de vignettes
    if (c.src) continue;
    const first = Math.max(0, Math.floor((x(v0.value) - x(a)) / tileW));
    const last = Math.min(Math.ceil((x(b) - x(a)) / tileW), Math.ceil((x(v1.value) - x(a)) / tileW));
    for (let k = first; k < last; k++) {
      const left = x(a) + k * tileW;
      const src = c.in + (k * tileW + tileW / 2) / pps.value;
      const idx = Math.floor(src / fs.step);
      const col = idx % fs.cols, row = Math.floor(idx / fs.cols);
      out.push({ key: `${c.id}-${k}`, left, w: Math.min(tileW, x(b) - left), pos: `-${col * tileW}px -${row * TILE_H}px` });
    }
  }
  return out;
});
const tileSize = computed(() => {
  const fs = props.analysis.filmstrip;
  return fs ? `${(fs.cols * fs.width * TILE_H) / fs.height}px auto` : "";
});

// --- forme d'onde de la voix (A-roll), dessinée pour la partie visible
const canvas = ref<HTMLCanvasElement>();
function drawWave() {
  const cv = canvas.value, peaks = props.peaks;
  if (!cv) return;
  const dpr = window.devicePixelRatio || 1;
  const w = viewW.value, h = rowH.voice;
  cv.width = w * dpr;
  cv.height = h * dpr;
  const g = cv.getContext("2d")!;
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  if (!peaks) return;
  const rate = props.analysis.peaks_rate;
  g.fillStyle = "#3E9E6E";
  const s = starts.value;
  let ci = 0;
  for (let px = 0; px < w; px++) {
    const t = (scrollX.value + px) / pps.value;
    if (t >= props.total) break;
    while (ci < props.tl.aroll.length - 1 && t >= s[ci] + props.tl.aroll[ci].out - props.tl.aroll[ci].in) ci++;
    while (ci > 0 && t < s[ci]) ci--;
    const c = props.tl.aroll[ci];
    if (!c) break;
    // un clip inséré d'un autre média : pas de forme d'onde de la source
    if (c.src) continue;
    const a = c.in + (t - s[ci]), b = a + 1 / pps.value;
    let peak = 0;
    for (let i = Math.floor(a * rate); i <= Math.floor(b * rate) && i < peaks.length; i++) peak = Math.max(peak, peaks[i]);
    const ph = Math.max(1, (peak / 100) * (h - 4));
    g.fillRect(px, (h - ph) / 2, 1, ph);
  }
}
let raf = 0;
function redraw() {
  cancelAnimationFrame(raf);
  raf = requestAnimationFrame(drawWave);
}
watch([() => props.peaks, pps, scrollX, viewW, () => props.tl.aroll, () => props.total], redraw, { deep: true });
onMounted(redraw);

// --- souris : sélectionner, déplacer, rogner, couper, plage
const timeAt = (e: PointerEvent | MouseEvent) => {
  const rect = scroller.value!.getBoundingClientRect();
  return Math.max(0, Math.min(props.total, (e.clientX - rect.left + scrollX.value) / pps.value));
};

/** Les points d'accroche : tête de lecture, coupes, bords des autres éléments, marqueurs. */
function snapPoints(except: string): number[] {
  const pts = [0, props.total, props.t, ...starts.value];
  for (const track of ["zooms", "broll", "motion", "audio", "texts"] as const) {
    for (const it of props.tl[track] as { id: string }[]) {
      if (it.id === except) continue;
      const span = spanOf(props.tl, track, it.id);
      if (span) pts.push(span[0], span[1]);
    }
  }
  for (const m of props.tl.markers) if (m.id !== except) pts.push(m.t);
  return pts;
}
function snap(value: number, pts: number[]): number {
  const tol = 8 / pps.value;
  let best = value, d = tol;
  for (const p of pts) if (Math.abs(p - value) < d) { d = Math.abs(p - value); best = p; }
  return best;
}

type Mode = "move" | "left" | "right";
// un beat du storyboard tiré : ses bords s'aimantent aux mots, en plus des points d'accroche habituels
let ghostDrag: { id: string; mode: Mode; t0: number; at: number; dur: number; starts: number[]; ends: number[]; moved: boolean } | null = null;

function downGhost(e: PointerEvent, g: { id: string; at: number; dur: number }, mode: Mode = "move") {
  if (e.button !== 0) return;
  e.stopPropagation();
  sel.value = null;
  emit("ghost", g.id);
  if (props.tool === "blade") return;
  const pts = snapPoints(g.id), words = props.words ?? [];
  const lead = props.lead ?? 0, tail = props.tail ?? 0;
  ghostDrag = {
    id: g.id, mode, t0: timeAt(e), at: g.at, dur: g.dur, moved: false,
    starts: [...pts, ...words.map((w) => Math.max(0, w[0] - lead))], ends: [...pts, ...words.map((w) => w[1] + tail)],
  };
  (e.target as HTMLElement).setPointerCapture(e.pointerId);
}
const MIN_BEAT = 0.3;
function applyGhost(d: NonNullable<typeof ghostDrag>, t: number) {
  const dt = t - d.t0;
  let at = d.at, end = d.at + d.dur;
  if (d.mode === "move") {
    const a = snap(d.at + dt, d.starts), b = snap(d.at + d.dur + dt, d.ends) - d.dur;
    at = Math.abs(a - (d.at + dt)) <= Math.abs(b - (d.at + dt)) ? a : b;
    at = Math.max(0, Math.min(props.total - d.dur, at));
    end = at + d.dur;
  } else if (d.mode === "left") {
    at = Math.max(0, Math.min(snap(d.at + dt, d.starts), end - MIN_BEAT));
  } else {
    end = Math.min(props.total, Math.max(snap(d.at + d.dur + dt, d.ends), at + MIN_BEAT));
  }
  emit("beat", d.id, round(at), round(end - at));
}

let drag: { track: Track; id: string; mode: Mode; t0: number; origin: Timeline; pts: number[]; moved: boolean; fx?: FxEnd } | null = null;
let rangeDrag: { a: number } | null = null;
let scrub = false;

function down(e: PointerEvent, track: Track, id: string, mode: Mode = "move") {
  if (e.button !== 0) return;
  e.stopPropagation();
  const t = timeAt(e);
  if (props.tool === "blade") {
    emit("blade", track, id, snap(t, [props.t]));
    return;
  }
  sel.value = { item: { track, id } };
  drag = { track, id, mode, t0: t, origin: clone(props.tl), pts: snapPoints(id), moved: false };
  emit("hold", true);
  (e.target as HTMLElement).setPointerCapture(e.pointerId);
}

/** Une transition : clic = la sélectionner ; tirer ses bords = changer sa durée. */
function downFx(e: PointerEvent, track: Track, id: string, fx: FxEnd, mode: Mode = "move") {
  if (e.button !== 0) return;
  e.stopPropagation();
  sel.value = { item: { track, id, fx } };
  if (mode === "move") return;
  drag = { track, id, mode, t0: timeAt(e), origin: clone(props.tl), pts: [], moved: false, fx };
  emit("hold", true);
  (e.target as HTMLElement).setPointerCapture(e.pointerId);
}

const FX_DUR: [number, number] = [0.2, 2];
/** La durée d'une transition dont on tire un bord jusqu'à t (au pas de 0,05 s). */
function applyFx(tl: Timeline, d: NonNullable<typeof drag>, t: number) {
  const span = fxSpan(d.origin, d.track, d.id, d.fx!);
  if (!span) return;
  const centered = d.fx === "transition" || (d.fx === "enter" && !!prevJoined(d.origin, d.track as "broll" | "motion", d.id));
  let dur = centered ? 2 * Math.abs(t - (span[0] + span[1]) / 2) : d.fx === "enter" ? t - span[0] : span[1] - t;
  // au pas de 0,05 s, sans dépasser ce que le rendu peut jouer
  const max = Math.min(FX_DUR[1], Math.floor(fxMax(d.origin, d.track, d.id, d.fx!, props.sourceDuration) * 20) / 20);
  dur = Math.round(Math.max(FX_DUR[0], Math.min(max, dur)) * 20) / 20;
  if (d.fx === "transition") {
    const c = tl.aroll.find((k) => k.id === d.id);
    if (c?.transition) c.transition = { ...c.transition, dur };
  } else {
    const it = (tl[d.track] as (Broll | Motion)[]).find((k) => k.id === d.id), key = d.fx as "enter" | "exit";
    if (it?.[key]) it[key] = { ...it[key]!, dur };
  }
}

function apply(tl: Timeline, d: NonNullable<typeof drag>, t: number) {
  if (d.fx) return applyFx(tl, d, t);
  const dt = t - d.t0;
  if (d.track === "aroll") {
    const o = d.origin.aroll.find((c) => c.id === d.id)!;
    const limit = o.src ? props.media[o.src]?.duration ?? Infinity : props.sourceDuration;
    if (d.mode === "left") trimAroll(tl, d.id, "in", o.in + dt, limit);
    else if (d.mode === "right") trimAroll(tl, d.id, "out", o.out + dt, limit);
    return;
  }
  if (d.track === "markers") {
    const m = tl.markers.find((k) => k.id === d.id)!, o = d.origin.markers.find((k) => k.id === d.id)!;
    m.t = round(Math.max(0, Math.min(props.total, snap(o.t + dt, d.pts))));
    return;
  }
  const list = tl[d.track] as { id: string; at: number; dur?: number; in?: number; out?: number }[];
  const it = list.find((k) => k.id === d.id)!;
  const o = (d.origin[d.track] as typeof list).find((k) => k.id === d.id)!;
  const len = o.dur ?? (o.out! - o.in!);
  const limit = "src" in o ? props.media[(o as { src: string }).src]?.duration ?? Infinity : Infinity;
  if (d.mode === "move") {
    let at = o.at + dt;
    const snapA = snap(at, d.pts), snapB = snap(at + len, d.pts) - len;
    at = Math.abs(snapA - at) <= Math.abs(snapB - at) ? snapA : snapB;
    it.at = round(Math.max(0, Math.min(props.total - 0.1, at)));
  } else if (d.mode === "left") {
    let at = snap(o.at + dt, d.pts);
    at = Math.min(at, o.at + len - 0.1);
    if (o.in != null) at = Math.max(at, o.at - o.in);
    at = Math.max(0, at);
    const shift = at - o.at;
    it.at = round(at);
    if (o.dur != null) it.dur = round(o.dur - shift);
    else it.in = round(o.in! + shift);
  } else {
    let end = snap(o.at + len + dt, d.pts);
    end = Math.max(end, o.at + 0.1);
    if (o.dur != null) it.dur = round(end - o.at);
    else it.out = round(Math.min(limit, o.in! + end - o.at));
  }
}

function move(e: PointerEvent) {
  lastMove = e;
  dragTo(e);
  if (!edgeRaf) edgeRaf = requestAnimationFrame(edgeScroll);
}

// près d'un bord pendant un glissé, la timeline défile d'autant plus vite qu'on s'en approche
const EDGE = 40;
let lastMove: PointerEvent | null = null;
let edgeRaf = 0;
function edgeScroll() {
  edgeRaf = 0;
  const el = scroller.value, e = lastMove;
  if (!el || !e || !(drag || ghostDrag || rangeDrag || scrub)) return;
  const left = el.getBoundingClientRect().left, right = left + el.clientWidth;
  const over = e.clientX < left + EDGE ? e.clientX - left - EDGE : e.clientX > right - EDGE ? e.clientX - right + EDGE : 0;
  if (!over) return;
  const before = el.scrollLeft;
  el.scrollLeft = before + Math.sign(over) * Math.min(40, 2 + Math.abs(over) * 0.4);
  if (el.scrollLeft === before) return;
  scrollX.value = el.scrollLeft;
  dragTo(e);
  edgeRaf = requestAnimationFrame(edgeScroll);
}

function dragTo(e: PointerEvent) {
  if (ghostDrag) {
    const t = timeAt(e);
    if (!ghostDrag.moved && Math.abs(t - ghostDrag.t0) * pps.value < 3) return;
    ghostDrag.moved = true;
    applyGhost(ghostDrag, t);
  } else if (drag) {
    const t = timeAt(e);
    if (!drag.moved && Math.abs(t - drag.t0) * pps.value < 3) return;
    drag.moved = true;
    const d = drag;
    emit("edit", (tl) => { Object.assign(tl, clone(d.origin)); apply(tl, d, t); });
  } else if (rangeDrag) {
    const t = timeAt(e);
    const a = Math.min(rangeDrag.a, t), b = Math.max(rangeDrag.a, t);
    sel.value = b - a > 0.05 ? { range: [round(a), round(b)] } : null;
  } else if (scrub) {
    emit("seek", timeAt(e));
  }
}

function up() {
  if (ghostDrag?.moved) emit("beatCommit");
  else if (ghostDrag) emit("seek", ghostDrag.at + 0.05);
  ghostDrag = null;
  if (drag) {
    emit("hold", false);
    if (drag.moved) emit("commit");
  }
  drag = null;
  rangeDrag = null;
  scrub = false;
  lastMove = null;
  cancelAnimationFrame(edgeRaf);
  edgeRaf = 0;
}

/** Zone vide : clic = tête de lecture, glisser = plage. */
function downEmpty(e: PointerEvent) {
  if (e.button !== 0) return;
  const t = timeAt(e);
  if (props.tool === "blade") {
    emit("blade", "aroll", "", snap(t, [props.t]));
    return;
  }
  sel.value = null;
  emit("seek", t);
  rangeDrag = { a: t };
  (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
}

function downRuler(e: PointerEvent) {
  if (e.button !== 0) return;
  e.stopPropagation();
  if (e.shiftKey) {
    rangeDrag = { a: timeAt(e) };
  } else {
    scrub = true;
    emit("seek", timeAt(e));
  }
  (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
}

// --- un média glissé depuis l'inspecteur : un trait montre où il arrive (aimanté aux coupes et à la tête)
const dropAt = ref<{ t: number; aroll: boolean } | null>(null);
function dropTarget(e: DragEvent) {
  const rect = scroller.value!.getBoundingClientRect();
  const y = e.clientY - rect.top;
  const aroll = y >= tops.aroll && y < tops.aroll + rowH.aroll;
  const t = timeAt(e);
  return { t: aroll ? snap(t, [props.t, ...starts.value, props.total]) : snap(t, snapPoints("")), aroll };
}
function dragOver(e: DragEvent) {
  if (!e.dataTransfer?.types.includes(MEDIA_DRAG)) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = "copy";
  dropAt.value = dropTarget(e);
}
function dropMedia(e: DragEvent) {
  const raw = e.dataTransfer?.getData(MEDIA_DRAG);
  dropAt.value = null;
  if (!raw) return;
  e.preventDefault();
  const { t, aroll } = dropTarget(e);
  emit("drop", JSON.parse(raw) as AvailableMedia, round(t), aroll);
}

const round = (n: number) => Math.round(n * 1000) / 1000;

/** Double-clic sur un élément : la tête de lecture se place à son début. */
function goTo(t: number) {
  if (props.tool === "select") emit("seek", t);
}

function motionState(id: string) {
  const s = props.motions[id];
  if (!s) return "";
  if (s.render === "ready") return "";
  if (s.render === "none") return tr("editing.timeline.toWrite");
  if (s.render === "error") return tr("editing.timeline.renderFailed");
  if (s.render === "rendering") return tr("editing.timeline.rendering", { pct: Math.round(s.progress * 100) });
  return tr("editing.timeline.renderPending");
}
</script>

<template>
  <div class="tl" :class="{ blade: tool === 'blade' }">
    <div class="labels" :style="{ width: `${LABEL_W}px`, height: `${height}px` }">
      <div class="corner" :style="{ height: `${RULER}px` }" />
      <div v-for="r in ROWS" :key="r.key" class="lab" :style="{ top: `${tops[r.key]}px`, height: `${r.h}px` }">{{ tr(`editing.lanes.${r.key}`) }}</div>
    </div>
    <div ref="scroller" class="scroller" :style="{ height: `${height + 12}px` }"
      @wheel="onWheel" @scroll="scrollX = ($event.target as HTMLElement).scrollLeft">
      <div class="content" :style="{ width: `${width}px`, height: `${height}px` }"
        @pointerdown="downEmpty" @pointermove="move" @pointerup="up" @pointercancel="up"
        @dragover="dragOver" @dragleave="dropAt = null" @drop="dropMedia">
        <!-- règle -->
        <div class="ruler" :style="{ height: `${RULER}px` }" @pointerdown="downRuler">
          <template v-for="k in ticks.out" :key="k.t">
            <span class="tick" :class="{ major: k.major }" :style="{ left: `${x(k.t)}px` }" />
            <span v-if="k.major" class="tlabel mono" :style="{ left: `${x(k.t) + 3}px` }">{{ label(k.t, ticks.step) }}</span>
          </template>
        </div>

        <!-- fonds des pistes -->
        <div v-for="r in ROWS" :key="r.key" class="lane" :class="r.key" :style="{ top: `${tops[r.key]}px`, height: `${r.h}px`, width: `${x(total)}px` }" />

        <!-- chapitres -->
        <div v-for="v in chaptersV" :key="v.m.id" class="chapter" :class="{ on: isSel('markers', v.m.id) }"
          :style="{ top: `${tops.chapters}px`, height: `${rowH.chapters}px`, left: `${x(v.a)}px`, width: `${x(v.b - v.a)}px` }"
          :title="v.m.text" @pointerdown="down($event, 'markers', v.m.id)" @dblclick="goTo(v.a)">
          <span>{{ v.m.text || tr("editing.timeline.chapter") }}</span>
        </div>

        <!-- storyboard : les beats proposés, sur leur piste -->
        <div v-for="v in ghostsV" :key="`g-${v.it.id}`" class="ghost" :class="{ off: !v.it.on, on: beatSel === v.it.id }"
          :style="{ top: `${tops[v.it.track] + 2}px`, height: `${ROWS.find((r) => r.key === v.it.track)!.h - 4}px`, left: `${x(v.a)}px`,
                    width: `${Math.max(3, x(v.b - v.a))}px`, '--c': v.it.color }"
          :title="v.it.label" @pointerdown="downGhost($event, v.it)">
          <i class="edge l" @pointerdown="downGhost($event, v.it, 'left')" />
          <span>{{ v.it.label }}</span>
          <i class="edge r" @pointerdown="downGhost($event, v.it, 'right')" />
        </div>

        <!-- textes écrits à la main -->
        <div v-for="v in textsV" :key="v.it.id" class="item text" :class="{ on: isSel('texts', v.it.id), empty: !v.it.text.trim() }"
          :style="{ top: `${tops.texts + 2}px`, height: `${rowH.texts - 4}px`, left: `${x(v.a)}px`, width: `${Math.max(3, x(v.b - v.a))}px` }"
          :title="v.it.text" @pointerdown="down($event, 'texts', v.it.id)" @dblclick="goTo(v.a)">
          <i class="edge l" @pointerdown="down($event, 'texts', v.it.id, 'left')" />
          <span>{{ v.it.text.trim() || tr("editing.timeline.emptyText") }}</span>
          <i class="edge r" @pointerdown="down($event, 'texts', v.it.id, 'right')" />
        </div>

        <!-- motion design -->
        <div v-for="v in motionV" :key="v.it.id" class="item motion" :class="{ on: isSel('motion', v.it.id), pending: !!motionState(v.it.id) }"
          :style="{ top: `${tops.motion + 2}px`, height: `${rowH.motion - 4}px`, left: `${x(v.a)}px`, width: `${Math.max(3, x(v.b - v.a))}px` }"
          :title="`${v.it.title}${motionState(v.it.id) ? ` · ${motionState(v.it.id)}` : ''}`" @pointerdown="down($event, 'motion', v.it.id)" @dblclick="goTo(v.a)">
          <i class="edge l" @pointerdown="down($event, 'motion', v.it.id, 'left')" />
          <span>{{ v.it.title || v.it.id }}</span><small v-if="motionState(v.it.id)">{{ motionState(v.it.id) }}</small>
          <i class="edge r" @pointerdown="down($event, 'motion', v.it.id, 'right')" />
        </div>

        <!-- zooms -->
        <div v-for="v in zoomsV" :key="v.it.id" class="item zoom" :class="{ on: isSel('zooms', v.it.id) }"
          :style="{ top: `${tops.zooms + 2}px`, height: `${rowH.zooms - 4}px`, left: `${x(v.a)}px`, width: `${Math.max(3, x(v.b - v.a))}px` }"
          :title="`Zoom ×${v.it.scale}`" @pointerdown="down($event, 'zooms', v.it.id)" @dblclick="goTo(v.a)">
          <i class="edge l" @pointerdown="down($event, 'zooms', v.it.id, 'left')" />
          <span>×{{ v.it.scale.toFixed(2) }}</span>
          <i class="edge r" @pointerdown="down($event, 'zooms', v.it.id, 'right')" />
        </div>

        <!-- B-roll -->
        <div v-for="v in brollV" :key="v.it.id" class="item broll" :class="{ on: isSel('broll', v.it.id) }"
          :style="{ top: `${tops.broll + 2}px`, height: `${rowH.broll - 4}px`, left: `${x(v.a)}px`, width: `${Math.max(3, x(v.b - v.a))}px` }"
          :title="nameOf(v.it.src)" @pointerdown="down($event, 'broll', v.it.id)" @dblclick="goTo(v.a)">
          <i class="edge l" @pointerdown="down($event, 'broll', v.it.id, 'left')" />
          <span>{{ nameOf(v.it.src) }}</span>
          <i class="edge r" @pointerdown="down($event, 'broll', v.it.id, 'right')" />
        </div>

        <!-- A-roll : la vidéo source, avec ses vignettes -->
        <div v-for="v in arollV" :key="v.c.id" class="clip" :class="{ on: isSel('aroll', v.c.id), ext: !!v.c.src }"
          :style="{ top: `${tops.aroll}px`, height: `${rowH.aroll}px`, left: `${x(v.a)}px`, width: `${x(v.b - v.a)}px` }"
          :title="v.c.src ? nameOf(v.c.src) : undefined" @pointerdown="down($event, 'aroll', v.c.id)" @dblclick="goTo(v.a)">
          <span v-if="v.c.src">{{ nameOf(v.c.src) }}</span>
          <i class="edge l" @pointerdown="down($event, 'aroll', v.c.id, 'left')" />
          <i class="edge r" @pointerdown="down($event, 'aroll', v.c.id, 'right')" />
        </div>
        <div class="strip" :style="{ top: `${tops.aroll + 4}px` }">
          <span v-for="k in tiles" :key="k.key" class="tile"
            :style="{ left: `${k.left}px`, width: `${k.w}px`, height: `${TILE_H}px`, backgroundImage: `url(${analysis.filmstrip!.url})`, backgroundPosition: k.pos, backgroundSize: tileSize }" />
        </div>
        <!-- le volume d'un clip réglé, au-dessus de ses vignettes -->
        <template v-for="v in arollV" :key="`g-${v.c.id}`">
          <b v-if="v.c.gain_db" class="gain mono" :style="{ top: `${tops.aroll + rowH.aroll - 16}px`, left: `${x(v.b) - 4}px` }">
            {{ v.c.gain_db > 0 ? "+" : "" }}{{ v.c.gain_db }} dB
          </b>
        </template>
        <span v-if="!analysis.filmstrip && analysis.pending" class="pending-media mono" :style="{ top: `${tops.aroll + 18}px`, left: `${scrollX + 8}px` }">
          {{ tr("editing.timeline.thumbsPending") }}
        </span>

        <!-- transitions : au-dessus des plans ; tirer un bord change la durée -->
        <div v-for="f in fxV" :key="`${f.id}-${f.fx}`" class="fx" :class="{ on: isFxSel(f.track, f.id, f.fx) }"
          :style="{ top: `${fxBox(f.track).top}px`, height: `${fxBox(f.track).height}px`, left: `${x(f.a)}px`, width: `${Math.max(8, x(f.b - f.a))}px` }"
          :title="`${fxName(f.name)} · ${(f.b - f.a).toFixed(2).replace('.', ',')} s`" @pointerdown="downFx($event, f.track, f.id, f.fx)" @dblclick="goTo(f.a)">
          <i v-if="f.centered || f.fx === 'exit'" class="edge l" @pointerdown="downFx($event, f.track, f.id, f.fx, 'left')" />
          <span v-if="x(f.b - f.a) > 46">{{ fxName(f.name) }}</span>
          <i v-if="f.centered || f.fx === 'enter'" class="edge r" @pointerdown="downFx($event, f.track, f.id, f.fx, 'right')" />
        </div>

        <!-- voix -->
        <canvas ref="canvas" class="wave" :style="{ top: `${tops.voice}px`, left: `${scrollX}px`, width: `${viewW}px`, height: `${rowH.voice}px` }" />

        <!-- musique et sons -->
        <div v-for="v in musicV" :key="v.it.id" class="item music" :class="{ on: isSel('audio', v.it.id) }"
          :style="{ top: `${tops.music + 2}px`, height: `${rowH.music - 4}px`, left: `${x(v.a)}px`, width: `${Math.max(3, x(v.b - v.a))}px` }"
          :title="`${nameOf(v.it.src)} · ${v.it.gain_db} dB`" @pointerdown="down($event, 'audio', v.it.id)" @dblclick="goTo(v.a)">
          <i class="edge l" @pointerdown="down($event, 'audio', v.it.id, 'left')" />
          <span>{{ nameOf(v.it.src) }}</span>
          <i class="edge r" @pointerdown="down($event, 'audio', v.it.id, 'right')" />
        </div>
        <div v-for="v in sfxV" :key="v.it.id" class="item sfx" :class="{ on: isSel('audio', v.it.id) }"
          :style="{ top: `${tops.sfx + 2}px`, height: `${rowH.sfx - 4}px`, left: `${x(v.a)}px`, width: `${Math.max(4, x(v.b - v.a))}px` }"
          :title="`${nameOf(v.it.src)} · ${v.it.gain_db} dB`" @pointerdown="down($event, 'audio', v.it.id)" @dblclick="goTo(v.a)">
          <i class="edge l" @pointerdown="down($event, 'audio', v.it.id, 'left')" />
          <span>{{ nameOf(v.it.src) }}</span>
          <i class="edge r" @pointerdown="down($event, 'audio', v.it.id, 'right')" />
        </div>

        <!-- plage sélectionnée, tête de lecture -->
        <div v-if="range" class="range" :style="{ left: `${x(range[0])}px`, width: `${x(range[1] - range[0])}px`, top: `${RULER}px`, height: `${height - RULER}px` }" />
        <div v-if="range" class="range-bar" :style="{ left: `${x(range[0])}px`, width: `${x(range[1] - range[0])}px`, height: `${RULER}px` }" />
        <div class="head" :style="{ left: `${x(t)}px`, height: `${height}px` }"><i /></div>
        <div v-if="dropAt" class="drop" :class="{ aroll: dropAt.aroll }" :style="{ left: `${x(dropAt.t)}px`, top: `${RULER}px`, height: `${height - RULER}px` }" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.tl { display: flex; border: 1px solid var(--line); border-radius: 4px; background: #fff; user-select: none; overflow: hidden; }
.tl.blade .content { cursor: crosshair; }
.labels { position: relative; flex-shrink: 0; border-right: 1px solid var(--line); background: var(--bg-soft); }
.corner { border-bottom: 1px solid var(--line); }
.lab { position: absolute; left: 0; right: 0; display: flex; align-items: center; padding: 0 10px; font-size: 11.5px; color: var(--muted); }
.scroller { flex: 1; min-width: 0; overflow-x: auto; overflow-y: hidden; position: relative; }
.content { position: relative; }

.ruler { position: absolute; top: 0; left: 0; width: 100%; border-bottom: 1px solid var(--line); cursor: ew-resize; background: #fff; z-index: 3; }
.tick { position: absolute; bottom: 0; width: 1px; height: 5px; background: var(--dash); }
.tick.major { height: 10px; background: var(--faint); }
.tlabel { position: absolute; top: 2px; font-size: 10px; color: var(--faint); white-space: nowrap; pointer-events: none; }

.lane { position: absolute; left: 0; background: var(--bg-softer); border-radius: 2px; }
.lane.aroll, .lane.voice { background: #F1F1EE; }

.item, .chapter, .clip {
  position: absolute; box-sizing: border-box; overflow: hidden; white-space: nowrap; cursor: grab;
  display: flex; align-items: center; gap: 4px; font-size: 10.5px; border-radius: 3px; z-index: 1;
}
.item span, .chapter span { overflow: hidden; text-overflow: ellipsis; padding: 0 6px; pointer-events: none; }
.item small { font-size: 9.5px; opacity: .8; padding-right: 6px; pointer-events: none; }
.item.on, .clip.on, .chapter.on { outline: 2px solid var(--red); outline-offset: -1px; z-index: 2; }

.chapter { border-left: 2px solid var(--ink-3); color: var(--ink-3); font-weight: 600; background: transparent; border-radius: 0; }
.ghost {
  position: absolute; box-sizing: border-box; overflow: hidden; white-space: nowrap; display: flex; align-items: center;
  font-size: 10.5px; border: 1.5px dashed var(--c); border-radius: 3px; background: color-mix(in srgb, var(--c) 8%, transparent);
  color: color-mix(in srgb, var(--c) 70%, #000); cursor: grab; z-index: 1;
}
.ghost.off { border-color: var(--line-strong); color: var(--off); background: transparent; }
.ghost.on { border-style: solid; outline: 2px solid var(--red); outline-offset: -1px; z-index: 2; }
.ghost .edge:hover { background: color-mix(in srgb, var(--c) 35%, transparent); }
.ghost span { overflow: hidden; text-overflow: ellipsis; padding: 0 6px; pointer-events: none; }
.item.text { background: #F4E9C8; color: var(--ink); font-family: "Ink Free", "Segoe Print", cursive; font-size: 12px; border: 1px solid #D8C68E; }
.item.text.empty { color: var(--faint); font-style: italic; }
.item.motion { background: #7C5CE0; color: #fff; font-weight: 600; }
.item.motion.pending { background: repeating-linear-gradient(135deg, #9C84EA 0 6px, #8A70E5 6px 12px); }
.item.zoom { background: #E8B02F; color: var(--ink); font-weight: 600; }
.item.broll { background: #3B82C4; color: #fff; }
.item.music { background: #2F9E83; color: #fff; }
.item.sfx { background: #D9663B; color: #fff; }
.clip { background: #2B2C2E; border-right: 1px solid #fff; }
/* sélectionné, le clip passe au-dessus des vignettes : il ne garde que son contour pour ne pas les masquer */
.clip.on { background: transparent; }
/* un clip inséré d'un autre média (extrait, archive) : sans vignettes, avec son nom */
.clip.ext { background: repeating-linear-gradient(135deg, #8A4FBF 0 8px, #7D45B0 8px 16px); color: #fff; }
.clip.ext span { overflow: hidden; text-overflow: ellipsis; padding: 0 8px; pointer-events: none; font-weight: 600; }
.gain { position: absolute; transform: translateX(-100%); z-index: 2; white-space: nowrap; font-size: 9.5px; font-weight: 600; color: #fff;
  background: rgba(0, 0, 0, .55); border-radius: 2px; padding: 0 4px; pointer-events: none; }
.clip.ext.on { background: repeating-linear-gradient(135deg, #8A4FBF 0 8px, #7D45B0 8px 16px); }
.strip { position: absolute; left: 0; height: 0; pointer-events: none; z-index: 1; }
.tile { position: absolute; top: 0; background-repeat: no-repeat; opacity: .92; }
.pending-media { position: absolute; font-size: 10.5px; color: var(--off); z-index: 2; pointer-events: none; }
.wave { position: absolute; pointer-events: none; }

/* une transition : un bloc hachuré sur la moitié basse de sa piste */
.fx {
  position: absolute; z-index: 4; display: flex; align-items: center; justify-content: center; overflow: hidden;
  border: 1px solid rgba(29, 30, 32, .55); border-radius: 3px; cursor: pointer; color: #1d1e20;
  background: repeating-linear-gradient(135deg, #F4F1E8 0 5px, #DCD6C6 5px 10px);
  font-size: 10.5px; font-weight: 600; white-space: nowrap;
}
.fx span { padding: 0 6px; overflow: hidden; text-overflow: ellipsis; pointer-events: none; }
.fx.on { border-color: var(--red); box-shadow: 0 0 0 1.5px var(--red); }
.edge { position: absolute; top: 0; bottom: 0; width: 6px; cursor: ew-resize; z-index: 3; }
.edge.l { left: 0; }
.edge.r { right: 0; }
.blade .edge { cursor: crosshair; }
.clip .edge:hover, .item .edge:hover { background: rgba(229, 72, 77, .5); }

.range { position: absolute; background: rgba(229, 72, 77, .08); border-left: 1px solid var(--red); border-right: 1px solid var(--red); pointer-events: none; z-index: 2; }
.range-bar { position: absolute; top: 0; background: rgba(229, 72, 77, .25); pointer-events: none; z-index: 4; }
.drop { position: absolute; width: 2px; margin-left: -1px; background: #3B82C4; pointer-events: none; z-index: 6; }
.drop.aroll { width: 3px; background: #8A4FBF; }
.head { position: absolute; top: 0; width: 1px; margin-left: -0.5px; background: var(--red); pointer-events: none; z-index: 5; }
.head i { position: absolute; top: 0; left: -5px; width: 11px; height: 10px; background: var(--red); clip-path: polygon(0 0, 100% 0, 50% 100%); }
</style>
