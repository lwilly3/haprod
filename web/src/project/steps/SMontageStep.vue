<script setup lang="ts">
/**
 * Montage d'un short : le short découpé par ffmpeg, habillé de sous-titres mot à mot et de slides
 * animées que Claude écrit et retouche à la demande (chat), puis rendu en MP4.
 * Un short = un projet du module animations, créé depuis la sélection (« Monter → »).
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import Seg from "../../components/Seg.vue";
import { api, del, post, putJson } from "../../lib/api";
import { usePolling } from "../../lib/composables";
import { mss } from "../../lib/format";
import { toast } from "../../lib/toast";
import { store } from "../store";
import MontageChat from "./shorts/MontageChat.vue";
import MontageStage from "./shorts/MontageStage.vue";
import {
  CAPTION_POSITIONS, CAPTION_STYLES, isActive,
  type CaptionGroup, type CaptionPosition, type CaptionStyle, type Montage, type Short, type Slide,
} from "./shorts/types";
import { useSelection, useWanted } from "./shorts/useSelection";

const { t: tr } = useI18n();
const route = useRoute();
const router = useRouter();
const project = computed(() => store.project!);
const S = useSelection(project);

// --- le short affiché (?short=)
const shortId = computed(() => (typeof route.query.short === "string" ? route.query.short : null));
const short = computed<Short | null>(() => S.shorts.value.find((s) => s.id === shortId.value)
  ?? S.shorts.value.find((s) => sent(s)) ?? S.shorts.value[0] ?? null);
const num = (s: Short) => String(S.shorts.value.indexOf(s) + 1).padStart(2, "0");
function openShort(s: Short) {
  router.replace({ query: { short: s.id } });
}

// --- son montage (projet animations)
const montage = ref<Montage | null>(null);
const busy = computed(() => isActive(montage.value?.status));
const rendering = computed(() => isActive(montage.value?.render?.status));

async function loadMontage() {
  const id = short.value?.project;
  if (!id) {
    montage.value = null;
    return;
  }
  const m = await api<Montage>(`/api/animations/jobs/${id}`);
  if (short.value?.project === id) montage.value = m;
}
usePolling(async () => {
  await loadMontage();
  return busy.value || rendering.value ? 1000 : 4000;
});
watch(() => short.value?.project, (id, old) => {
  if (id === old) return;
  montage.value = null;
  selectedId.value = null;
  t.value = 0;
  playing.value = false;
  loadMontage().catch(() => {});
});

function receive(m: Montage) {
  if (m.id === short.value?.project) montage.value = m;
}

async function call(path: string, method: "POST" | "PUT" | "DELETE", body?: unknown) {
  if (!montage.value) return;
  const url = `/api/animations/jobs/${montage.value.id}${path}`;
  try {
    receive(await (method === "DELETE" ? del<Montage>(url) : method === "PUT" ? putJson<Montage>(url, body) : post<Montage>(url, body)));
  } catch (e) {
    toast((e as Error).message, true);
  }
}

// envoyé au montage (« Monter → ») : sa vidéo se découpe, puis le montage se crée tout seul
const wanted = useWanted(project.value.id);
const sent = (s: Short) => !!s.project || wanted.value.includes(s.id);
const waiting = computed(() => !!short.value && !short.value.project && wanted.value.includes(short.value.id));
const opening = ref(false);

async function startMontage() {
  const s = short.value;
  if (!s || opening.value) return;
  if (!s.render?.url) {
    await S.cut(s.id);
    if (!wanted.value.includes(s.id)) wanted.value = [...wanted.value, s.id];
    return;
  }
  opening.value = true;
  if (await S.montage(s)) wanted.value = wanted.value.filter((id) => id !== s.id);
  opening.value = false;
}

// tous les shorts attendus dont la vidéo vient d'être prête, pas seulement celui affiché
const creating = new Set<string>();
watch(() => S.shorts.value.map((s) => `${s.id}:${!!s.render?.url}:${!!s.project}`).join(), async () => {
  for (const s of S.shorts.value) {
    if (!wanted.value.includes(s.id)) continue;
    if (s.project) {
      wanted.value = wanted.value.filter((id) => id !== s.id);
    } else if (s.render?.url && !creating.has(s.id)) {
      creating.add(s.id);
      if (s.id === short.value?.id) opening.value = true;
      if (await S.montage(s)) wanted.value = wanted.value.filter((id) => id !== s.id);
      creating.delete(s.id);
      opening.value = false;
    }
  }
}, { immediate: true });

/** L'attente avant le montage : découpe de la vidéo, puis création du montage. */
const prep = computed(() => {
  const r = short.value?.render;
  const failed = r?.status === "error" || r?.status === "cancelled";
  let cut = tr("shortEditing.prep.queued");
  if (r?.url) cut = tr("shortEditing.prep.done");
  else if (r?.status === "rendering") cut = tr("shortEditing.prep.progress", { pct: Math.round(r.progress * 100) });
  else if (failed) cut = r?.status === "error" ? tr("shortEditing.prep.failed", { error: r.error ?? "" }) : tr("shortEditing.prep.cancelled");
  return {
    cut, failed, pct: r?.url ? 1 : r?.status === "rendering" ? r.progress : 0,
    queued: !r?.url && !failed && r?.status !== "rendering",
  };
});

