<script setup lang="ts">
/**
 * Le prompteur, pensé pour le téléphone, en trois écrans : le projet, puis le texte à dire (tout, ou
 * celui d'un setup : ?t=), puis le texte qui défile sur fond noir, en miroir si besoin. Se pilote au
 * toucher ou au clavier — une télécommande Bluetooth qui simule des touches marche pareil.
 */
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import { api } from "../lib/api";
import { usePref } from "../lib/composables";
import { duration } from "../lib/format";
import { wordCount } from "../project/steps/script/markdown";
import { letterOf, setupColor, spoken, type Spoken } from "../project/steps/script/setups";
import type { Block } from "../project/steps/script/useScript";
import type { Plan, ProjectSummary, Setup } from "../project/types";

const { t } = useI18n();
const route = useRoute();
const pid = typeof route.params.pid === "string" ? route.params.pid : null;
/** le texte choisi : "all", l'id d'un setup, ou "none" (le texte sans setup) ; null : pas encore choisi */
const wanted = typeof route.query.t === "string" ? route.query.t : null;

// --- Les projets et le texte ---------------------------------------------------------------

const projects = shallowRef<ProjectSummary[]>([]);
const title = computed(() => projects.value.find((p) => p.id === pid)?.title ?? "");
const setups = shallowRef<Setup[]>([]);
const parts = shallowRef<Spoken[]>([]);
const loaded = ref(false);
const error = ref("");

onMounted(async () => {
  try {
    const list = await api<ProjectSummary[]>("/api/projects");
    projects.value = [...list].sort((a, b) => (b.opened_at || b.updated_at) - (a.opened_at || a.updated_at));
    if (pid) {
      const data = await api<{ blocks: Block[]; plans: Plan[]; setups: Setup[]; sections: Record<string, string> }>(
        `/api/projects/${pid}/script`);
      setups.value = data.setups;
      parts.value = spoken(data.blocks, data.plans, data.sections);
    }
  } catch (e) {
    error.value = (e as Error).message;
  }
  loaded.value = true;
});

const indexOf = computed(() => new Map(setups.value.map((s, i) => [s.id, i])));
const seconds = (list: Spoken[]) => (list.reduce((n, s) => n + wordCount(s.text), 0) / 150) * 60;
const partsOf = (id: string) => (id === "all" ? parts.value : parts.value.filter((s) => s.setup === (id === "none" ? "" : id)));

const choices = computed(() => {
  const out = [{ id: "all", label: t("prompter.allText"), letter: "", color: "", seconds: seconds(parts.value) }];
  setups.value.forEach((st, n) => {
    const list = partsOf(st.id);
    if (list.length) out.push({ id: st.id, label: st.name || t("prompter.setup", { letter: letterOf(n) }), letter: letterOf(n), color: setupColor(n), seconds: seconds(list) });
  });
  const none = partsOf("none");
  if (none.length && setups.value.length) out.push({ id: "none", label: t("prompter.noSetup"), letter: "", color: "", seconds: seconds(none) });
  return out;
});
/** le texte à dire ; null (choix absent ou setup supprimé depuis) : on affiche les choix */
const source = computed(() => (wanted && choices.value.some((c) => c.id === wanted) ? wanted : null));
const shown = computed(() => (source.value ? partsOf(source.value) : []));

/** En mode "tout", la pastille du setup quand il change d'un paragraphe à l'autre. */
const badge = (i: number) => {
  if (source.value !== "all") return null;
  const id = shown.value[i].setup;
  if (!id || (i > 0 && shown.value[i - 1].setup === id)) return null;
  const n = indexOf.value.get(id);
  return n == null ? null : { letter: letterOf(n), color: setupColor(n) };
};

// --- Réglages (gardés sur l'appareil) ------------------------------------------------------

