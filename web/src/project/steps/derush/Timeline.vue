<script setup lang="ts">
/**
 * La timeline du dérush, façon logiciel de montage : des bouts de rushes bout à bout (V1) et leur son (A1).
 * On attrape un bout pour le déplacer, on tire ses bords pour le rogner ou le rallonger (aimanté aux
 * phrases et aux mots, Alt pour s'en passer), la lame le coupe en deux. Glisser sur A1 sélectionne une plage.
 * Alt + molette zoome sur la tête de lecture, Ctrl + molette la déplace (elle reste au milieu de l'écran, comme dans
 * Filmora ; la molette seule fait défiler la page). Tirée sur la règle, la tête s'aimante aux coupes (Alt : sans aimant).
 * Dans chaque bout, une bande marque
 * la parole (les trous sont des silences, les pointillés du son non transcrit) ; zoomé, le texte des phrases s'affiche.
 * Une timeline imbriquée est un seul bloc (double-clic : on l'ouvre). On y dépose rushes et timelines de la médiathèque.
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { mmss } from "../../../lib/format";
import type { DerushClip, DerushSeg, TimelineClip } from "../../types";
import { clipLen, offsets, type Selection } from "./clips";
import { MEDIA_TYPE, type MediaItem } from "./useDerush";
import type { Playlist } from "./usePlaylist";

export interface Peaks { rate: number; peaks: number[] }

const props = defineProps<{
  /** les bouts de la timeline (rushes et timelines imbriquées) ; `flat` : les bouts de rushes qu'elle lit */
  clips: TimelineClip[]; flat: DerushClip[]; player: Playlist; names: Record<string, string>; colors: Record<string, string>;
  durations: Record<string, number>; segs: Record<string, DerushSeg[]>; peaks: Record<string, Peaks | undefined>;
  tool: "select" | "blade";
}>();
const emit = defineEmits<{
  move: [ids: string[], before: string | null];
  trim: [id: string, side: "in" | "out", value: number];
  split: [t: number];
  insert: [items: MediaItem[], before: string | null];
  open: [tl: string];
}>();
const sel = defineModel<Selection>("selection", { required: true });
const { t: tr } = useI18n();

const LABEL_W = 44, RULER = 22, V = 64, A = 48, GAP = 2;
const top = { v: RULER + GAP, a: RULER + V + GAP * 2 };
const height = RULER + V + A + GAP * 2;

const starts = computed(() => offsets(props.clips));
const total = computed(() => props.clips.reduce((a, c) => a + clipLen(c), 0));

// --- zoom et défilement
const scroller = ref<HTMLElement>();
const viewW = ref(800);
const scrollX = ref(0);
const pps = ref(4);
const minPps = computed(() => Math.max(0.01, (viewW.value - 40) / Math.max(total.value, 1)));
const MAX_PPS = 800;
const width = computed(() => Math.max(total.value * pps.value + 200, viewW.value));
const x = (sec: number) => sec * pps.value;
const v0 = computed(() => scrollX.value / pps.value - 2);
const v1 = computed(() => (scrollX.value + viewW.value) / pps.value + 2);
const headX = computed(() => x(props.player.t.value));

function setZoom(next: number, anchor: number, anchorPx: number) {
  pps.value = Math.min(MAX_PPS, Math.max(minPps.value, next));
  nextTick(() => {
    if (scroller.value) scroller.value.scrollLeft = Math.max(0, anchor * pps.value - anchorPx);
  });
}
// comme dans Filmora : on zoome sur la tête de lecture, qui reste au milieu de l'écran (près d'un bout de la
// timeline, elle s'en écarte le temps qu'il faut)
function zoomBy(factor: number) {
  setZoom(pps.value * factor, props.player.t.value, viewW.value / 2);
}
function fit() {
  setZoom(minPps.value, 0, 0);
}
defineExpose({ zoomBy, fit });

function onWheel(e: WheelEvent) {
  // la molette seule fait défiler la page
  if (e.altKey) {
    e.preventDefault();
    zoomBy(Math.pow(1.0015, -e.deltaY));
  } else if ((e.ctrlKey || e.metaKey) && Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
    // on se déplace avec la tête de lecture, qui reste au milieu de l'écran
    e.preventDefault();
    const t = Math.max(0, Math.min(props.player.t.value + e.deltaY / pps.value, total.value));
    props.player.seek(t);
    scroller.value!.scrollLeft = Math.max(0, x(t) - viewW.value / 2);
  }
}