// --- lecture
const t = ref(0);
const playing = ref(false);
const total = computed(() => montage.value?.media.reduce((n, p) => Math.max(n, p.start + p.duration), 0) || short.value?.duration || 0);
const format = computed(() => montage.value?.settings.format ?? "short");

function onKey(e: KeyboardEvent) {
  if (e.code !== "Space" || e.repeat || e.ctrlKey || e.metaKey || e.altKey) return;
  const el = e.target as HTMLElement | null;
  if (el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))) return;
  e.preventDefault();
  if (el?.tagName === "BUTTON") el.blur();
  playing.value = !playing.value;
}
onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));

// --- slides
const slides = computed(() => montage.value?.slides ?? []);
const selectedId = ref<string | null>(null);
const slide = computed<Slide | null>(() => slides.value.find((s) => s.id === selectedId.value) ?? null);
const slideNo = (s: Slide) => String(slides.value.indexOf(s) + 1).padStart(2, "0");
const slideLabel = (s: Slide) => tr("shortEditing.slideLabel", { no: slideNo(s), title: s.title });

function pick(id: string) {
  const s = slides.value.find((x) => x.id === id);
  if (!s) return;
  playing.value = false;
  selectedId.value = s.id;
  t.value = Math.min(s.start + (s.end - s.start) * 0.6, s.end - 0.1);
}

const round = (n: number) => Math.round(n * 10) / 10;
const patch = (changes: Partial<Slide>) => slide.value && call(`/slides/${slide.value.id}`, "PUT", changes);
function moveStart(value: number) {
  const s = slide.value;
  if (!s || Number.isNaN(value) || round(value) === s.start) return;
  patch({ start: round(value), end: round(value + s.end - s.start) });
}
function setLength(value: number) {
  if (slide.value && value > 0) patch({ end: round(slide.value.start + value) });
}
function removeSlide() {
  const s = slide.value;
  if (s && confirm(tr("shortEditing.deleteSlideConfirm", { title: s.title }))) {
    selectedId.value = null;
    call(`/slides/${s.id}`, "DELETE");
  }
}

const chat = ref<InstanceType<typeof MontageChat>>();
const comment = () => chat.value?.compose();
const addAtCursor = () => chat.value?.compose(tr("shortEditing.addSlideAt", { tc: mss(t.value) }), true);

// --- sous-titres (ids envoyés au backend, libellés traduits)
const STYLE_OPTIONS = computed(() => CAPTION_STYLES.map((s) => [s, tr(`shortEditing.captionStyles.${s}`)] as const));
const POSITION_OPTIONS = computed(() => CAPTION_POSITIONS.map((p) => [p, tr(`shortEditing.captionPositions.${p}`)] as const));
const captionStyle = computed({
  get: () => montage.value?.captions?.style ?? "pop",
  set: (style: CaptionStyle) => call("/captions", "PUT", { style }),
});
const captionPosition = computed({
  get: () => montage.value?.captions?.position ?? "bas",
  set: (position: CaptionPosition) => call("/captions", "PUT", { position }),
});
// les groupes de mots, pour la piste de la timeline
const groups = ref<CaptionGroup[]>([]);
watch(() => montage.value?.captions?.url, async (url) => {
  if (!url || !montage.value) {
    groups.value = [];
    return;
  }
  try {
    const data = await api<{ groups: CaptionGroup[] }>(`/api/animations/jobs/${montage.value.id}/files/captions.json?v=${Date.now()}`);
    groups.value = data.groups ?? [];
  } catch {
    groups.value = [];
  }
}, { immediate: true });