const speed = usePref("prompteur.speed", 6);
const size = usePref("prompteur.size", 44);
const margin = usePref("prompteur.margin", 6);
const mirrorH = usePref("prompteur.mirrorH", false);
const mirrorV = usePref("prompteur.mirrorV", false);
const guide = usePref("prompteur.guide", true);
const LINE = 1.4;
const settings = ref(false);

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
/** vitesse 10 = une ligne par seconde */
const pxPerSecond = computed(() => (speed.value * size.value * LINE) / 10);

// --- Défilement ----------------------------------------------------------------------------

const textEl = ref<HTMLElement>();
const paras = ref<HTMLElement[]>([]);
/** de combien le texte est monté (px) ; 0 : le début du texte sur la ligne de lecture */
const offset = ref(0);
const height = ref(0);
const viewH = ref(window.innerHeight);
const guideY = computed(() => Math.round(viewH.value * 0.3));
const playing = ref(false);

const setOffset = (v: number) => { offset.value = clamp(v, 0, height.value); };
const remaining = computed(() => (height.value - offset.value) / pxPerSecond.value);
const progress = computed(() => (height.value ? offset.value / height.value : 0));

let raf = 0;
let last = 0;
function frame(t: number): void {
  const dt = last ? (t - last) / 1000 : 0;
  last = t;
  setOffset(offset.value + pxPerSecond.value * dt);
  if (offset.value >= height.value) playing.value = false;
  else raf = requestAnimationFrame(frame);
}
watch(playing, (on) => {
  cancelAnimationFrame(raf);
  last = 0;
  if (on) {
    settings.value = false;
    raf = requestAnimationFrame(frame);
  }
});
function toggle(): void {
  if (!playing.value && offset.value >= height.value) offset.value = 0;
  playing.value = !playing.value;
}

/** Fait monter (-1) ou descendre (1) le texte de deux lignes. */
const step = (dir: 1 | -1) => setOffset(offset.value + dir * 2 * size.value * LINE);

/** Saute au paragraphe suivant (1) ou précédent (-1). */
function jump(dir: 1 | -1): void {
  const tops = paras.value.map((el) => el.offsetTop).sort((a, b) => a - b);
  const target = dir > 0 ? tops.find((t) => t > offset.value + 2) : [...tops].reverse().find((t) => t < offset.value - 2);
  setOffset(target ?? (dir > 0 ? height.value : 0));
}

// --- Indicateur passager (vitesse…) ---------------------------------------------------------

const flash = ref("");
let flashTimer: ReturnType<typeof setTimeout> | undefined;
function show(text: string): void {
  flash.value = text;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => (flash.value = ""), 900);
}
function faster(d: number): void {
  speed.value = clamp(speed.value + d, 1, 30);
  show(t("prompter.speedFlash", { n: speed.value }));
}

// --- Clavier / télécommande ----------------------------------------------------------------

const testing = ref(false);
const keys = ref<string[]>([]);
/** touches qu'on peut laisser enfoncées */
const REPEAT = ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"];
const ACTIONS: Record<string, () => void> = {
  " ": toggle, Enter: toggle, MediaPlayPause: toggle,
  ArrowUp: () => step(-1), ArrowDown: () => step(1),
  ArrowRight: () => faster(1), ArrowLeft: () => faster(-1),
  PageDown: () => jump(1), PageUp: () => jump(-1),
  Home: () => setOffset(0),
};
function onKey(e: KeyboardEvent): void {
  if (testing.value) keys.value = [`${e.key === " " ? t("prompter.space") : e.key}  ·  ${e.code || "—"}`, ...keys.value].slice(0, 8);
  const action = ACTIONS[e.key];
  if (!source.value || !action || (e.repeat && !REPEAT.includes(e.key))) return;
  e.preventDefault();
  // sinon le bouton qui a le focus se déclencherait aussi
  (document.activeElement as HTMLElement | null)?.blur();
  action();
}

// --- Toucher -------------------------------------------------------------------------------