const ro = new ResizeObserver(([entry]) => { viewW.value = entry.contentRect.width; });
onMounted(() => {
  ro.observe(scroller.value!);
  viewW.value = scroller.value!.clientWidth;
  fit();
});
onUnmounted(() => ro.disconnect());
watch(total, (n, old) => { if (!old && n) nextTick(fit); else if (pps.value < minPps.value) pps.value = minPps.value; });

// la tête reste visible : en lecture on tourne la page quand elle sort de l'écran ; un saut (flèches, bout
// suivant, ±1 s…) hors de l'écran la ramène au centre
watch(headX, (px) => {
  const el = scroller.value;
  if (!el || drag) return;
  if (px <= scrollX.value + viewW.value - 30 && px >= scrollX.value) return;
  el.scrollLeft = Math.max(0, props.player.playing.value ? px - 60 : px - viewW.value / 2);
});

// --- règle
const STEPS = [0.04, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1200];
const ticks = computed(() => {
  const step = STEPS.find((s) => s * pps.value >= 70) ?? 1200;
  const minor = STEPS.slice().reverse().find((s) => s < step && s * pps.value >= 10) ?? step;
  const out: { t: number; major: boolean }[] = [];
  const first = Math.max(0, Math.floor(v0.value / minor) * minor);
  for (let t = first; t <= Math.min(v1.value, total.value + minor); t += minor) {
    const r = Math.round(t * 1000) / 1000;
    out.push({ t: r, major: Math.abs(r / step - Math.round(r / step)) < 1e-6 });
  }
  return { out, step };
});
function label(t: number, step: number) {
  const m = Math.floor(t / 60), s = t - m * 60;
  return step < 1 ? `${m}:${s.toFixed(step < 0.1 ? 2 : 1).padStart(step < 0.1 ? 5 : 4, "0")}` : `${m}:${String(Math.round(s)).padStart(2, "0")}`;
}

// --- bouts affichés, avec leur bande de parole
const selIds = computed(() => new Set(sel.value && "clips" in sel.value ? sel.value.clips : []));
const range = computed(() => (sel.value && "range" in sel.value ? sel.value.range : null));

interface Mark { key: string; left: number; w: number; type: DerushSeg["type"] | "voice"; text: string }
const clipsV = computed(() => props.clips.map((c, i) => {
  const a = starts.value[i], b = a + clipLen(c);
  return { c, i, a, b };
}).filter((k) => k.b >= v0.value && k.a <= v1.value).map((k) => {
  const marks: Mark[] = [];
  for (const s of props.segs[k.c.rush ?? ""] ?? []) {
    if (s.type === "sil" || s.end <= k.c.in || s.start >= k.c.out) continue;
    const sa = k.a + Math.max(s.start, k.c.in) - k.c.in, sb = k.a + Math.min(s.end, k.c.out) - k.c.in;
    if (sb < v0.value || sa > v1.value) continue;
    marks.push({ key: s.key, left: x(sa - k.a), w: Math.max(1, x(sb - sa)), type: s.words.length ? s.type : "voice", text: s.text });
  }
  return { ...k, marks };
}));

// --- forme d'onde, dessinée pour la partie visible
const canvas = ref<HTMLCanvasElement>();
function drawWave() {
  const cv = canvas.value;
  if (!cv) return;
  const dpr = window.devicePixelRatio || 1;
  const w = viewW.value, h = A;
  cv.width = w * dpr;
  cv.height = h * dpr;
  const g = cv.getContext("2d")!;
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  g.fillStyle = "#3E9E6E";
  const cs = props.flat, o = offsets(cs);
  let i = 0;
  for (let px = 0; px < w; px++) {
    const d = (scrollX.value + px) / pps.value;
    if (d >= total.value) break;
    while (i < cs.length - 1 && o[i] + clipLen(cs[i]) <= d) i++;
    const c = cs[i], pk = c && props.peaks[c.rush];
    if (!pk) continue;
    const t0 = c.in + (d - o[i]), t1 = t0 + 1 / pps.value;
    let peak = 0;
    for (let k = Math.floor(t0 * pk.rate); k <= Math.floor(t1 * pk.rate) && k < pk.peaks.length; k++) peak = Math.max(peak, pk.peaks[k]);
    const ph = Math.max(1, (peak / 100) * (h - 6));
    g.fillRect(px, (h - ph) / 2, 1, ph);
  }
}
let raf = 0;
function redraw() {
  cancelAnimationFrame(raf);
  raf = requestAnimationFrame(drawWave);
}
watch([() => props.peaks, pps, scrollX, viewW, () => props.flat], redraw);
onMounted(redraw);

