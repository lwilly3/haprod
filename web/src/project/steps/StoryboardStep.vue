<script setup lang="ts">
/**
 * Storyboard de la vidéo longue : avant le montage, Daryl propose les moments où l'image change — un
 * motion design, un zoom, un B-roll, une transition — et ce qu'on y voit ; on coche, on réécrit, on
 * supprime. Rien n'entre dans la timeline ici : les beats cochés arrivent au Montage, où l'on crée leurs
 * animations et où l'on pose zooms et B-roll.
 *
 * Les beats au centre, l'aperçu à droite (la place du beat y est dessinée), une bande de rythme en haut
 * pour juger la densité, et sous l'aperçu le chat avec Daryl (sur toute la vidéo ou sur le moment choisi,
 * image comprise). Raccourcis : Espace lecture, ↑/↓ beat précédent / suivant.
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import AnimationPreview from "../../components/AnimationPreview.vue";
import TransitionPicker from "../../components/TransitionPicker.vue";
import type { Fx } from "../../lib/transitions";
import { act, store } from "../store";
import { usePlaylist, type Piece } from "./derush/usePlaylist";
import Preview from "./montage/Preview.vue";
import StoryboardChat from "./storyboard/StoryboardChat.vue";
import { BEAT_TYPES, isImage, tcd, TYPE_COLOR, type Beat, type BeatType, type BeatWarning } from "./montage/types";
import { useMontage } from "./montage/useMontage";
import { useStoryboard } from "./montage/useStoryboard";

const { t: tr, locale } = useI18n();
const route = useRoute();
const router = useRouter();
const project = computed(() => store.project!);
const M = useMontage(project.value.id);
const SB = useStoryboard(project.value.id);
const view = computed(() => SB.view.value);
const board = computed(() => view.value?.board ?? null);
const busy = computed(() => SB.busy.value);
const job = computed(() => view.value?.job ?? null);

// --- lecture : la timeline du montage, telle qu'elle est
const pieces = computed<Piece[]>(() => (M.view.value?.source && M.tl.value
  ? M.tl.value.aroll.map((c) => ({ src: M.view.value!.source!.url, start: c.in, end: c.out, on: true }))
  : []));
const player = usePlaylist(pieces);
const t = computed(() => player.t.value);
const total = computed(() => M.total.value);
const seek = (s: number) => player.seek(Math.max(0, Math.min(s, total.value)));
// les contrôles dépendent de l'A-roll : relus quand il change
watch(() => JSON.stringify(M.tl.value?.aroll ?? []), () => SB.load());

// --- réglages de la génération
const density = ref("equilibre");
const note = ref("");
const ALL = BEAT_TYPES;
/** les types que Daryl propose à la prochaine génération */
const genTypes = ref<BeatType[]>([...ALL]);
function toggleGen(k: BeatType) {
  genTypes.value = genTypes.value.includes(k) ? genTypes.value.filter((x) => x !== k) : ALL.filter((x) => x === k || genTypes.value.includes(x));
}
watch(board, (b) => { if (b) { density.value = b.density; note.value = b.note; } }, { immediate: true });
watch(() => view.value?.default_density, (d) => { if (d && !board.value) density.value = d; }, { immediate: true });

function run() {
  // les beats posés à la main au montage sont gardés : seul ce que Daryl avait proposé est refait
  if (all.value.some((b) => b.origin !== "user") && !confirm(tr("editing.storyboard.confirmRerun"))) return;
  SB.run(density.value, note.value, genTypes.value);
}

// --- les beats
const all = computed(() => board.value?.beats ?? []);
/** les types affichés (filtre de l'en-tête) */
const shown = ref<BeatType[]>([...ALL]);
/** tout est affiché : on ne garde que ce type ; sinon on l'ajoute ou on le retire (rien d'affiché : tout) */
function toggleShown(k: BeatType) {
  const next = shown.value.length === ALL.length ? [k]
    : shown.value.includes(k) ? shown.value.filter((x) => x !== k) : ALL.filter((x) => x === k || shown.value.includes(x));
  shown.value = next.length ? next : [...ALL];
}
const beats = computed(() => all.value.filter((b) => shown.value.includes(b.type)));
const countOf = (k: BeatType) => all.value.filter((b) => b.type === k).length;
const composed = computed(() => view.value?.composed ?? {});
const kept = computed(() => all.value.filter((b) => b.on).length);
const stats = computed(() => view.value?.checks?.density ?? null);
/** le mot de Daryl, sans le gras markdown */
const message = computed(() => (board.value?.message ?? "").replace(/\*\*/g, "").trim());
const num = (n: number, d = 0) => n.toLocaleString(locale.value, { maximumFractionDigits: d });