let drag: { y: number; offset: number; moved: boolean } | null = null;
function down(e: PointerEvent): void {
  drag = { y: e.clientY, offset: offset.value, moved: false };
}
function move(e: PointerEvent): void {
  if (!drag) return;
  const dy = e.clientY - drag.y;
  if (Math.abs(dy) > 8) drag.moved = true;
  // texte retourné verticalement : le geste s'inverse
  if (drag.moved) setOffset(drag.offset - dy * (mirrorV.value ? -1 : 1));
}
/** Un toucher sans glisser : ferme les réglages s'ils sont ouverts, sinon lecture / pause. */
function up(): void {
  if (drag && !drag.moved) {
    if (settings.value) settings.value = false;
    else toggle();
  }
  drag = null;
}
const wheel = (e: WheelEvent) => setOffset(offset.value + e.deltaY);

// --- Écran ---------------------------------------------------------------------------------

/**
 * Garder l'écran allumé : Wake Lock, qui n'existe qu'en HTTPS. Safari peut exiger un geste et relâche
 * le verrou quand on quitte l'app : on le redemande à chaque toucher ou touche s'il n'est pas tenu.
 */
let lock: WakeLockSentinel | null = null;
async function keepAwake(): Promise<void> {
  if (lock || document.visibilityState !== "visible" || !("wakeLock" in navigator)) return;
  try {
    lock = await navigator.wakeLock.request("screen");
    lock.addEventListener("release", () => { lock = null; });
  } catch { /* HTTP, ou refusé */ }
}
const canFullscreen = document.fullscreenEnabled;
const fullscreen = () => (document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen());

const onResize = () => { viewH.value = window.innerHeight; };
let observer: ResizeObserver | undefined;
watch(textEl, (el) => {
  observer?.disconnect();
  if (!el) return;
  observer = new ResizeObserver(() => {
    height.value = el.offsetHeight;
    setOffset(offset.value);
  });
  observer.observe(el);
});

onMounted(() => {
  window.addEventListener("keydown", onKey);
  window.addEventListener("keydown", keepAwake);
  window.addEventListener("pointerdown", keepAwake);
  window.addEventListener("resize", onResize);
  document.addEventListener("visibilitychange", keepAwake);
  keepAwake();
});
onUnmounted(() => {
  cancelAnimationFrame(raf);
  observer?.disconnect();
  window.removeEventListener("keydown", onKey);
  window.removeEventListener("keydown", keepAwake);
  window.removeEventListener("pointerdown", keepAwake);
  window.removeEventListener("resize", onResize);
  document.removeEventListener("visibilitychange", keepAwake);
  lock?.release().catch(() => {});
});
</script>