// --- souris
const timeAt = (e: PointerEvent | MouseEvent) => {
  const rect = scroller.value!.getBoundingClientRect();
  return Math.max(0, Math.min(total.value, (e.clientX - rect.left + scrollX.value) / pps.value));
};

type Drag =
  | { kind: "scrub"; pts: number[] }
  | { kind: "range"; a: number; moved: boolean }
  | { kind: "clip"; id: string; d0: number; moved: boolean; additive: boolean }
  | { kind: "trim"; i: number; side: "in" | "out"; edge: number; d0: number; to: number; pts: number[]; min: number; max: number };
let drag: Drag | null = null;
const ghost = ref<{ x0: number; x1: number; delta: number; grow: boolean } | null>(null);
const moving = ref<{ ids: string[]; dx: number; before: string | null; at: number } | null>(null);

function capture(e: PointerEvent) {
  (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
}

function downRuler(e: PointerEvent) {
  if (e.button !== 0) return;
  e.stopPropagation();
  // la tête tirée sur la règle s'aimante aux coupes (sans sa propre position, où elle resterait collée)
  drag = { kind: "scrub", pts: [0, total.value, ...starts.value].filter((p) => p !== props.player.t.value) };
  props.player.seek(e.altKey ? timeAt(e) : snap(timeAt(e), drag.pts));
  capture(e);
}

/** Fond et piste A1 : clic = tête de lecture, glisser = plage ; avec la lame, coupe. */
function downTrack(e: PointerEvent) {
  if (e.button !== 0) return;
  const t = timeAt(e);
  if (props.tool === "blade") {
    emit("split", t);
    return;
  }
  props.player.seek(t);
  drag = { kind: "range", a: t, moved: false };
  capture(e);
}

function downClip(e: PointerEvent, id: string) {
  if (e.button !== 0) return;
  e.stopPropagation();
  const t = timeAt(e);
  if (props.tool === "blade") {
    emit("split", t);
    return;
  }
  drag = { kind: "clip", id, d0: t, moved: false, additive: e.ctrlKey || e.metaKey || e.shiftKey };
  capture(e);
}

function downEdge(e: PointerEvent, i: number, side: "in" | "out") {
  if (e.button !== 0 || props.tool === "blade") return;
  e.stopPropagation();
  const c = props.clips[i], pts: number[] = [];
  for (const s of props.segs[c.rush ?? ""] ?? []) {
    pts.push(s.start, s.end);
    for (const w of s.words) pts.push(w[0], w[1]);
  }
  const dur = props.durations[c.rush ?? c.tl ?? ""] ?? c.out;
  const edge = side === "in" ? c.in : c.out;
  drag = { kind: "trim", i, side, edge, d0: timeAt(e), to: edge, pts,
    min: side === "in" ? 0 : c.in + 0.05, max: side === "in" ? c.out - 0.05 : dur };
  capture(e);
}

function snap(value: number, pts: number[]) {
  const tol = 8 / pps.value;
  let best = value, dist = tol;
  for (const p of pts) if (Math.abs(p - value) < dist) { dist = Math.abs(p - value); best = p; }
  return best;
}

function onMove(e: PointerEvent) {
  if (!drag) return;
  const d = timeAt(e);
  if (drag.kind === "scrub") {
    props.player.seek(e.altKey ? d : snap(d, drag.pts));
  } else if (drag.kind === "range") {
    if (!drag.moved && Math.abs(d - drag.a) * pps.value < 4) return;
    drag.moved = true;
    sel.value = { range: [Math.min(drag.a, d), Math.max(drag.a, d)] };
  } else if (drag.kind === "clip") {
    if (!drag.moved && Math.abs(d - drag.d0) * pps.value < 4) return;
    if (!drag.moved) {
      drag.moved = true;
      if (!selIds.value.has(drag.id)) sel.value = { clips: [drag.id] };
    }
    const ids = [...selIds.value], dx = d - drag.d0;
    // la place visée : avant le premier bout (non déplacé) dont le milieu est après la souris
    const rest = props.clips.map((c, i) => ({ c, a: starts.value[i], b: starts.value[i] + clipLen(c) })).filter((k) => !ids.includes(k.c.id));
    const next = rest.find((k) => (k.a + k.b) / 2 > d);
    moving.value = { ids, dx, before: next?.c.id ?? null, at: next ? next.a : rest.length ? rest[rest.length - 1].b : 0 };
  } else if (drag.kind === "trim") {
    let to = drag.edge + (d - drag.d0);
    if (!e.altKey) to = snap(to, drag.pts);
    to = Math.round(Math.max(drag.min, Math.min(drag.max, to)) * 1000) / 1000;
    drag.to = to;
    const a = starts.value[drag.i], c = props.clips[drag.i];
    const ex = x(drag.side === "in" ? a : a + clipLen(c));
    const delta = to - drag.edge, nx = ex + x(delta);
    ghost.value = { x0: Math.min(ex, nx), x1: Math.max(ex, nx), delta, grow: drag.side === "in" ? delta < 0 : delta > 0 };
  }
}

function onUp() {
  const d = drag;
  drag = null;
  if (d?.kind === "range" && !d.moved) sel.value = null;
  else if (d?.kind === "clip") {
    if (!d.moved) {
      // simple clic : sélection du bout (Ctrl / Maj : ajouté à la sélection) et tête de lecture
      const ids = d.additive ? [...selIds.value] : [];
      const at = ids.indexOf(d.id);
      if (at >= 0) ids.splice(at, 1); else ids.push(d.id);
      sel.value = ids.length ? { clips: ids } : null;
      props.player.seek(d.d0);
    } else if (moving.value) {
      const m = moving.value;
      moving.value = null;
      emit("move", m.ids, m.before);
    }
  } else if (d?.kind === "trim") {
    ghost.value = null;
    if (Math.abs(d.to - d.edge) > 1e-3) emit("trim", props.clips[d.i].id, d.side, d.to);
  }
}

// --- dépôt depuis la médiathèque : avant le bout dont le milieu est après la souris
const dropAt = ref<{ before: string | null; at: number } | null>(null);
function placeAt(e: DragEvent) {
  const d = timeAt(e), k = props.clips.findIndex((c, i) => starts.value[i] + clipLen(c) / 2 > d);
  return k < 0 ? { before: null, at: total.value } : { before: props.clips[k].id, at: starts.value[k] };
}
function onDragOver(e: DragEvent) {
  if (!e.dataTransfer?.types.includes(MEDIA_TYPE)) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = "copy";
  dropAt.value = placeAt(e);
}
function onDrop(e: DragEvent) {
  const raw = e.dataTransfer?.getData(MEDIA_TYPE);
  dropAt.value = null;
  if (!raw) return;
  e.preventDefault();
  emit("insert", JSON.parse(raw) as MediaItem[], placeAt(e).before);
}

const fmtDelta = (s: number) => `${s > 0 ? "+" : "−"}${Math.abs(s).toFixed(2)} s`;
const shortName = (n: string) => n.replace(/\.[^.]+$/, "");
</script>

<template>
  <div class="tl" :class="{ blade: tool === 'blade' }">
    <div class="labels" :style="{ width: `${LABEL_W}px`, height: `${height}px` }">
      <div class="corner" :style="{ height: `${RULER}px` }" />
      <div class="lab" :style="{ top: `${top.v}px`, height: `${V}px` }">V1</div>
      <div class="lab" :style="{ top: `${top.a}px`, height: `${A}px` }">A1</div>
    </div>
    <div ref="scroller" class="scroller" :style="{ height: `${height + 12}px` }"
      @wheel="onWheel" @scroll="scrollX = ($event.target as HTMLElement).scrollLeft"
      @dragover="onDragOver" @dragleave="dropAt = null" @drop="onDrop">
      <div class="content" :style="{ width: `${width}px`, height: `${height}px` }"
        @pointerdown="downTrack" @pointermove="onMove" @pointerup="onUp" @pointercancel="onUp">
        <!-- règle -->
        <div class="ruler" :style="{ height: `${RULER}px` }" @pointerdown="downRuler">
          <template v-for="k in ticks.out" :key="k.t">
            <span class="tick" :class="{ major: k.major }" :style="{ left: `${x(k.t)}px` }" />
            <span v-if="k.major" class="tlabel mono" :style="{ left: `${x(k.t) + 3}px` }">{{ label(k.t, ticks.step) }}</span>
          </template>
        </div>

        <div class="lane" :style="{ top: `${top.v}px`, height: `${V}px`, width: `${Math.max(x(total), 4)}px` }" />
        <div class="lane" :style="{ top: `${top.a}px`, height: `${A}px`, width: `${Math.max(x(total), 4)}px` }" />

        <!-- bouts de rushes -->
        <div v-for="k in clipsV" :key="k.c.id" class="clip"
          :class="{ on: selIds.has(k.c.id), moving: moving?.ids.includes(k.c.id), nested: !!k.c.tl }"
          :style="{ top: `${top.v}px`, height: `${V}px`, left: `${x(k.a)}px`, width: `${Math.max(2, x(k.b - k.a))}px`,
                    background: k.c.tl ? undefined : colors[k.c.rush!], transform: moving?.ids.includes(k.c.id) ? `translateX(${x(moving.dx)}px)` : '' }"
          :title="k.c.tl ? tr('derush.timeline.nested', { name: names[k.c.tl] }) : `${names[k.c.rush!]} · ${mmss(k.c.in)} → ${mmss(k.c.out)}`"
          @pointerdown="downClip($event, k.c.id)"
          @dblclick="tool !== 'blade' && (k.c.tl ? emit('open', k.c.tl) : player.seek(k.a))">
          <span v-if="x(k.b - k.a) > 24" class="name">
            <template v-if="k.c.tl">⧉ {{ names[k.c.tl] }}</template>
            <template v-else>{{ shortName(names[k.c.rush!] ?? k.c.rush) }}</template>
            <small> {{ mmss(k.c.in) }}</small>
          </span>
          <span v-for="m in k.marks" :key="m.key" class="mark" :class="m.type" :style="{ left: `${m.left}px`, width: `${m.w}px` }">
            <em v-if="m.w > 50">{{ m.text }}</em>
          </span>
          <i class="edge l" :title="tr('derush.timeline.trim')" @pointerdown="downEdge($event, k.i, 'in')" />
          <i class="edge r" :title="tr('derush.timeline.trim')" @pointerdown="downEdge($event, k.i, 'out')" />
        </div>
        <div v-if="dropAt" class="drop-at" :style="{ left: `${x(dropAt.at)}px`, top: `${top.v - 2}px`, height: `${V + A + GAP + 4}px` }" />
        <div v-if="moving" class="drop-at" :style="{ left: `${x(moving.at)}px`, top: `${top.v - 2}px`, height: `${V + A + GAP + 4}px` }" />

        <canvas ref="canvas" class="wave" :style="{ top: `${top.a}px`, left: `${scrollX}px`, width: `${viewW}px`, height: `${A}px` }" />

        <!-- rognage en cours -->
        <template v-if="ghost">
          <div class="ghost" :class="{ grow: ghost.grow }" :style="{ left: `${ghost.x0}px`, width: `${Math.max(1, ghost.x1 - ghost.x0)}px`, top: `${top.v}px`, height: `${V + GAP + A}px` }" />
          <span class="ghost-tip mono" :style="{ left: `${ghost.x1 + 6}px`, top: `${top.v + 4}px` }">{{ fmtDelta(ghost.delta) }}</span>
        </template>

        <!-- plage sélectionnée, tête de lecture -->
        <div v-if="range" class="range" :style="{ left: `${x(range[0])}px`, width: `${x(range[1] - range[0])}px`, top: `${RULER}px`, height: `${height - RULER}px` }" />
        <div v-if="range" class="range-bar" :style="{ left: `${x(range[0])}px`, width: `${x(range[1] - range[0])}px`, height: `${RULER}px` }" />
        <div class="head" :style="{ left: `${headX}px`, height: `${height}px` }"><i /></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tl { display: flex; border: 1px solid var(--line); border-radius: 4px; background: #fff; user-select: none; overflow: hidden; }
.tl.blade .content, .tl.blade .clip { cursor: crosshair; }
.labels { position: relative; flex-shrink: 0; border-right: 1px solid var(--line); background: var(--bg-soft); }
.corner { border-bottom: 1px solid var(--line); }
.lab { position: absolute; left: 0; right: 0; display: flex; align-items: center; padding: 0 10px; font-size: 11.5px; color: var(--muted); }
.scroller { flex: 1; min-width: 0; overflow-x: auto; overflow-y: hidden; position: relative; }
.content { position: relative; }

.ruler { position: absolute; top: 0; left: 0; width: 100%; border-bottom: 1px solid var(--line); cursor: ew-resize; background: #fff; z-index: 3; }
.tick { position: absolute; bottom: 0; width: 1px; height: 5px; background: var(--dash); }
.tick.major { height: 10px; background: var(--faint); }
.tlabel { position: absolute; top: 2px; font-size: 10px; color: var(--faint); white-space: nowrap; pointer-events: none; }

.lane { position: absolute; left: 0; background: #F1F1EE; border-radius: 2px; }

.clip {
  position: absolute; box-sizing: border-box; overflow: hidden; border-radius: 4px; cursor: grab; z-index: 2;
  border: 1px solid rgba(255, 255, 255, .9); box-shadow: inset 0 0 0 1px rgba(0, 0, 0, .25);
}
.clip.nested { background: repeating-linear-gradient(135deg, #2B3440 0 10px, #323C49 10px 20px); }
.clip.on { box-shadow: inset 0 0 0 2px var(--red), 0 0 0 1px var(--red); z-index: 3; }
.clip.moving { opacity: .75; cursor: grabbing; z-index: 6; box-shadow: 0 6px 16px rgba(0, 0, 0, .25); }
.name {
  position: absolute; left: 6px; right: 6px; top: 3px; font-family: var(--mono); font-size: 10.5px; color: #fff;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; pointer-events: none;
}
.name small { opacity: .7; font-size: 10px; }
.mark { position: absolute; bottom: 4px; height: 30px; background: rgba(255, 255, 255, .16); border-bottom: 4px solid rgba(255, 255, 255, .75); overflow: hidden; pointer-events: none; }
.mark.retake { border-bottom-color: #E8B02F; background: rgba(232, 176, 47, .15); }
.mark.voice { background: transparent; border-bottom: 4px dotted rgba(255, 255, 255, .7); }
.mark em { display: block; font-style: normal; font-size: 10px; line-height: 1.25; color: #fff; padding: 2px 4px; white-space: normal; max-height: 26px; overflow: hidden; }
.edge { position: absolute; top: 0; bottom: 0; width: 8px; cursor: ew-resize; z-index: 4; }
/* comme dans Filmora : [ rogne le début du bout sous la souris, ] sa fin (entre deux bouts collés, on voit lequel) */
.edge.l {
  left: 0;
  cursor: url("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' fill='none' stroke-linecap='round' stroke-linejoin='round'><path d='M16 4H12V20H16M8 12H2M4 10L2 12L4 14' stroke='white' stroke-width='4'/><path d='M16 4H12V20H16M8 12H2M4 10L2 12L4 14' stroke='black' stroke-width='2'/></svg>") 12 12, w-resize;
}
.edge.r {
  right: 0;
  cursor: url("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' fill='none' stroke-linecap='round' stroke-linejoin='round'><path d='M8 4H12V20H8M16 12H22M20 10L22 12L20 14' stroke='white' stroke-width='4'/><path d='M8 4H12V20H8M16 12H22M20 10L22 12L20 14' stroke='black' stroke-width='2'/></svg>") 12 12, e-resize;
}
.edge:hover { background: rgba(229, 72, 77, .55); }
.blade .edge { display: none; }
.drop-at { position: absolute; width: 3px; margin-left: -1.5px; background: #3B82C4; border-radius: 2px; z-index: 7; pointer-events: none; }

.wave { position: absolute; pointer-events: none; z-index: 1; }

.ghost { position: absolute; z-index: 5; pointer-events: none; background: rgba(229, 72, 77, .25); border: 1px solid var(--red); }
.ghost.grow { background: rgba(62, 158, 110, .25); border-color: #3E9E6E; }
.ghost-tip { position: absolute; z-index: 7; font-size: 10.5px; background: var(--ink); color: #fff; padding: 1px 5px; border-radius: 3px; pointer-events: none; white-space: nowrap; }

.range { position: absolute; background: rgba(229, 72, 77, .12); border-left: 1px solid var(--red); border-right: 1px solid var(--red); pointer-events: none; z-index: 4; }
.range-bar { position: absolute; top: 0; background: rgba(229, 72, 77, .25); pointer-events: none; z-index: 4; }
.head { position: absolute; top: 0; width: 1px; margin-left: -0.5px; background: var(--red); pointer-events: none; z-index: 8; }
.head i { position: absolute; top: 0; left: -5px; width: 11px; height: 10px; background: var(--red); clip-path: polygon(0 0, 100% 0, 50% 100%); }
</style>
