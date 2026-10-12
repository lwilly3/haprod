<script setup lang="ts">
/**
 * L'aperçu du montage au temps de la tête de lecture : la vidéo source (clips de l'A-roll bout à bout)
 * avec ses zooms, le B-roll par-dessus, le motion design (composition HyperFrames pilotée image par
 * image), les textes écrits à la main (qu'on déplace à la souris), et les sons. C'est une prévisualisation :
 * le rendu final se fait dans Resolve.
 * Un beat du storyboard pas encore fait s'affiche en slide, à sa place à l'écran, sa consigne modifiable sur place ;
 * un zoom ou un B-roll vidéo pas encore posé se voit déjà tel qu'il sera (avec une étiquette).
 */
import { computed, onBeforeUnmount, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import { domToCanvas } from "modern-screenshot";
import { mmss } from "../../../lib/format";
import type { Playlist } from "../derush/usePlaylist";
import SlideFrame from "../shorts/SlideFrame.vue";
import { fxFrame, layersAt } from "../../../lib/transitions";
import LayerVideo from "./LayerVideo.vue";
import {
  clipStarts, isImage, tcd, TEXT_BORDER, TEXT_FADE, TEXT_FONT, type AnimState, type Beat, type MontageView, type TextNote, type Timeline, type Visual,
} from "./types";

const props = defineProps<{
  player: Playlist; tl: Timeline; view: MontageView;
  /** les beats du storyboard sans animation, montrés en slide */
  beats?: Beat[];
  /** « Créer l'animation » sur la slide (absent : pas de bouton), et l'état de chaque création */
  create?: boolean;
  anims?: Record<string, AnimState>;
  /** les médias des B-roll (leur adresse) */
  visuals?: Visual[];
  /** le texte sélectionné (toujours visible, contour en pointillés), et si on peut déplacer les textes */
  textSel?: string | null; editable?: boolean;
}>();
const emit = defineEmits<{
  create: [string]; stop: [string]; remove: [string]; report: []; pick: [string, string];
  /** la consigne d'un beat réécrite sur sa slide */
  show: [string, string];
  /** un texte cliqué, puis déplacé (son centre, en fraction de l'image) */
  pickText: [string]; moveText: [string, number, number];
}>();
const live = (id: string) => ["queued", "running"].includes(props.anims?.[id]?.status ?? "");
const { t: tr } = useI18n();
const route = useRoute();
const shortName = (name: string) => name.replace(/\.[^.]+$/, "");
async function copySearch(b: Beat) {
  await navigator.clipboard.writeText(b.search || b.show);
}

const el = ref<HTMLVideoElement | null>(null);
onMounted(() => { props.player.video.value = el.value; });
onBeforeUnmount(() => { props.player.video.value = null; });

const t = computed(() => props.player.t.value);
const playing = computed(() => props.player.playing.value);
const step = (s: number) => props.player.seek(Math.max(0, Math.min(t.value + s, props.player.total.value)));

// --- volume de l'A-roll : celui du clip sous la tête de lecture. Par Web Audio, pour pouvoir monter au-dessus de
// 0 dB ; branché à la première lecture (le navigateur n'accepte le son qu'après un geste)
let audio: { ctx: AudioContext; gain: GainNode } | null = null;
const arollGain = computed(() => {
  const starts = clipStarts(props.tl);
  const i = starts.findLastIndex((s) => s <= t.value);
  return props.tl.aroll[i]?.gain_db ?? 0;
});
watch([arollGain, playing], () => {
  const v = el.value;
  if (!v) return;
  const linear = 10 ** (arollGain.value / 20);
  if (!audio && playing.value) {
    try {
      const ctx = new AudioContext(), gain = ctx.createGain();
      ctx.createMediaElementSource(v).connect(gain).connect(ctx.destination);
      audio = { ctx, gain };
    } catch { /* sans Web Audio : le volume reste plafonné à 0 dB */ }
  }
  if (audio) {
    if (audio.ctx.state === "suspended") audio.ctx.resume().catch(() => {});
    audio.gain.gain.value = linear;
  } else v.volume = Math.min(1, linear);
}, { immediate: true });
onUnmounted(() => { audio?.ctx.close().catch(() => {}); });

// --- zoom de l'A-roll (montée et descente progressives, comme à l'export)
const RAMP = 0.4;
// les beats du storyboard qui sont faits sans animation : vus tels qu'ils seront posés
const beatAt = (type: Beat["type"]) => props.beats?.find((b) => b.type === type && t.value >= b.at && t.value < b.at + b.dur
  && (type !== "broll" || (!!b.src && !isImage(b.src))));
const zoomBeat = computed(() => beatAt("zoom") ?? null);
const brollBeat = computed(() => beatAt("broll") ?? null);
const mediaUrl = (src: string) => props.view.media[src]?.url ?? props.visuals?.find((v) => v.src === src)?.url ?? "";

const zoom = computed(() => {
  const zb = zoomBeat.value;
  const z = props.tl.zooms.find((k) => t.value >= k.at && t.value < k.at + k.dur)
    ?? (zb?.zoom ? { at: zb.at, dur: zb.dur, ...zb.zoom } : null);
  if (!z) return { s: 1, x: 0, y: 0 };
  const ramp = Math.min(RAMP, z.dur / 3);
  const k = Math.min(1, (t.value - z.at) / ramp, (z.at + z.dur - t.value) / ramp);
  const e = k * k * (3 - 2 * k);
  return { s: 1 + (z.scale - 1) * e, x: z.x * e, y: z.y * e };
});
const videoStyle = computed(() => ({
  transform: `translate(${-zoom.value.x * 100}%, ${-zoom.value.y * 100}%) scale(${zoom.value.s})`,
}));

// --- transitions de l'A-roll : un second lecteur joue l'autre côté de la coupe (avant la coupe, le clip qui
// arrive ; après, la fin prolongée de celui qui part). Mêmes bornes qu'au rendu (render.segments) : centrée sur
// la coupe, réduite si la source n'a pas assez de marge.
const cuts = computed(() => {
  const starts = clipStarts(props.tl), total = props.view.source?.duration ?? 0;
  return props.tl.aroll.flatMap((cur, i) => {
    const prev = props.tl.aroll[i - 1], tr = cur.transition;
    // pas de transition avec un clip inséré d'un autre média (comme fxMax)
    if (!prev || !tr || prev.src || cur.src) return [];
    const half = Math.min(tr.dur / 2, (prev.out - prev.in) / 2, (cur.out - cur.in) / 2, Math.max(0, total - prev.out), cur.in);
    return half > 0.02 ? [{ fx: tr.fx, at: starts[i], half, out: prev.out, in: cur.in }] : [];
  });
});
const arollFx = computed(() => {
  const c = cuts.value.find((x) => Math.abs(t.value - x.at) < x.half);
  if (!c) return null;
  const f = fxFrame(c.fx, (t.value - (c.at - c.half)) / (2 * c.half), "pair");
  const before = t.value < c.at;
  // A dessous, l'aplat, B dessus
  return {
    main: { ...(before ? f.a : f.b), zIndex: before ? 1 : 3 },
    ghost: { ...(before ? f.b : f.a), zIndex: before ? 3 : 1 },
    veil: f.veil ? { ...f.veil, zIndex: 2 } : null,
    time: before ? c.in + (t.value - c.at) : c.out + (t.value - c.at),
  };
});
// hors transition, le second lecteur attend déjà au début de la prochaine
const ghostTime = computed(() => arollFx.value?.time ?? (() => {
  const next = cuts.value.find((x) => x.at - x.half > t.value);
  return next ? next.in - next.half : 0;
})());

// --- B-roll : les plans visibles à t, avec leurs transitions (deux à la fois pendant un enchaînement)
const brolls = computed(() => {
  const items = props.tl.broll.map((b) => ({ id: b.id, at: b.at, len: b.out - b.in, enter: b.enter, exit: b.exit, src: b.src, in: b.in }));
  const bb = brollBeat.value;
  // un beat pas encore posé, s'il n'y a rien d'autre
  if (bb && !items.some((b) => t.value >= b.at && t.value < b.at + b.len)) {
    items.push({ id: `beat-${bb.id}`, at: bb.at, len: bb.dur, enter: bb.enter, exit: bb.exit, src: bb.src!, in: bb.start ?? 0 });
  }
  return items;
});
const brollLayers = computed(() => layersAt(brolls.value, t.value).map((l) => {
  const b = brolls.value.find((x) => x.id === l.id)!;
  return { ...l, url: mediaUrl(b.src), time: b.in + l.local };
}));

// --- motion design
const stage = ref<HTMLElement>();
const stageW = ref(640);
const ro = new ResizeObserver(([e]) => { stageW.value = e.contentRect.width; });
onMounted(() => stage.value && ro.observe(stage.value));
onUnmounted(() => ro.disconnect());
// les compositions visibles à t, avec leurs transitions
const motionLayers = computed(() => layersAt(
  props.tl.motion.filter((m) => props.view.motions[m.id]?.html).map((m) => ({ id: m.id, at: m.at, len: m.dur, enter: m.enter, exit: m.exit })),
  t.value,
).map((l) => {
  const m = props.tl.motion.find((x) => x.id === l.id)!;
  return { ...l, slide: { id: m.id, start: m.at, end: m.at + m.dur, title: m.title, kind: m.kind, idea: m.idea, why: "", discarded: false,
    url: props.view.motions[m.id]!.html! } };
}));
const motion = computed(() => motionLayers.value[0] ?? null);
const motionPending = computed(() => {
  const m = props.tl.motion.find((k) => t.value >= k.at && t.value < k.at + k.dur);
  return m && !props.view.motions[m.id]?.html ? m : null;
});

// --- textes écrits à la main : la police, la taille et le contour du rendu, à l'échelle de l'aperçu
const texts = computed(() => props.tl.texts
  .filter((x) => t.value >= x.at && t.value < x.at + x.dur && (x.text.trim() || x.id === props.textSel))
  .map((x) => {
    const sel = x.id === props.textSel, size = x.size * stageW.value * 9 / 16;
    const fade = Math.min(TEXT_FADE, x.dur / 3);
    const k = Math.max(0, Math.min(1, (t.value - x.at) / fade, (x.at + x.dur - t.value) / fade));
    return {
      x, sel, style: {
        left: `${x.x * 100}%`, top: `${x.y * 100}%`, transform: `translate(-50%, -50%) rotate(${x.angle}deg)`,
        fontFamily: TEXT_FONT, fontSize: `${size}px`, color: x.color, WebkitTextStroke: `${2 * TEXT_BORDER * size}px #000`,
        // pendant qu'on le règle, le texte reste entier même au bord de son fondu
        opacity: sel ? 1 : k,
      },
    };
  }));
let textDrag: { id: string; dx: number; dy: number; x0: number; y0: number; moved: boolean } | null = null;
function downText(e: PointerEvent, x: TextNote) {
  if (e.button !== 0) return;
  e.stopPropagation();
  emit("pickText", x.id);
  if (!props.editable || !stage.value) return;
  const r = stage.value.getBoundingClientRect();
  textDrag = { id: x.id, dx: (e.clientX - r.left) / r.width - x.x, dy: (e.clientY - r.top) / r.height - x.y, x0: e.clientX, y0: e.clientY, moved: false };
  (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
}
function moveText(e: PointerEvent) {
  const d = textDrag;
  if (!d || !stage.value) return;
  if (!d.moved && Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < 3) return;
  d.moved = true;
  const r = stage.value.getBoundingClientRect();
  const fit = (v: number) => Math.round(Math.max(0, Math.min(1, v)) * 1000) / 1000;
  emit("moveText", d.id, fit((e.clientX - r.left) / r.width - d.dx), fit((e.clientY - r.top) / r.height - d.dy));
}

// --- sons : un lecteur par son en cours
const players = new Map<string, HTMLAudioElement>();
watch([t, playing], () => {
  const active = new Set<string>();
  if (playing.value) {
    for (const s of props.tl.audio) {
      if (t.value < s.at || t.value >= s.at + s.out - s.in) continue;
      const url = props.view.media[s.src]?.url;
      if (!url) continue;
      active.add(s.id);
      let a = players.get(s.id);
      // a.src est absolue et encodée (espaces → %20) : on compare avec l'adresse résolue de la même façon
      if (!a || a.src !== new URL(url, location.href).href) {
        a?.pause();
        a = new Audio(url);
        players.set(s.id, a);
      }
      a.volume = Math.min(1, Math.pow(10, s.gain_db / 20));
      const want = s.in + (t.value - s.at);
      if (Math.abs(a.currentTime - want) > 0.3) a.currentTime = want;
      if (a.paused) a.play().catch(() => {});
    }
  }
  for (const [id, a] of players) if (!active.has(id)) { a.pause(); players.delete(id); }
});
onUnmounted(() => { for (const a of players.values()) a.pause(); players.clear(); });

// un beat posé dont l'animation n'est pas écrite reste une slide, qu'on peut relancer ; un zoom ou un B-roll
// vidéo se voit déjà, une étiquette dit qu'il reste à poser
const beat = computed(() => (motion.value ? null
  : props.beats?.find((b) => t.value >= b.at && t.value < b.at + b.dur && b.type !== "zoom"
    && !(b.type === "broll" && b.src && !isImage(b.src))) ?? null));
const toPlace = computed(() => [zoomBeat.value, brollBeat.value].filter((b): b is Beat => !!b));

function slideKind(b: Beat) {
  if (b.type === "transition") return tr("editing.storyboard.types.transition");
  if (b.type === "broll") return `${tr("editing.storyboard.types.broll")} · ${b.src ? tr(`editing.storyboard.places.${b.place}`) : tr("editing.storyboard.broll.missing")}`;
  return `${tr(`editing.storyboard.kinds.${b.kind}`)} · ${tr(`editing.storyboard.places.${b.place}`)}`;
}
const chapter = computed(() => [...props.tl.markers].reverse().find((m) => m.kind === "chapter" && m.t <= t.value)?.text ?? "");

/**
 * L'image de l'aperçu telle qu'on la voit, en JPEG (data URL) : l'A-roll zoomé, le B-roll, le motion,
 * puis les slides des beats et les étiquettes. Les vidéos sont dessinées à la main (cadrage et zoom
 * exacts), le motion (iframe de même origine) et les slides passent par modern-screenshot.
 */
async function capture(W = 1280): Promise<string | null> {
  const box = stage.value;
  if (!box) return null;
  const H = Math.round((W * 9) / 16);
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const g = canvas.getContext("2d")!;
  g.fillStyle = "#1d1e20";
  g.fillRect(0, 0, W, H);
  const a = el.value;
  if (a && a.readyState >= 2 && a.videoWidth) {
    // comme le CSS : translate(-x, -y) scale(s) autour du centre, vidéo en contain
    const z = zoom.value, k = Math.min(W / a.videoWidth, H / a.videoHeight);
    const w = a.videoWidth * k, h = a.videoHeight * k;
    g.save();
    g.translate(W / 2 - z.x * W, H / 2 - z.y * H);
    g.scale(z.s, z.s);
    g.translate(-W / 2, -H / 2);
    g.drawImage(a, (W - w) / 2, (H - h) / 2, w, h);
    g.restore();
  }
  for (const b of box.querySelectorAll<HTMLVideoElement>("video.broll")) {
    if (b.readyState < 2 || !b.videoWidth) continue;
    // en cover
    const k = Math.max(W / b.videoWidth, H / b.videoHeight), w = W / k, h = H / k;
    g.drawImage(b, (b.videoWidth - w) / 2, (b.videoHeight - h) / 2, w, h, 0, 0, W, H);
  }
  for (const f of box.querySelectorAll("iframe")) {
    const doc = f.contentDocument;
    if (!doc?.documentElement) continue;
    const m = await domToCanvas(doc.documentElement, { width: 1920, height: 1080 }).catch(() => null);
    if (m) g.drawImage(m, 0, 0, W, H);
  }
  // les calques un par un, sans les boutons : capturer tout l'aperçu attendrait le chargement de ses vidéos
  const at = box.getBoundingClientRect(), k = W / at.width;
  const layers = [...box.children].filter((n): n is HTMLElement => n instanceof HTMLElement
    && !(n instanceof HTMLVideoElement || n instanceof HTMLIFrameElement) && !n.classList.contains("pbar")
    && !n.classList.contains("layer") && !!n.offsetWidth);
  for (const n of layers) {
    const r = n.getBoundingClientRect();
    const c = await domToCanvas(n, { scale: k, filter: (x) => !(x instanceof HTMLButtonElement || (x instanceof HTMLElement && x.classList.contains("s-acts"))) }).catch(() => null);
    if (c) g.drawImage(c, (r.left - at.left) * k, (r.top - at.top) * k, r.width * k, r.height * k);
  }
  return canvas.toDataURL("image/jpeg", 0.85);
}
defineExpose({ capture });
</script>

<template>
  <div class="preview">
    <div ref="stage" class="stage hatch-dark">
      <div class="aroll-box layer" :style="videoStyle" @click="player.toggle()">
        <video ref="el" class="aroll" preload="auto" playsinline :style="arollFx?.main" />
        <div v-if="arollFx?.veil" class="veil" :style="arollFx.veil" />
        <LayerVideo v-if="view.source && cuts.length" class="aroll ghost" :class="{ idle: !arollFx }" :src="view.source.url"
          :time="ghostTime" :playing="playing && !!arollFx" :style="arollFx?.ghost" />
      </div>
      <template v-for="l in brollLayers" :key="l.id">
        <div v-if="l.veil && !l.over" class="veil layer" :style="l.veil" />
        <LayerVideo class="broll" :src="l.url" :time="l.time" :playing="playing" :style="l.style" />
        <div v-if="l.veil && l.over" class="veil layer" :style="l.veil" />
      </template>
      <template v-for="l in motionLayers" :key="l.slide.url">
        <div v-if="l.veil && !l.over" class="veil layer" :style="l.veil" />
        <div class="mlayer layer" :style="l.style">
          <SlideFrame :slide="l.slide" :local="l.local" format="youtube" :scale="stageW / 1920" :visible="true" />
        </div>
        <div v-if="l.veil && l.over" class="veil layer" :style="l.veil" />
      </template>
      <div v-if="motionPending && !beat" class="pending">
        <span class="kind mono">motion · {{ motionPending.kind || tr("editing.preview.toWrite") }}</span>
        <span class="what">{{ motionPending.title }}</span>
      </div>
      <!-- un B-roll sans média : une carte en coin, qui laisse voir l'A-roll, pour le choisir ou le chercher -->
      <div v-if="beat?.type === 'broll' && !beat.src" class="slide find broll" :class="{ off: !beat.on }">
        <button v-if="create" class="x-btn s-remove" :title="tr('editing.storyboard.remove')" @click.stop="emit('remove', beat.id)">×</button>
        <span class="s-kind mono">{{ slideKind(beat) }}</span>
        <textarea v-if="create" class="s-edit" rows="2" :value="beat.show" @click.stop
          @input="emit('show', beat.id, ($event.target as HTMLTextAreaElement).value)" />
        <span v-else class="s-show">{{ beat.show }}</span>
        <span class="s-search mono">{{ tr("editing.storyboard.broll.search", { q: beat.search || "…" }) }}</span>
        <span v-if="create" class="s-acts">
          <select :title="tr('editing.storyboard.broll.media')" @click.stop
            @change="emit('pick', beat.id, ($event.target as HTMLSelectElement).value)">
            <option value="">{{ tr("editing.storyboard.broll.media") }} · {{ tr("editing.storyboard.broll.missing") }}</option>
            <optgroup v-for="w in ['projet', 'bibliothèque']" :key="w" :label="tr(`editing.storyboard.broll.where.${w === 'projet' ? 'project' : 'library'}`)">
              <option v-for="v in (visuals ?? []).filter((x) => x.where === w)" :key="v.src" :value="v.src" :title="v.description">
                {{ v.kind === "video" ? "▶ " : "" }}{{ shortName(v.name) }}
              </option>
            </optgroup>
          </select>
          <button class="btn sm" @click.stop="copySearch(beat)">{{ tr("editing.storyboard.broll.copy") }}</button>
          <RouterLink class="btn sm" :to="`/p/${route.params.pid}/ressources?add=youtube`">{{ tr("editing.storyboard.broll.goMedia") }}</RouterLink>
        </span>
      </div>
      <div v-else-if="beat" class="slide" :class="[beat.type === 'transition' ? 'full' : beat.place, beat.type, { off: !beat.on, img: isImage(beat.src) }]">
        <img v-if="beat.type === 'broll' && isImage(beat.src)" class="s-img" :src="mediaUrl(beat.src!)" alt="">
        <button v-if="create" class="x-btn s-remove" :title="tr('editing.storyboard.remove')" @click.stop="emit('remove', beat.id)">×</button>
        <span class="s-kind mono">{{ slideKind(beat) }}</span>
        <textarea v-if="create" class="s-edit" :rows="beat.type === 'transition' || beat.place === 'full' ? 3 : 4" :value="beat.show"
          :placeholder="tr(`editing.storyboard.showPh.${beat.type}`)" @click.stop @input="emit('show', beat.id, ($event.target as HTMLTextAreaElement).value)" />
        <span v-else class="s-show">{{ beat.show }}</span>
        <template v-if="create && (beat.type !== 'broll' || beat.src)">
          <span v-if="live(beat.id)" class="s-state mono">
            {{ anims![beat.id].status === "queued" ? tr("editing.anims.queued") : `${tr("editing.anims.running")} · ${anims![beat.id].activity ?? ""}` }}
            <button class="btn sm s-create" @click.stop="emit('stop', beat.id)">{{ tr("common.stop") }}</button>
          </span>
          <template v-else>
            <span v-if="anims?.[beat.id]?.status === 'error'" class="s-error">{{ tr("editing.anims.failed", { e: anims[beat.id].error }) }}</span>
            <button class="btn sm s-create" @click.stop="emit('create', beat.id)">
              {{ anims?.[beat.id] ? tr("editing.anims.retry") : tr("editing.storyboard.create") }}
            </button>
          </template>
        </template>
      </div>
      <!-- les textes : un calque de la taille de l'image (capturé d'un bloc), seuls les textes attrapent la souris -->
      <div v-if="texts.length" class="texts">
        <div v-for="x in texts" :key="x.x.id" class="txt" :class="{ sel: x.sel, drag: editable }" :style="x.style"
          @pointerdown="downText($event, x.x)" @pointermove="moveText" @pointerup="textDrag = null" @pointercancel="textDrag = null">
          {{ x.x.text.trim() ? x.x.text : tr("editing.preview.textPlaceholder") }}
        </div>
      </div>
      <span v-if="zoom.s > 1.001" class="tag mono">zoom ×{{ zoom.s.toFixed(2) }}</span>
      <div v-for="b in toPlace" :key="b.id" class="to-place mono" :class="{ off: !b.on }">
        {{ b.type === "zoom" ? tr("editing.storyboard.types.zoom") : tr("editing.storyboard.types.broll") }} · {{ tr("editing.storyboard.toPlace") }}
        <button v-if="create" class="btn sm" @click.stop="emit('create', b.id)">{{ tr("editing.storyboard.place_") }}</button>
        <button v-if="create" class="x-btn s-del" :title="tr('editing.storyboard.remove')" @click.stop="emit('remove', b.id)">×</button>
      </div>
      <span v-if="chapter" class="chap mono">{{ chapter }}</span>
      <div class="pbar"><div :style="{ width: `${player.total.value ? (t / player.total.value) * 100 : 0}%` }" /></div>
    </div>
    <div class="bar">
      <button class="btn ctl" :title="tr('editing.preview.start')" @click="player.seek(0)">⏮</button>
      <button class="btn ctl" :title="tr('editing.preview.back5')" @click="player.seek(t - 5)">−5 s</button>
      <button class="btn ctl" :title="tr('editing.preview.back1')" @click="step(-1)">−1 s</button>
      <button class="btn dark play" :title="tr('editing.preview.playPause')" @click="player.toggle()">{{ playing ? "❚❚" : "▶" }}</button>
      <button class="btn ctl" :title="tr('editing.preview.fwd1')" @click="step(1)">+1 s</button>
      <button class="btn ctl" :title="tr('editing.preview.fwd5')" @click="player.seek(t + 5)">+5 s</button>
      <span class="mono now">{{ tcd(t) }}</span><span class="mono dim">/ {{ mmss(player.total.value) }}</span>
      <span class="spacer" />
      <button v-if="!playing" class="btn ctl" :title="tr('editing.preview.reportTitle')" @click="emit('report')">{{ tr("editing.preview.report") }}</button>
    </div>
  </div>
</template>

<style scoped>
.preview { display: flex; flex-direction: column; gap: 8px; }
.stage { position: relative; aspect-ratio: 16 / 9; overflow: hidden; background-color: #1d1e20; }
.aroll-box { position: absolute; inset: 0; cursor: pointer; transform-origin: center; }
.aroll { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; }
.ghost { pointer-events: none; }
.ghost.idle { visibility: hidden; }
.broll { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; pointer-events: none; }
/* les calques d'une transition : la composition (mise à l'échelle par SlideFrame) et l'aplat d'un passage par une couleur */
.mlayer, .veil { position: absolute; inset: 0; pointer-events: none; }
.mlayer { overflow: hidden; }
.texts { position: absolute; inset: 0; pointer-events: none; }
.txt {
  position: absolute; white-space: pre; text-align: center; line-height: normal; paint-order: stroke fill;
  pointer-events: auto; cursor: pointer; user-select: none;
}
.txt.drag { cursor: move; }
.txt.sel { outline: 1.5px dashed rgba(255, 255, 255, .8); outline-offset: 4px; }
.pending {
  position: absolute; right: 6%; top: 12%; max-width: 40%; display: flex; flex-direction: column; gap: 4px;
  background: rgba(24, 25, 27, .85); border: 1px dashed #9C84EA; border-radius: 4px; padding: 10px 12px; pointer-events: none;
}
.pending .kind { font-size: 10px; text-transform: uppercase; color: #B9A6F2; }
.pending .what { font-size: 13px; font-weight: 600; color: #fff; }
.slide {
  position: absolute; display: flex; flex-direction: column; gap: 6px; padding: 12px 14px; overflow: hidden;
  background: rgba(24, 25, 27, .8); border: 1.5px dashed #B9A6F2; border-radius: 6px; color: #fff; pointer-events: none;
}
.slide.full { inset: 6%; justify-content: center; align-items: center; text-align: center; }
.slide.right { right: 5%; top: 10%; bottom: 10%; width: 36%; justify-content: center; }
.slide.left { left: 5%; top: 10%; bottom: 10%; width: 36%; justify-content: center; }
.slide.top { left: 8%; right: 8%; top: 7%; height: 30%; justify-content: center; }
.slide.lower { left: 8%; right: 8%; bottom: 7%; height: 30%; justify-content: center; }
.slide.find { left: 4%; bottom: 7%; width: 46%; max-height: 62%; gap: 5px; padding: 10px 12px; }
.slide.find .s-show { -webkit-line-clamp: 3; font-size: 12px; }
.s-acts { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 2px; pointer-events: auto; }
.s-acts select { max-width: 100%; font-size: 11.5px; }
.slide.off { opacity: .45; }
.slide.transition { border-color: #8DB4EE; background: rgba(20, 34, 58, .82); }
.slide.broll { border-color: #7CCFC4; }
.slide.img { padding: 0; justify-content: flex-end; }
.slide.img > :not(.s-img) { position: relative; margin: 0 12px; }
.slide.img > :last-child { margin-bottom: 10px; }
.s-img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: .55; }
.slide.left.img .s-img, .slide.right.img .s-img { object-fit: contain; background: #111; }
.s-search { font-size: 11px; color: #9FE0D7; }
.to-place {
  position: absolute; left: 10px; bottom: 12px; display: flex; align-items: center; gap: 8px; padding: 4px 6px 4px 10px;
  font-size: 11px; color: #fff; background: rgba(24, 25, 27, .8); border: 1.5px dashed #E8B02F; border-radius: 4px;
}
.to-place.off { opacity: .5; }
/* supprimer le beat (après confirmation) : en coin de la slide */
.slide > .s-remove, .slide.img > .s-remove { position: absolute; top: 6px; right: 8px; margin: 0; font-size: 17px; color: #C8C9C5; pointer-events: auto; }
.s-remove:hover, .s-del:hover { color: #fff; }
.s-del { color: #C8C9C5; }
.s-kind { font-size: 10px; text-transform: uppercase; letter-spacing: .05em; color: #B9A6F2; }
.s-show { font-size: 12.5px; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 6; -webkit-box-orient: vertical; overflow: hidden; }
.slide.full .s-show { font-size: 14px; max-width: 70%; }
.slide.lower .s-show, .slide.top .s-show { -webkit-line-clamp: 3; }
.s-create { align-self: flex-start; pointer-events: auto; margin-top: 4px; }
/* la consigne, réécrite sur place */
.s-edit {
  pointer-events: auto; width: 100%; box-sizing: border-box; resize: none; border: 1px solid transparent; border-radius: 3px;
  background: transparent; color: inherit; font: inherit; font-size: 12.5px; line-height: 1.4; padding: 2px 4px; margin: 0 -4px;
}
.s-edit:hover { border-color: rgba(255, 255, 255, .25); }
.s-edit:focus { outline: none; border-color: rgba(255, 255, 255, .55); background: rgba(0, 0, 0, .35); }
.s-edit::placeholder { color: rgba(255, 255, 255, .45); }
.slide.full .s-edit { text-align: center; font-size: 14px; max-width: 70%; }
.s-state { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 11px; color: #B9A6F2; }
.s-state .s-create { margin-top: 0; }
.s-error { font-size: 11.5px; color: #FFB4B4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.slide.full .s-create { align-self: center; }
.tag { position: absolute; left: 10px; top: 8px; font-size: 10.5px; color: #E8B02F; pointer-events: none; }
.chap { position: absolute; right: 10px; top: 8px; max-width: 50%; font-size: 10.5px; color: #C8C9C5; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; pointer-events: none; }
.pbar { position: absolute; left: 0; right: 0; bottom: 0; height: 3px; background: rgba(255, 255, 255, .15); pointer-events: none; }
.pbar > div { height: 3px; background: var(--red); }
.bar { display: flex; align-items: center; gap: 8px; }
.btn.ctl { padding: 0 10px; font-size: 12.5px; }
.btn.play { width: 42px; padding: 0; font-size: 12px; }
.now { font-size: 12.5px; padding-left: 6px; }
.dim { font-size: 12.5px; color: var(--faint); }
</style>