// --- rendu final
async function startRender() {
  await call("/render", "POST");
}
async function stopRender() {
  if (montage.value) await post(`/api/animations/jobs/${montage.value.id}/render/stop`).catch(() => {});
}
watch(() => montage.value?.render?.status, (status, before) => {
  if (status === "done" && isActive(before)) toast(tr("shortEditing.rendered"));
});
const renderText = computed(() => {
  const r = montage.value?.render;
  if (!r) return "";
  if (r.status === "queued") return tr("shortEditing.render.queued");
  if (isActive(r.status)) return tr("shortEditing.render.progress", { stage: r.stage ?? tr("shortEditing.render.stage"), pct: Math.round(r.progress * 100) });
  if (r.status === "error") return tr("shortEditing.render.error", { error: r.error ?? "" });
  if (r.status === "cancelled") return tr("shortEditing.render.cancelled");
  return "";
});

// --- timeline
const P = (x: number) => `${total.value ? Math.max(0, Math.min(100, (x / total.value) * 100)) : 0}%`;
const ticks = computed(() => {
  const step = total.value > 120 ? 15 : total.value > 50 ? 10 : 5;
  return Array.from({ length: Math.floor(total.value / step) + 1 }, (_, i) => i * step);
});
/** Les extraits du short, à l'échelle de la vidéo montée (qui a un peu d'air autour de chacun). */
const parts = computed(() => {
  const clips = short.value?.clips ?? [];
  const sum = clips.reduce((n, c) => n + c.end - c.start, 0) || 1;
  let a = 0;
  return clips.map((c, i) => {
    const w = ((c.end - c.start) / sum) * total.value, o = a;
    a += w;
    return { start: o, dur: w, label: tr("shortEditing.part", { n: i + 1 }) };
  });
});
const partLabel = computed(() => {
  if (parts.value.length < 2) return "";
  const i = parts.value.findIndex((p) => t.value >= p.start && t.value < p.start + p.dur);
  return tr("shortEditing.partOf", { i: Math.max(0, i) + 1, n: parts.value.length });
});
const curGroup = computed(() => groups.value.findIndex((g) => {
  const a = g.words[0]?.start ?? 0, b = g.words.at(-1)?.end ?? 0;
  return t.value >= a && t.value < b;
}));

function seekAt(e: MouseEvent) {
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
  playing.value = false;
  t.value = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * total.value;
}
</script>