const warningsOf = computed(() => {
  const out: Record<string, BeatWarning[]> = {};
  for (const w of view.value?.checks?.warnings ?? []) if (w.beat) (out[w.beat] ??= []).push(w);
  return out;
});
const general = computed(() => (view.value?.checks?.warnings ?? []).filter((w) => !w.beat));
function warnText(w: BeatWarning) {
  return tr(`editing.storyboard.warnings.${w.kind}`, {
    text: w.text, delta: w.delta?.toLocaleString(locale.value, { maximumFractionDigits: 1 }),
    n: stats.value?.count ?? 0, a: stats.value?.target[0] ?? 0, b: stats.value?.target[1] ?? 0,
  });
}

function setOn(b: Beat, on: boolean) { SB.edit(() => { b.on = on; }, 150); }
// tout cocher / décocher : les types affichés seulement
function setAll(on: boolean) { SB.edit((list) => { list.forEach((b) => { if (shown.value.includes(b.type)) b.on = on; }); }, 150); }
function remove(b: Beat) {
  if (selected.value === b.id) selected.value = null;
  SB.edit((list) => list.filter((x) => x.id !== b.id), 150);
}
function change(b: Beat, key: "show" | "kind" | "place" | "anim" | "sfx" | "src" | "search", value: string) {
  SB.edit(() => {
    b[key] = value;
    // une image sur un côté : plein écran, gauche ou droite seulement
    if (key === "src" && isImage(value) && !["full", "left", "right"].includes(b.place)) b.place = "full";
  }, key === "show" || key === "search" ? 800 : 150);
}
/** La transition d'entrée ou de sortie au montage (null : coupe franche). */
function setEnd(b: Beat, key: "enter" | "exit", value: Fx | null | undefined) {
  SB.edit(() => { b[key] = value ?? null; }, 150);
}
function setStart(b: Beat, value: number) {
  SB.edit(() => { b.start = Math.max(0, Number.isFinite(value) ? Math.round(value * 100) / 100 : 0); }, 150);
}
function setType(b: Beat, type: BeatType) {
  SB.edit(() => {
    b.type = type;
    if (type === "zoom") b.zoom ??= { scale: 1.25, x: 0, y: 0 };
    if (type === "broll") {
      b.src ??= "";
      b.search ??= "";
      if (!["full", "left", "right"].includes(b.place)) b.place = "full";
    }
  }, 150);
}

// --- zoom : grossissement, et le centre qu'on clique dans le cadre
const SCALES = [1.15, 1.25, 1.35];
const room = (s: number) => (s - 1) / 2;
const clampZ = (v: number, s: number) => Math.round(Math.max(-room(s), Math.min(v, room(s))) * 1000) / 1000;
function setZoom(b: Beat, patch: Partial<NonNullable<Beat["zoom"]>>) {
  SB.edit(() => {
    const z = { ...(b.zoom ?? { scale: 1.25, x: 0, y: 0 }), ...patch };
    b.zoom = { scale: z.scale, x: clampZ(z.x, z.scale), y: clampZ(z.y, z.scale) };
  }, 150);
}
/** le cadre gardé, dans l'image entière (comme l'aperçu : agrandi autour du centre, puis décalé) */
function frameStyle(b: Beat) {
  const z = b.zoom ?? { scale: 1, x: 0, y: 0 };
  const w = 100 / z.scale;
  return { width: `${w}%`, height: `${w}%`, left: `${50 + (z.x / z.scale) * 100 - w / 2}%`, top: `${50 + (z.y / z.scale) * 100 - w / 2}%` };
}
/** l'image de la vidéo au début du beat, tirée des vignettes de la source (pour voir où est le visage) */
function thumbStyle(b: Beat) {
  const strip = M.view.value?.analysis.filmstrip, tl = M.tl.value, dur = M.view.value?.source?.duration ?? 0;
  if (!strip || !tl || !dur) return {};
  let acc = 0, src = 0;
  for (const c of tl.aroll) {
    const len = c.out - c.in;
    if (b.at + 0.5 < acc + len) { src = c.in + Math.max(0, b.at + 0.5 - acc); break; }
    acc += len;
  }
  const n = Math.ceil(dur / strip.step), rows = Math.ceil(n / strip.cols), i = Math.min(n - 1, Math.floor(src / strip.step));
  const col = i % strip.cols, row = Math.floor(i / strip.cols);
  return {
    backgroundImage: `url(${strip.url})`, backgroundSize: `${strip.cols * 100}% ${rows * 100}%`,
    backgroundPosition: `${strip.cols > 1 ? (col / (strip.cols - 1)) * 100 : 0}% ${rows > 1 ? (row / (rows - 1)) * 100 : 0}%`,
  };
}
function onFrame(e: MouseEvent, b: Beat) {
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
  const s = b.zoom?.scale ?? 1.25;
  setZoom(b, { x: ((e.clientX - r.left) / r.width - 0.5) * s, y: ((e.clientY - r.top) / r.height - 0.5) * s });
}