<template>
  <!-- 1. le projet -->
  <div v-if="!pid" class="prompteur page">
    <h1>{{ t("prompter.title") }}</h1>
    <p v-if="error" class="error">{{ error }}</p>
    <RouterLink v-for="p in projects" :key="p.id" class="item" :to="`/prompteur/${p.id}`">{{ p.title || t("common.untitled") }}</RouterLink>
    <p v-if="loaded && !projects.length && !error" class="dim">{{ t("prompter.noProjects") }}</p>
  </div>

  <!-- 2. le texte à dire -->
  <div v-else-if="!source" class="prompteur page">
    <RouterLink to="/prompteur" class="back">{{ t("prompter.back") }}</RouterLink>
    <h1>{{ title }}</h1>
    <p v-if="error" class="error">{{ error }}</p>
    <template v-else-if="loaded">
      <RouterLink v-for="c in choices" :key="c.id" class="item choice" :to="{ query: { t: c.id } }">
        <span class="badge" :style="{ background: c.color || 'transparent' }">{{ c.letter }}</span>
        <span class="label">{{ c.label }}</span>
        <span class="mono dim">{{ duration(c.seconds) }}</span>
      </RouterLink>
      <p v-if="!parts.length" class="dim">{{ t("prompter.emptyScript") }}</p>
    </template>
  </div>

  <!-- 3. le prompteur -->
  <div v-else class="prompteur">
    <!-- le texte, seul à passer en miroir -->
    <div class="viewport" :style="{ transform: `scale(${mirrorH ? -1 : 1}, ${mirrorV ? -1 : 1})` }"
      @pointerdown="down" @pointermove="move" @pointerup="up" @pointercancel="drag = null" @wheel.passive="wheel">
      <div ref="textEl" class="text" :style="{
        transform: `translateY(${guideY - offset}px)`, fontSize: size + 'px', lineHeight: LINE,
        paddingLeft: margin + '%', paddingRight: margin + '%',
      }">
        <p v-for="(s, i) in shown" :key="i" ref="paras">
          <span v-if="badge(i)" class="badge" :style="{ background: badge(i)!.color }">{{ badge(i)!.letter }}</span>{{ s.text }}
        </p>
      </div>
      <div v-if="guide" class="guide" :style="{ top: guideY + 'px', height: size * LINE + 'px' }" />
      <div class="progress" :style="{ width: progress * 100 + '%' }" />
      <div v-if="flash" class="flash">{{ flash }}</div>
    </div>

    <div v-if="testing" class="keys">
      <div class="keys-title">{{ t("prompter.keysReceived") }}</div>
      <div v-for="(k, i) in keys" :key="i" class="mono">{{ k }}</div>
      <div v-if="!keys.length" class="dim">{{ t("prompter.pressRemote") }}</div>
    </div>

    <div v-if="settings" class="settings" @pointerdown.stop>
      <div class="row">
        <div class="stepper"><span>{{ t("prompter.speed") }}</span><button @click="speed = clamp(speed - 1, 1, 30)">−</button><b class="mono">{{ speed }}</b><button @click="speed = clamp(speed + 1, 1, 30)">+</button></div>
        <div class="stepper"><span>{{ t("prompter.size") }}</span><button @click="size = clamp(size - 4, 20, 120)">−</button><b class="mono">{{ size }}</b><button @click="size = clamp(size + 4, 20, 120)">+</button></div>
        <div class="stepper"><span>{{ t("prompter.margins") }}</span><button @click="margin = clamp(margin - 2, 0, 30)">−</button><b class="mono">{{ margin }}</b><button @click="margin = clamp(margin + 2, 0, 30)">+</button></div>
      </div>
      <div class="row">
        <button class="chip" :class="{ on: mirrorH }" @click="mirrorH = !mirrorH">{{ t("prompter.mirrorH") }}</button>
        <button class="chip" :class="{ on: mirrorV }" @click="mirrorV = !mirrorV">{{ t("prompter.mirrorV") }}</button>
        <button class="chip" :class="{ on: guide }" @click="guide = !guide">{{ t("prompter.guide") }}</button>
        <button class="chip" :class="{ on: testing }" @click="testing = !testing; keys = []">{{ t("prompter.keyTest") }}</button>
        <button v-if="canFullscreen" class="chip" @click="fullscreen">{{ t("prompter.fullscreen") }}</button>
      </div>
      <div class="row">
        <button class="chip" @click="setOffset(0)">{{ t("prompter.toStart") }}</button>
        <RouterLink class="chip" :to="{ query: {} }">{{ t("prompter.chooseText") }}</RouterLink>
      </div>
    </div>

    <div class="corner" @pointerdown.stop>
      <span v-if="!playing" class="mono dim">{{ duration(remaining) }}</span>
      <button class="gear" :class="{ on: settings }" :title="t('prompter.settings')" @click="settings = !settings">⚙</button>
    </div>
  </div>
</template>