<template>
  <div class="screen">
    <div class="main">
      <div v-if="!S.loaded.value" class="eyebrow">{{ tr("common.loading") }}</div>
      <div v-else-if="!S.shorts.value.length" class="dashed-box">
        {{ tr("shortEditing.noShorts") }}
        <RouterLink :to="`/p/${project.id}/selection`">{{ tr("shortEditing.goToClips") }}</RouterLink>
      </div>

      <template v-else-if="short">
        <div class="tabs-row">
          <div class="short-tabs">
            <button v-for="s in S.shorts.value" :key="s.id" :class="{ on: s.id === short.id, off: !sent(s) }"
              :title="sent(s) ? s.title : tr('shortEditing.notSelected', { title: s.title })" @click="openShort(s)">{{ tr("shortEditing.shortTab", { n: num(s) }) }}</button>
          </div>
          <span class="short-title">{{ short.title }}</span>
        </div>

        <!-- pas encore de montage pour ce short -->
        <!-- envoyé au montage : la vidéo se découpe, le montage suit tout seul -->
        <div v-if="!short.project && (waiting || opening)" class="prep">
          <span class="prep-t">{{ tr("shortEditing.prep.title") }}</span>
          <div class="prep-step">
            <span class="prep-n mono">1</span>
            <div class="prep-body">
              <div class="prep-row"><span>{{ tr("shortEditing.prep.cut") }}</span><span class="mono prep-s" :class="{ err: prep.failed }">{{ prep.cut }}</span></div>
              <div class="progress" :class="{ indeterminate: prep.queued }"><div :style="{ width: `${prep.pct * 100}%` }" /></div>
              <button v-if="prep.failed" class="link-btn" @click="startMontage">{{ tr("shortEditing.prep.retryCut") }}</button>
            </div>
          </div>
          <div class="prep-step" :class="{ todo: !opening }">
            <span class="prep-n mono">2</span>
            <div class="prep-body">
              <div class="prep-row"><span>{{ tr("shortEditing.prep.captionsAndSlides") }}</span><span class="mono prep-s">{{ opening ? tr("shortEditing.prep.starting") : tr("shortEditing.prep.upcoming") }}</span></div>
            </div>
          </div>
          <span class="faint prep-hint">{{ tr("shortEditing.prep.hint") }}</span>
        </div>

        <!-- pas sélectionné pour le montage -->
        <div v-else-if="!short.project" class="dashed-box start">
          <span>{{ tr("shortEditing.notSelectedLong") }}</span>
          <button class="btn dark lg" @click="startMontage">{{ tr("shortEditing.editThisShort") }}</button>
        </div>

        <div v-else-if="!montage" class="eyebrow">{{ tr("shortEditing.loadingEdit") }}</div>

        <template v-else>
          <div class="work">
            <div class="player">
              <MontageStage
                v-model:t="t" v-model:playing="playing" :slides="slides" :selected-id="selectedId" :format="format"
                :media="montage.media" :captions="montage.captions" :busy="busy" :label="partLabel"
              />
              <div class="transport">
                <button class="btn ctl" :title="tr('shortEditing.backToStart')" @click="t = 0">⏮</button>
                <button class="btn dark play" @click="playing = !playing">{{ playing ? "❚❚" : "▶" }}</button>
                <span class="mono now">{{ mss(t) }}</span><span class="mono dim">/ {{ mss(total) }}</span>
              </div>
            </div>

            <fieldset class="panel" :disabled="busy">
              <div class="section">
                <span class="eyebrow">{{ tr("shortEditing.slide") }}</span>
                <template v-if="slide">
                  <span class="sel-label">{{ tr("shortEditing.slideHeader", { no: slideNo(slide), kind: slide.kind || tr("shortEditing.slideKind") }) }}<span v-if="slide.discarded" class="faint">{{ tr("shortEditing.discarded") }}</span></span>
                  <input :key="slide.id + slide.title" class="input" :value="slide.title" :title="tr('shortEditing.slideName')"
                    @change="patch({ title: ($event.target as HTMLInputElement).value })">
                  <div class="times">
                    <span class="mono">{{ mss(slide.start) }} → {{ mss(slide.end) }}</span>
                    <label>{{ tr("shortEditing.start") }} <input :key="slide.id + slide.start" class="input num" type="number" step="0.1" min="0" :value="slide.start"
                      @change="moveStart(+($event.target as HTMLInputElement).value)"></label>
                    <label>{{ tr("common.duration") }} <input :key="slide.id + slide.end" class="input num" type="number" step="0.5" min="0.5" :value="round(slide.end - slide.start)"
                      @change="setLength(+($event.target as HTMLInputElement).value)"></label>
                  </div>
                  <p v-if="slide.idea" class="idea">{{ slide.idea }}</p>
                  <div class="row">
                    <button class="btn" @click="comment">{{ tr("common.comment") }}</button>
                    <button class="link-btn" @click="patch({ discarded: !slide.discarded })">{{ slide.discarded ? tr("shortEditing.restore") : tr("common.dismiss") }}</button>
                    <button class="link-btn" @click="removeSlide">{{ tr("common.delete") }}</button>
                  </div>
                </template>
                <span v-else class="hint">{{ slides.length ? tr("shortEditing.hintPick") : busy ? tr("shortEditing.hintBusy") : tr("shortEditing.hintNone") }}</span>
              </div>

              <div class="section">
                <span class="eyebrow">{{ tr("shortEditing.captions") }}</span>
                <template v-if="montage.captions">
                  <Seg v-model="captionStyle" :options="STYLE_OPTIONS" size="sm" />
                  <Seg v-model="captionPosition" :options="POSITION_OPTIONS" size="sm" />
                  <span class="hint">{{ tr("shortEditing.captionsHint") }}</span>
                </template>
                <span v-else class="hint">{{ tr("shortEditing.noCaptions") }}</span>
              </div>

              <div class="section">
                <span class="eyebrow">{{ tr("shortEditing.finalVideo") }}</span>
                <div class="row">
                  <button v-if="rendering" class="btn" @click="stopRender">{{ tr("shortEditing.stopRender") }}</button>
                  <button v-else class="btn dark" :disabled="busy" @click="startRender">{{ montage.render?.url ? tr("shortEditing.renderAgain") : tr("shortEditing.renderShort") }}</button>
                  <a v-if="montage.render?.url && !rendering" class="btn" :href="`${montage.render.url}?download=1`">{{ tr("shortEditing.download") }}</a>
                </div>
                <div v-if="rendering" class="progress"><div :style="{ width: `${(montage.render?.progress ?? 0) * 100}%` }" /></div>
                <span v-if="renderText" class="hint mono" :class="{ err: montage.render?.status === 'error' }">{{ renderText }}</span>
                <span v-else-if="!montage.render" class="hint">{{ tr("shortEditing.renderHint") }}</span>
              </div>
            </fieldset>
          </div>

          <div class="timeline">
            <div class="tl-head">
              <span class="eyebrow">{{ tr("shortEditing.timeline") }}</span>
              <span class="spacer" />
              <button class="link-btn" :disabled="!montage.can_undo || busy" @click="call('/undo', 'POST')">{{ tr("shortEditing.undoLast") }}</button>
              <button class="btn sm" :disabled="busy" @click="addAtCursor">{{ tr("shortEditing.addSlide") }}</button>
            </div>
            <div class="grid">
              <span />
              <div class="ticks">
                <span v-for="k in ticks" :key="k" class="mono" :style="{ left: P(k) }">{{ mss(k) }}</span>
              </div>
              <span class="lane">{{ tr("shortEditing.lanes.slides") }}</span>
              <div class="track slides" @click="seekAt">
                <div v-for="s in slides" :key="s.id" class="slide" :class="{ on: s.id === selectedId, off: s.discarded, pending: !s.url }"
                  :style="{ left: P(s.start), width: P(s.end - s.start) }" :title="s.title" @click.stop="pick(s.id)">
                  <span>{{ s.title }}</span>
                </div>
              </div>
              <span class="lane">{{ tr("shortEditing.lanes.video") }}</span>
              <div class="track video" @click="seekAt">
                <div v-for="p in parts" :key="p.label" class="part mono" :style="{ left: P(p.start), width: P(p.dur) }">{{ p.label }}</div>
              </div>
              <span class="lane">{{ tr("shortEditing.lanes.captions") }}</span>
              <div class="track subs" @click="seekAt">
                <div v-for="(g, i) in groups" :key="i" class="sub" :class="{ on: i === curGroup }"
                  :style="{ left: P(g.words[0]?.start ?? 0), width: P((g.words.at(-1)?.end ?? 0) - (g.words[0]?.start ?? 0)) }">
                  {{ g.emoji }}{{ g.words.map((w) => w.text).join(" ") }}
                </div>
              </div>
              <div class="head" :style="{ left: `calc(86px + (100% - 86px) * ${total ? t / total : 0})` }" />
            </div>
          </div>
        </template>
      </template>
    </div>

    <MontageChat
      v-if="montage && short?.project" ref="chat" :montage="montage" :slide="slide" :slide-label="slideLabel"
      @updated="receive" @pick="pick" @stop="call('/stop', 'POST')"
    />
  </div>