// --- B-roll : le média choisi, ou la recherche à faire
const visuals = computed(() => view.value?.visuals ?? []);
const visualOf = (b: Beat) => visuals.value.find((v) => v.src === b.src) ?? null;
const shortName = (name: string) => name.replace(/\.[^.]+$/, "");
async function copySearch(b: Beat) {
  await navigator.clipboard.writeText(b.search || b.show);
}
const animOf = (b: Beat) => view.value?.anims.find((a) => a.name === b.anim) ?? null;
const sfxName = (s: string) => (s ? s.split("/").pop()!.replace(/\.[^.]+$/, "") : tr("editing.storyboard.noSfx"));
const hovered = ref<string | null>(null);

// --- le beat en cours : celui qu'on a choisi, sinon celui que la lecture traverse
const selected = ref<string | null>(null);
const playingBeat = computed(() => beats.value.find((b) => t.value >= b.at && t.value < b.at + b.dur) ?? null);
const current = computed(() => beats.value.find((b) => b.id === selected.value) ?? playingBeat.value);
/** les beats montrés en slide sur l'aperçu : ceux qui ne sont pas encore animés */
const slides = computed(() => all.value.filter((b) => !composed.value[b.id]));

const list = ref<HTMLElement>();
function focusId(id: string) {
  const b = beats.value.find((x) => x.id === id);
  if (b) focus(b);
}
function onSend(text: string, at: number | null, beat: string | null, frame: boolean) {
  if (player.playing.value) player.toggle();
  SB.send(text, at, beat, frame);
}
async function focus(b: Beat, scroll = true) {
  selected.value = b.id;
  seek(b.at);
  if (!scroll) return;
  await nextTick();
  list.value?.querySelector(`[data-beat="${b.id}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}
/** un clic sur la carte, hors des champs : on y amène la lecture */
function onCard(e: MouseEvent, b: Beat) {
  if ((e.target as HTMLElement).closest("input, textarea, select, button")) return;
  focus(b, false);
}
// arrivé depuis la piste motion du Montage (?beat=b3)
watch([() => route.query.beat, beats], ([id]) => {
  const b = typeof id === "string" ? beats.value.find((x) => x.id === id) : null;
  if (b && selected.value !== b.id) focus(b);
}, { immediate: true });

// --- bande de rythme
const pct = (s: number) => `${total.value ? (s / total.value) * 100 : 0}%`;
const chapters = computed(() => (M.tl.value?.markers ?? []).filter((m) => m.kind === "chapter"));
const strip = ref<HTMLElement>();
function onStrip(e: MouseEvent) {
  const r = strip.value!.getBoundingClientRect();
  seek(((e.clientX - r.left) / r.width) * total.value);
  selected.value = null;
}

// --- valider : les beats cochés passent au Montage, où l'on crée leurs animations
const validating = ref(false);
async function validate() {
  validating.value = true;
  await SB.flush();
  if (project.value.status.storyboard !== "done") await act("/steps/storyboard", { done: true });
  validating.value = false;
  router.push(`/p/${project.value.id}/montage`);
}

// --- raccourcis clavier
function onKey(e: KeyboardEvent) {
  const el = e.target as HTMLElement | null;
  if (el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))) return;
  const i = current.value ? beats.value.indexOf(current.value) : -1;
  if (e.key === " ") player.toggle();
  else if (e.key === "ArrowDown") {
    const b = i >= 0 ? beats.value[i + 1] : beats.value.find((x) => x.at > t.value);
    if (b) focus(b);
  } else if (e.key === "ArrowUp") {
    const b = i >= 0 ? beats.value[i - 1] : [...beats.value].reverse().find((x) => x.at < t.value);
    if (b) focus(b);
  } else return;
  e.preventDefault();
}
onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <div class="screen">
    <div v-if="!M.view.value || !view" class="eyebrow">{{ tr("common.loading") }}</div>
    <div v-else-if="!M.view.value.source" class="dashed-box">
      {{ tr("editing.needSource") }}
      <RouterLink :to="`/p/${project.id}/transcript`">{{ tr("editing.goToSource") }}</RouterLink>
    </div>

    <!-- Daryl écrit -->
    <div v-else-if="busy" class="state">
      <span class="state-label mono">{{ tr("editing.storyboard.working", { a: job?.activity || tr("editing.storyboard.starting") }) }}</span>
      <div class="progress bar"><div :style="{ width: `${Math.round((job?.progress ?? 0) * 100)}%` }" /></div>
      <button class="btn sm" @click="SB.stop()">{{ tr("common.stop") }}</button>
    </div>

    <!-- pas encore de storyboard -->
    <div v-else-if="!board" class="state">
      <h2>{{ tr("editing.storyboard.emptyTitle") }}</h2>
      <p class="state-text">{{ tr("editing.storyboard.intro") }}</p>
      <span v-if="job?.status === 'error'" class="error">{{ tr("editing.storyboard.failed", { e: job.error }) }}</span>
      <div class="settings">
        <label class="field">
          <span>{{ tr("editing.storyboard.density") }}</span>
          <select v-model="density">
            <option v-for="d in view.densities" :key="d" :value="d">{{ tr(`editing.storyboard.densities.${d}`) }}</option>
          </select>
        </label>
        <textarea v-model="note" rows="2" :placeholder="tr('editing.storyboard.notePlaceholder')" />
        <div class="field">
          <span>{{ tr("editing.storyboard.genTypes") }}</span>
          <span class="gen-types">
            <button v-for="k in ALL" :key="k" class="gen" :class="{ on: genTypes.includes(k) }" :style="{ '--c': TYPE_COLOR[k] }"
              @click="toggleGen(k)">{{ tr(`editing.storyboard.types.${k}`) }}</button>
          </span>
        </div>
      </div>
      <button class="btn dark lg" :disabled="!genTypes.length" @click="run">{{ tr("editing.storyboard.run") }}</button>
    </div>

    <template v-else>
      <!-- en-tête : où on en est, et la suite -->
      <header class="head">
        <div class="summary">
          <span class="count">{{ tr("editing.storyboard.stats", { kept, n: all.length }) }}</span>
          <span v-if="countOf('motion')" class="dim">{{ tr("editing.storyboard.motionStats", { m: stats?.count ?? 0, a: stats?.target[0] ?? 0, b: stats?.target[1] ?? 0 }) }}</span>
          <span v-if="stats?.every" class="dim">{{ tr("editing.storyboard.every", { s: num(stats.every) }) }}</span>
          <span class="types">
            <button v-for="k in ALL" :key="k" class="type-chip" :class="{ on: shown.includes(k) }" :style="{ '--c': TYPE_COLOR[k] }"
              :disabled="!countOf(k)" @click="toggleShown(k)">
              <i />{{ tr(`editing.storyboard.types.${k}`) }} <b class="mono">{{ countOf(k) }}</b>
            </button>
          </span>
          <span class="links">
            <button class="link-btn" @click="setAll(true)">{{ tr("editing.storyboard.checkAll") }}</button>
            <button class="link-btn" @click="setAll(false)">{{ tr("editing.storyboard.uncheckAll") }}</button>
          </span>
        </div>
        <div class="regen">
          <select v-model="density" :title="tr('editing.storyboard.density')">
            <option v-for="d in view.densities" :key="d" :value="d">{{ tr(`editing.storyboard.densities.${d}`) }}</option>
          </select>
          <input v-model="note" :placeholder="tr('editing.storyboard.notePlaceholder')">
          <span class="gen-types" :title="tr('editing.storyboard.genTypes')">
            <button v-for="k in ALL" :key="k" class="gen" :class="{ on: genTypes.includes(k) }" :style="{ '--c': TYPE_COLOR[k] }"
              @click="toggleGen(k)">{{ tr(`editing.storyboard.types.${k}`) }}</button>
          </span>
          <button class="btn sm" :disabled="!genTypes.length" @click="run">{{ tr("editing.storyboard.rerun") }}</button>
        </div>
        <button class="btn red md" :disabled="!kept || validating" @click="validate">
          {{ tr("editing.storyboard.validate", kept) }}
        </button>
      </header>

      <!-- bande de rythme : un bloc par beat, sur toute la durée -->
      <div ref="strip" class="strip" @click="onStrip">
        <span v-for="c in chapters" :key="c.id" class="chap" :style="{ left: pct(c.t) }" :title="c.text" />
        <button v-for="b in beats" :key="b.id" class="block"
          :class="[b.type, { off: !b.on, done: !!composed[b.id], cur: current?.id === b.id, warn: !!warningsOf[b.id] }]"
          :style="{ left: pct(b.at), width: pct(b.dur), '--c': TYPE_COLOR[b.type] }" :title="`${tcd(b.at)} · ${b.show}`" @click.stop="focus(b)" />
        <span class="head-line" :style="{ left: pct(t) }" />
      </div>

      <div class="body">
        <div ref="list" class="list">
          <details v-if="message" class="message">
            <summary>{{ tr("editing.storyboard.darylSays") }} <span class="first">{{ message.split(/\n/)[0] }}</span></summary>
            <p>{{ message }}</p>
          </details>
          <section v-if="general.length || board.unresolved.length" class="warnings">
            <span v-for="(w, i) in general" :key="`g${i}`">{{ warnText(w) }}</span>
            <template v-for="(u, i) in board.unresolved" :key="`u${i}`">
              <span v-if="u.origin === 'script'">{{ tr("editing.storyboard.planMissing", { text: u.anchor }) }}</span>
              <button v-else class="warn" @click="seek(u.t)">
                <span class="mono">{{ tcd(u.t) }}</span> {{ tr("editing.storyboard.unresolved", { text: u.anchor }) }}
              </button>
            </template>
          </section>

          <article v-for="b in beats" :key="b.id" class="beat" :data-beat="b.id" :style="{ '--c': TYPE_COLOR[b.type] }"
            :class="{ off: !b.on, cur: current?.id === b.id, done: !!composed[b.id] }" @click="onCard($event, b)">
            <!-- quand -->
            <div class="when">
              <label class="check">
                <input type="checkbox" :checked="b.on" @change="setOn(b, ($event.target as HTMLInputElement).checked)">
                <span class="n mono">{{ all.indexOf(b) + 1 }}</span>
              </label>
              <button class="tc mono" :title="tr('editing.storyboard.jump')" @click="focus(b, false)">{{ tcd(b.at) }}</button>
              <span class="dur mono">{{ num(b.dur, 1) }} s</span>
              <select class="type-select" :value="b.type" :disabled="!!composed[b.id]" :title="tr('editing.storyboard.typeTitle')"
                @change="setType(b, ($event.target as HTMLSelectElement).value as BeatType)">
                <option v-for="k in ALL" :key="k" :value="k">{{ tr(`editing.storyboard.types.${k}`) }}</option>
              </select>
              <span v-if="b.origin" class="origin" :class="b.origin" :title="tr(`editing.storyboard.originTitle.${b.origin}`)">
                {{ tr(`editing.storyboard.origin.${b.origin}`) }}
              </span>
              <span v-if="composed[b.id]" class="composed" :title="tr('editing.storyboard.composedTitle')">
                {{ tr("editing.storyboard.composed", { id: composed[b.id] }) }}
              </span>
            </div>

            <!-- quoi -->
            <div class="what">
              <p class="says"><span class="label">{{ tr("editing.storyboard.says") }}</span>« {{ b.says }} »</p>
              <label class="show">
                <span class="label">{{ tr("editing.storyboard.showLabel") }}</span>
                <textarea :value="b.show" rows="3" :placeholder="tr(`editing.storyboard.showPh.${b.type}`)"
                  @input="change(b, 'show', ($event.target as HTMLTextAreaElement).value)" @blur="SB.flush()" />
              </label>
              <p v-if="b.motion.enter || b.motion.hold" class="motion">
                <template v-for="(s, k) in [b.motion.enter, b.motion.hold, b.motion.exit].filter(Boolean)" :key="k">
                  <span v-if="k" class="arrow">→</span><span>{{ s }}</span>
                </template>
              </p>
              <p v-if="b.why" class="why">{{ b.why }}</p>
              <p v-for="(w, k) in warningsOf[b.id] ?? []" :key="k" class="beat-warn">{{ warnText(w) }}</p>
            </div>

            <!-- comment : selon le type -->
            <div v-if="b.type === 'zoom'" class="how">
              <label>
                <span class="label">{{ tr("editing.storyboard.zoom.scale") }}</span>
                <select :value="b.zoom?.scale" @change="setZoom(b, { scale: +($event.target as HTMLSelectElement).value })">
                  <option v-if="b.zoom && !SCALES.includes(b.zoom.scale)" :value="b.zoom.scale">×{{ num(b.zoom.scale, 2) }}</option>
                  <option v-for="(sc, k) in SCALES" :key="sc" :value="sc">{{ tr(`editing.storyboard.zoom.scales.${k}`) }} · ×{{ num(sc, 2) }}</option>
                </select>
              </label>
              <div>
                <span class="label">{{ tr("editing.storyboard.zoom.frame") }}</span>
                <!-- l'image entière, le cadre gardé dessiné dedans : on clique là où on veut le centre -->
                <span class="framer" :style="thumbStyle(b)" :title="tr('editing.storyboard.zoom.frameTitle')" @click.stop="onFrame($event, b)">
                  <span class="kept" :style="frameStyle(b)" />
                </span>
              </div>
            </div>

            <div v-else-if="b.type === 'broll'" class="how">
              <label>
                <span class="label">{{ tr("editing.storyboard.broll.media") }}</span>
                <select :value="b.src ?? ''" :title="visualOf(b)?.description || ''"
                  @change="change(b, 'src', ($event.target as HTMLSelectElement).value)">
                  <option value="">{{ tr("editing.storyboard.broll.missing") }}</option>
                  <option v-if="b.src && !visualOf(b)" :value="b.src">{{ b.src.split("/").pop() }}</option>
                  <optgroup v-for="w in ['projet', 'bibliothèque']" :key="w" :label="tr(`editing.storyboard.broll.where.${w === 'projet' ? 'project' : 'library'}`)">
                    <option v-for="v in visuals.filter((x) => x.where === w)" :key="v.src" :value="v.src" :title="v.description">
                      {{ v.kind === "video" ? "▶ " : "" }}{{ shortName(v.name) }}
                    </option>
                  </optgroup>
                </select>
              </label>
              <template v-if="visualOf(b)">
                <img v-if="visualOf(b)!.kind === 'image'" class="thumb" :src="visualOf(b)!.url" alt="">
                <template v-else>
                  <!-- l'image du média à la seconde où le plan commence -->
                  <video class="thumb" :src="`${visualOf(b)!.url}#t=${b.start ?? 0}`" muted preload="metadata" />
                  <label>
                    <span class="label">{{ tr("editing.storyboard.broll.start") }}</span>
                    <input type="number" min="0" step="0.1" :value="b.start ?? 0"
                      @change="setStart(b, +($event.target as HTMLInputElement).value)">
                  </label>
                </template>
              </template>
              <div v-else-if="!b.src" class="find">
                <span class="label">{{ tr("editing.storyboard.broll.toFind") }}</span>
                <input :value="b.search" :placeholder="tr('editing.storyboard.broll.searchPh')"
                  @input="change(b, 'search', ($event.target as HTMLInputElement).value)" @blur="SB.flush()">
                <span class="find-links">
                  <button class="link-btn" @click="copySearch(b)">{{ tr("editing.storyboard.broll.copy") }}</button>
                  <RouterLink :to="`/p/${project.id}/assets`">{{ tr("editing.storyboard.broll.goAssets") }}</RouterLink>
                </span>
              </div>
              <div v-if="isImage(b.src)">
                <span class="label">{{ tr("editing.storyboard.place") }} · <b class="place-name">{{ tr(`editing.storyboard.places.${b.place}`) }}</b></span>
                <span class="placer">
                  <button v-for="p in ['full', 'left', 'right']" :key="p" class="zone" :class="[p, { on: b.place === p }]"
                    :title="tr(`editing.storyboard.places.${p}`)" @click="change(b, 'place', p)" />
                </span>
              </div>
              <label>
                <span class="label">{{ tr("editing.storyboard.sfx") }}</span>
                <select :value="b.sfx" :title="view.sfx_help[b.sfx] || ''" @change="change(b, 'sfx', ($event.target as HTMLSelectElement).value)">
                  <option v-for="sx in view.sfx" :key="sx" :value="sx" :title="view.sfx_help[sx]">{{ sfxName(sx) }}</option>
                </select>
              </label>
              <div class="ends">
                <TransitionPicker :title="tr('transitions.enter')" :model-value="b.enter" @update:model-value="(v) => setEnd(b, 'enter', v)" />
                <TransitionPicker :title="tr('transitions.exit')" :model-value="b.exit" @update:model-value="(v) => setEnd(b, 'exit', v)" />
              </div>
            </div>

            <div v-else-if="b.type === 'transition'" class="how">
              <p class="hint">{{ tr("editing.storyboard.transitionHint") }}</p>
              <label>
                <span class="label">{{ tr("editing.storyboard.sfx") }}</span>
                <select :value="b.sfx" :title="view.sfx_help[b.sfx] || ''" @change="change(b, 'sfx', ($event.target as HTMLSelectElement).value)">
                  <option v-for="sx in view.sfx" :key="sx" :value="sx" :title="view.sfx_help[sx]">{{ sfxName(sx) }}</option>
                </select>
              </label>
            </div>

            <div v-else class="how">
              <div>
                <span class="label">{{ tr("editing.storyboard.place") }} · <b class="place-name">{{ tr(`editing.storyboard.places.${b.place}`) }}</b></span>
                <!-- l'écran en petit : on clique la zone où le visuel apparaît -->
                <span class="placer">
                  <button v-for="p in view.places" :key="p" class="zone" :class="[p, { on: b.place === p }]"
                    :title="tr(`editing.storyboard.places.${p}`)" @click="change(b, 'place', p)" />
                </span>
              </div>
              <label>
                <span class="label">{{ tr("editing.storyboard.kind") }}</span>
                <select :value="b.kind" @change="change(b, 'kind', ($event.target as HTMLSelectElement).value)">
                  <option v-for="k in view.kinds" :key="k" :value="k">{{ tr(`editing.storyboard.kinds.${k}`) }}</option>
                </select>
              </label>
              <label>
                <span class="label">{{ tr("editing.storyboard.base") }}</span>
                <select :value="b.anim ?? ''" :title="animOf(b)?.description || tr('editing.storyboard.anim')"
                  @change="change(b, 'anim', ($event.target as HTMLSelectElement).value)">
                  <option value="">{{ tr("editing.storyboard.custom") }}</option>
                  <option v-for="a in view.anims" :key="a.name" :value="a.name" :title="a.description">{{ a.title }}</option>
                </select>
              </label>
              <div v-if="animOf(b)" class="anim" @mouseenter="hovered = b.id" @mouseleave="hovered = null">
                <AnimationPreview :src="animOf(b)!.url" :id="animOf(b)!.id" :format="animOf(b)!.format" :hero="animOf(b)!.hero" :playing="hovered === b.id" />
              </div>
              <label>
                <span class="label">{{ tr("editing.storyboard.sfx") }}</span>
                <select :value="b.sfx" :title="view.sfx_help[b.sfx] || ''" @change="change(b, 'sfx', ($event.target as HTMLSelectElement).value)">
                  <option v-for="s in view.sfx" :key="s" :value="s" :title="view.sfx_help[s]">{{ sfxName(s) }}</option>
                </select>
              </label>
              <div class="ends">
                <TransitionPicker :title="tr('transitions.enter')" :model-value="b.enter" @update:model-value="(v) => setEnd(b, 'enter', v)" />
                <TransitionPicker :title="tr('transitions.exit')" :model-value="b.exit" @update:model-value="(v) => setEnd(b, 'exit', v)" />
              </div>
            </div>

            <button class="x-btn remove" :title="tr('editing.storyboard.remove')" @click="remove(b)">×</button>
          </article>
        </div>

        <!-- l'aperçu, avec la place du beat dessinée dessus, et le chat avec Daryl -->
        <aside class="aside">
          <Preview v-if="M.tl.value" :player="player" :tl="M.tl.value" :view="M.view.value" :beats="slides" :visuals="visuals" />
          <p class="keys mono">{{ tr("editing.storyboard.keys") }}</p>
          <StoryboardChat :chat="view.chat" :t="t" :beat="current" :beats="beats"
            @send="onSend" @stop="SB.stopChat()" @seek="seek" @focus="focusId" />
        </aside>
      </div>
    </template>
  </div>
</template>

<style scoped>
.screen { padding: 16px 32px 32px; display: flex; flex-direction: column; gap: 14px; }
.mono { font-family: var(--mono); }
.dim { color: var(--faint); }
.label { display: block; font-size: 10.5px; letter-spacing: .06em; text-transform: uppercase; color: var(--faint); margin-bottom: 4px; }
select, input, textarea { font: inherit; font-size: 13px; border: 1px solid var(--line-input); border-radius: 4px; background: #fff; }
select { padding: 4px 6px; }
input { padding: 5px 8px; }
textarea { padding: 8px 10px; resize: vertical; line-height: 1.5; }
.dashed-box { display: flex; flex-direction: column; gap: 10px; align-items: center; }

/* états : génération, pas encore de storyboard */
.state { max-width: 560px; margin: 8vh auto 0; display: flex; flex-direction: column; align-items: center; gap: 14px; text-align: center; }
.state h2 { margin: 0; font-size: 20px; }
.state-text { margin: 0; font-size: 14px; color: var(--muted); line-height: 1.6; text-wrap: pretty; }
.state-label { font-size: 12.5px; color: var(--muted); }
.progress.bar { width: 260px; }
.settings { width: 100%; display: flex; flex-direction: column; gap: 10px; }
.field { display: flex; align-items: center; justify-content: center; gap: 8px; font-size: 13px; color: var(--muted); }
.error { font-size: 13px; color: var(--red-ink); }

/* en-tête */
.head { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }
.summary { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; font-size: 13px; }
.count { font-weight: 600; }
.links { display: flex; gap: 10px; font-size: 12.5px; }
.regen { display: flex; gap: 6px; align-items: center; margin-left: auto; }
.regen input { width: 240px; }
.types { display: flex; gap: 6px; }
.type-chip, .gen {
  display: inline-flex; align-items: center; gap: 6px; padding: 3px 9px; font: inherit; font-size: 12px; border: 1px solid var(--line-strong);
  border-radius: 999px; background: #fff; color: var(--muted); cursor: pointer;
}
.type-chip i { width: 8px; height: 8px; border-radius: 50%; background: var(--c); opacity: .35; }
.type-chip.on { color: var(--ink); border-color: var(--c); }
.type-chip.on i { opacity: 1; }
.type-chip b { font-weight: 600; font-size: 11px; }
.type-chip:disabled { opacity: .4; cursor: default; }
.gen-types { display: inline-flex; gap: 4px; }
.gen { padding: 2px 8px; font-size: 11.5px; }
.gen.on { background: var(--c); border-color: var(--c); color: #fff; }

/* bande de rythme */
.strip { position: relative; height: 30px; border-radius: 4px; background: var(--bg-soft); border: 1px solid var(--line); cursor: pointer; }
.chap { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--line-strong); }
.block { position: absolute; top: 4px; bottom: 12px; min-width: 3px; padding: 0; border: none; border-radius: 2px; background: var(--c); cursor: pointer; }
/* les zooms sur une ligne à part, en dessous : ils accompagnent ce qui est à l'écran */
.block.zoom { top: 20px; bottom: 4px; }
.block.off { background: var(--toggle-off); }
.block.done { background: var(--ink); }
.block.warn:not(.off) { box-shadow: inset 0 -3px 0 var(--red); }
.block.cur { outline: 2px solid var(--red); outline-offset: 1px; z-index: 1; }
.head-line { position: absolute; top: -3px; bottom: -3px; width: 2px; margin-left: -1px; background: var(--red); pointer-events: none; }

/* corps : beats, aperçu */
.body { display: grid; grid-template-columns: minmax(0, 1fr) minmax(380px, 520px); gap: 28px; align-items: start; }
.list { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.message { padding: 10px 14px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg-softer); font-size: 13.5px; color: var(--ink-2); }
.message summary { cursor: pointer; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.message summary .first { color: var(--ink-2); }
.message[open] summary .first { display: none; }
.message p { margin: 8px 0 0; line-height: 1.6; white-space: pre-line; max-width: 80ch; }
.warnings { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; background: var(--bg-soft); border-radius: 4px; font-size: 12.5px; color: var(--ink-3); }
.warn { text-align: left; border: none; background: transparent; padding: 0; font-size: 12.5px; color: var(--ink-3); cursor: pointer; }
.warn:hover { color: var(--ink); }
.warn .mono { font-size: 11.5px; color: var(--faint); margin-right: 4px; }

.beat {
  position: relative; display: grid; grid-template-columns: 96px minmax(0, 1fr) 220px; gap: 20px;
  padding: 16px 40px 16px 16px; background: #fff; border: 1px solid var(--line); border-left: 4px solid var(--c); border-radius: 6px;
  scroll-margin-top: 16px;
}
.beat.done { border-left-color: var(--ink); }
.beat.off { border-left-color: var(--line-strong); background: var(--bg-softer); }
.beat.off .what, .beat.off .how { opacity: .5; }
.beat.cur { box-shadow: 0 0 0 2px var(--red); }
.when { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; }
.check { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.check input { width: 16px; height: 16px; margin: 0; }
.n { font-size: 12px; color: var(--faint); }
.tc { border: none; background: transparent; padding: 0; font-size: 14px; font-weight: 600; color: var(--ink); cursor: pointer; }
.tc:hover { color: var(--red-ink); }
.dur { font-size: 12px; color: var(--muted); }
.origin, .composed { font-size: 11px; padding: 1px 7px; border-radius: 3px; white-space: nowrap; }
.origin.script { background: var(--ink); color: #fff; }
.origin.daryl { background: #EEE9FC; color: #5B3FC4; }
.origin.user { background: #FCE8F0; color: #A62E5C; }
.composed { border: 1px solid var(--ink); color: var(--ink); }

.what { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.says { margin: 0; font-size: 13.5px; color: var(--muted); font-style: italic; line-height: 1.5; }
.says .label { font-style: normal; }
.show { display: flex; flex-direction: column; }
.show textarea { font-size: 14.5px; color: var(--ink); field-sizing: content; min-height: 4.8em; resize: none; }
.motion { margin: 0; display: flex; flex-wrap: wrap; gap: 6px; font-size: 12.5px; color: var(--muted); line-height: 1.45; }
.arrow { color: var(--faint); }
.why { margin: 0; font-size: 12.5px; color: var(--faint); line-height: 1.45; }
.beat-warn { margin: 0; font-size: 12.5px; color: var(--red-ink); }

.how { display: flex; flex-direction: column; gap: 10px; }
.how select { width: 100%; }
.ends { display: flex; gap: 14px; flex-wrap: wrap; }
.place-name { font-weight: 600; color: var(--ink); text-transform: none; letter-spacing: 0; font-size: 12px; }
.placer { position: relative; display: block; width: 100%; aspect-ratio: 16 / 9; border: 1px solid var(--line-strong); border-radius: 4px; background: var(--bg-soft); }
.zone { position: absolute; padding: 0; border: 1px dashed var(--dash); border-radius: 2px; background: #fff; cursor: pointer; }
.zone:hover { border-color: var(--ink); }
.zone.on { background: #7C5CE0; border: 1px solid #7C5CE0; }
.zone.full { left: 38%; right: 38%; top: 32%; bottom: 32%; }
.zone.left { left: 5%; top: 30%; bottom: 30%; width: 28%; }
.zone.right { right: 5%; top: 30%; bottom: 30%; width: 28%; }
.zone.top { left: 8%; right: 8%; top: 6%; height: 18%; }
.zone.lower { left: 8%; right: 8%; bottom: 6%; height: 18%; }
.zone.full.on { left: 4%; right: 4%; top: 6%; bottom: 6%; opacity: .35; z-index: 0; }
.anim { border-radius: 4px; overflow: hidden; }
.type-select { font-size: 11.5px; padding: 1px 4px; color: var(--c); font-weight: 600; border-color: var(--c); }
.framer { position: relative; display: block; width: 100%; aspect-ratio: 16 / 9; border: 1px solid var(--line-strong); border-radius: 4px; background: var(--bg-soft); cursor: crosshair; overflow: hidden; }
.kept { position: absolute; border: 2px solid var(--c); box-shadow: 0 0 0 999px rgba(0, 0, 0, .45); pointer-events: none; }
.thumb { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; border-radius: 4px; background: var(--bg-soft); display: block; }
.find { display: flex; flex-direction: column; gap: 6px; }
.find-links { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 12px; white-space: nowrap; }
.hint { margin: 0; font-size: 12.5px; color: var(--muted); line-height: 1.5; }
.remove { position: absolute; top: 12px; right: 12px; font-size: 18px; }

/* aperçu */
.aside { position: sticky; top: 12px; height: calc(100vh - 140px); min-height: 560px; display: flex; flex-direction: column; gap: 10px; }
.keys { margin: 0; font-size: 10.5px; color: var(--off); line-height: 1.6; }

@media (max-width: 1100px) {
  .body { grid-template-columns: 1fr; }
  .aside { position: static; order: -1; max-width: 640px; }
  .beat { grid-template-columns: 80px minmax(0, 1fr); }
  .how { grid-column: 2; flex-direction: row; flex-wrap: wrap; }
  .how > label { flex: 1 1 160px; }
}
</style>