<style scoped>
.prompteur {
  position: fixed; inset: 0; background: #000; color: #fff; overflow: hidden;
  font-family: var(--sans); -webkit-user-select: none; user-select: none;
}
.dim { color: rgba(255, 255, 255, 0.5); }
.error { color: #ff8a8a; }
.mono { font-family: var(--mono); }

/* écrans de choix */
.page {
  overflow-y: auto; padding: calc(24px + env(safe-area-inset-top)) 20px 40px;
  display: flex; flex-direction: column; gap: 4px;
}
.page h1 { font-size: 28px; margin: 0 0 16px; }
.back { color: rgba(255, 255, 255, 0.6); text-decoration: none; font-size: 15px; margin-bottom: 12px; }
.item {
  color: #fff; text-decoration: none; font-size: 19px; padding: 14px 4px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.12);
}
.choice { display: flex; align-items: center; gap: 12px; }
.choice .label { flex: 1; min-width: 0; }
.choice .badge { font-size: 15px; width: 26px; height: 26px; margin: 0; border-radius: 5px; }

/* le texte */
.viewport { position: absolute; inset: 0; touch-action: none; }
.text { position: absolute; left: 0; right: 0; top: 0; font-weight: 500; will-change: transform; }
.text p { margin: 0 0 0.9em; }
.badge {
  display: inline-flex; align-items: center; justify-content: center; vertical-align: middle; flex-shrink: 0;
  width: 1.1em; height: 1.1em; border-radius: 0.15em; font-size: 0.55em; margin-right: 0.4em; color: #fff;
}
.guide {
  position: absolute; left: 0; right: 0; pointer-events: none;
  background: rgba(255, 255, 255, 0.07); border-top: 1px solid rgba(255, 255, 255, 0.18);
  border-bottom: 1px solid rgba(255, 255, 255, 0.18);
}
.progress { position: absolute; left: 0; top: 0; height: 3px; background: rgba(255, 255, 255, 0.35); }
.flash {
  position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); pointer-events: none;
  background: rgba(40, 40, 40, 0.9); padding: 12px 20px; border-radius: 10px; font-size: 22px;
}

.keys {
  position: absolute; right: 12px; top: calc(12px + env(safe-area-inset-top)); z-index: 2;
  background: rgba(30, 30, 30, 0.95); padding: 10px 14px; border-radius: 8px; font-size: 14px;
  display: flex; flex-direction: column; gap: 4px; min-width: 200px;
}
.keys-title { font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: rgba(255, 255, 255, 0.5); }

/* réglages : la roue en bas à droite, le panneau au-dessus */
.corner {
  position: absolute; right: calc(12px + env(safe-area-inset-right)); bottom: calc(12px + env(safe-area-inset-bottom));
  z-index: 2; display: flex; align-items: center; gap: 10px; font-size: 13px;
}
.gear {
  width: 40px; height: 40px; border-radius: 20px; border: none; padding: 0; cursor: pointer;
  background: rgba(255, 255, 255, 0.08); color: rgba(255, 255, 255, 0.45); font-size: 22px; line-height: 40px;
}
.gear.on { background: #fff; color: #000; }
.settings {
  position: absolute; left: 0; right: 0; bottom: 0; z-index: 1;
  background: rgba(22, 22, 22, 0.94); border-top: 1px solid rgba(255, 255, 255, 0.12);
  padding: 12px 64px calc(12px + env(safe-area-inset-bottom)) 14px;
  display: flex; flex-direction: column; gap: 10px; font-size: 15px;
}
.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.chip {
  height: 34px; padding: 0 12px; border-radius: 17px; border: 1px solid rgba(255, 255, 255, 0.2);
  background: transparent; color: #fff; font: inherit; font-size: 14px; cursor: pointer;
  display: inline-flex; align-items: center; text-decoration: none;
}
.chip.on { background: #fff; color: #000; }
.stepper { display: flex; align-items: center; gap: 6px; margin-right: 8px; }
.stepper span { color: rgba(255, 255, 255, 0.6); font-size: 13px; margin-right: 2px; }
.stepper b { min-width: 28px; text-align: center; font-weight: 500; }
.stepper button {
  width: 34px; height: 34px; border-radius: 17px; border: 1px solid rgba(255, 255, 255, 0.2);
  background: transparent; color: #fff; font-size: 20px; cursor: pointer; padding: 0;
}
</style>