</template>

<style scoped>
.screen { padding: 16px 24px 24px 32px; display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 24px; align-items: start; }
.main { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.dashed-box { display: flex; flex-direction: column; gap: 10px; align-items: center; }
.dashed-box.start span { max-width: 460px; }
.prep {
  display: flex; flex-direction: column; gap: 18px; padding: 28px; max-width: 560px;
  border: 1px dashed var(--dash); border-radius: 4px;
}
.prep-t { font-size: 15px; font-weight: 600; }
.prep-step { display: flex; gap: 12px; }
.prep-step.todo { color: var(--faint); }
.prep-n {
  width: 22px; height: 22px; flex-shrink: 0; border-radius: 11px; border: 1px solid currentColor;
  display: flex; align-items: center; justify-content: center; font-size: 11px;
}
.prep-body { flex: 1; display: flex; flex-direction: column; gap: 8px; padding-top: 2px; }
.prep-row { display: flex; justify-content: space-between; gap: 12px; font-size: 13.5px; }
.prep-s { font-size: 12px; color: var(--muted); text-align: right; }
.prep-s.err { color: var(--red-ink); }
.prep-body .link-btn { align-self: flex-start; font-size: 12.5px; }
.progress { overflow: hidden; }
.progress.indeterminate > div { width: 30% !important; animation: slide 1.2s infinite ease-in-out; }
@keyframes slide { from { transform: translateX(-100%); } to { transform: translateX(340%); } }
.prep-hint { font-size: 12.5px; line-height: 1.5; }

.tabs-row { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.short-tabs { display: flex; border: 1px solid var(--line-strong); border-radius: 4px; overflow: hidden; }
.short-tabs button { border: none; background: #fff; padding: 7px 12px; font-size: 13px; cursor: pointer; white-space: nowrap; color: var(--ink-2); }
.short-tabs button.off { color: var(--off); }
.short-tabs button.on { background: var(--ink); color: #fff; }
.short-title { font-size: 14.5px; font-weight: 600; }

.work { display: flex; gap: 28px; flex-wrap: wrap; align-items: flex-start; }
.player { display: flex; flex-direction: column; gap: 8px; }
.transport { display: flex; align-items: center; gap: 10px; }
.btn.ctl { width: 32px; padding: 0; font-size: 12px; }
.btn.play { width: 42px; padding: 0; font-size: 12px; }
.now { font-size: 12.5px; }
.dim { font-size: 12.5px; color: var(--faint); }

.panel { flex: 1; min-width: 240px; max-width: 420px; display: flex; flex-direction: column; gap: 22px; border: none; margin: 0; padding: 0; }
.panel:disabled { opacity: .7; }
.section { display: flex; flex-direction: column; gap: 10px; }
.section + .section { border-top: 1px solid var(--line-soft); padding-top: 16px; }
.section .eyebrow { font-size: 10.5px; }
.sel-label { font-size: 13px; font-weight: 600; }
.section .input { height: 38px; padding: 0 10px; }
.times { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; font-size: 12.5px; color: var(--muted); }
.times .mono { font-size: 12px; }
.times label { display: flex; align-items: center; gap: 6px; }
.input.num { width: 74px; height: 30px; font-size: 13px; padding: 0 8px; }
.idea { margin: 0; font-size: 12.5px; color: var(--muted); line-height: 1.45; }
.row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.row a.btn { color: var(--ink); text-decoration: none; }
.row .link-btn { font-size: 12.5px; }
.hint { font-size: 13px; color: var(--faint); line-height: 1.5; }
.hint.mono { font-size: 12px; }
.hint.err { color: var(--red-ink); }

.timeline { display: flex; flex-direction: column; gap: 8px; border-top: 1px solid var(--line); padding-top: 12px; }
.tl-head { display: flex; align-items: center; gap: 12px; }
.tl-head .link-btn { font-size: 12px; }
.grid { position: relative; display: grid; grid-template-columns: 76px minmax(0, 1fr); gap: 6px 10px; align-items: center; }
.ticks { position: relative; height: 14px; }
.ticks span { position: absolute; font-size: 10px; color: var(--faint); transform: translateX(-50%); }
.ticks span:first-child { transform: none; }
.lane { font-size: 12px; color: var(--muted); }
.track { position: relative; cursor: pointer; }
.track.slides { height: 40px; background: var(--bg-soft); border-radius: 3px; }
.slide {
  position: absolute; top: 4px; bottom: 4px; background: #fff; color: var(--ink); border: 1px solid var(--dash);
  border-radius: 3px; font-size: 11px; font-weight: 600; padding: 0 6px; display: flex; align-items: center;
  overflow: hidden; white-space: nowrap;
}
.slide span { overflow: hidden; text-overflow: ellipsis; }
.slide.pending { border-style: dashed; }
.slide.off { opacity: .45; }
.slide.on { background: var(--ink); color: #fff; border-color: var(--ink); }
.track.video { height: 30px; }
.part {
  position: absolute; top: 0; bottom: 0; background: var(--ink-3); border-right: 2px solid #fff; color: #fff;
  font-size: 10.5px; padding: 0 6px; display: flex; align-items: center; overflow: hidden; white-space: nowrap;
}
.track.subs { height: 24px; }
.sub {
  position: absolute; top: 0; bottom: 0; background: var(--line-soft); border-right: 1px solid #fff; font-size: 10px;
  color: var(--ink-2); padding: 0 4px; display: flex; align-items: center; overflow: hidden; white-space: nowrap;
}
.sub.on { background: var(--red-bg); }
.head { position: absolute; top: 16px; bottom: 0; width: 2px; margin-left: -1px; background: var(--red); pointer-events: none; }
</style>
