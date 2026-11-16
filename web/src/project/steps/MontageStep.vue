<script setup lang="ts">
/**
 * Montage de la vidéo longue : l'atelier du monteur. Aperçu, inspecteur, timeline zoomable, et le chat
 * où le monteur (Claude) reçoit les demandes : elles se mettent en file, chacune avec sa conversation, et
 * il en traite plusieurs à la fois, chacune sur sa copie de la timeline, pendant que le client continue de monter.
 * Tout s'exporte en FCPXML dans le dossier du projet, que DaVinci Resolve ouvre tel quel.
 *
 * Raccourcis (conventions de Resolve) : Espace lecture, J/K/L, ←/→ image par image (Maj : 1 s),
 * ↑/↓ coupe précédente / suivante, A sélection, B lame, Ctrl+B couper à la tête, Suppr supprimer,
 * M beat (posé à la tête de lecture, à tirer sur son passage), I/O plage, Alt+X effacer la plage, Alt+molette ou +/− zoom, Ctrl+molette déplacer la tête, Maj+Z ajuster, Ctrl+Z annuler.
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api, post } from "../../lib/api";
import { toast } from "../../lib/toast";
import { store } from "../store";
import { usePlaylist, type Piece } from "./derush/usePlaylist";
import BeatPanel from "./montage/BeatPanel.vue";
import type { ImageTab } from "./montage/BeatImageModal.vue";
import FindSaid from "./montage/FindSaid.vue";
import ImageSearchQueue from "./montage/ImageSearchQueue.vue";
import Inspector from "./montage/Inspector.vue";
import MonteurChat from "./montage/MonteurChat.vue";
import TaskQueue from "./montage/TaskQueue.vue";
import { addMedia, bladeAroll, bladeItem, frameStep, insertAroll, isVideo, pauseMotion, remove, unpauseMotion, type Shift } from "./montage/ops";
import Preview from "./montage/Preview.vue";
import StylePicker from "./montage/StylePicker.vue";
import Timeline from "./montage/Timeline.vue";
import { clipStarts, fxSpan, isImage, needsAnim, spanOf, tcd, trackLabel, TYPE_COLOR, type AnimState, type Beat, type AvailableMedia, type Broll, type MontageTask, type Motion, type Selection, type Shot, type Timeline as TL, type Track } from "./montage/types";
import { useMontage } from "./montage/useMontage";
import { useStoryboard } from "./montage/useStoryboard";

const { t: tr } = useI18n();
const project = computed(() => store.project!);
const M = useMontage(project.value.id);
const view = M.view;
const tl = M.tl;

// --- lecture : les clips de l'A-roll bout à bout, dans la vidéo source ou le média inséré
const pieces = computed<Piece[]>(() => (view.value?.source && tl.value
  ? tl.value.aroll.map((c) => ({ src: c.src ? mediaUrl(c.src) : view.value!.source!.url, start: c.in, end: c.out, on: true }))
  : []));
// un clip tout juste inséré : son adresse dans la liste des médias, le temps que le serveur la renvoie
const mediaUrl = (src: string) => view.value?.media[src]?.url ?? M.available.value.find((m) => m.src === src)?.url ?? "";
const player = usePlaylist(pieces);
const t = computed(() => player.t.value);
const seek = (s: number) => player.seek(Math.max(0, Math.min(s, M.total.value)));

// --- forme d'onde
const peaks = ref<number[] | null>(null);
watch(() => view.value?.analysis.peaks, async (url) => {
  peaks.value = url ? await api<number[]>(url).catch(() => null) : null;
}, { immediate: true });

const selection = ref<Selection | null>(null);
const tool = ref<"select" | "blade">("select");
const timeline = ref<InstanceType<typeof Timeline>>();
const chat = ref<InstanceType<typeof MonteurChat>>();
const preview = ref<InstanceType<typeof Preview>>();

function edit(change: (t: TL) => void) {
  M.edit(change, 800);
}

// --- textes : sélectionnés et déplacés depuis l'aperçu
const textSel = computed(() => (selection.value && "item" in selection.value && selection.value.item.track === "texts" ? selection.value.item.id : null));
function moveText(id: string, x: number, y: number) {
  edit((tl) => { const it = tl.texts.find((k) => k.id === id); if (it) Object.assign(it, { x, y }); });
}

function blade(track: Track, id: string, at: number) {
  let created: string | null = null;
  M.edit((x) => { created = track === "aroll" || !id ? bladeAroll(x, at) : bladeItem(x, track, id, at); });
  if (!created) toast(tr("editing.nothingToCut"));
}

/**
 * Insère une vidéo entière dans l'A-roll à l'instant `at` : tout ce qui suit est décalé d'autant, beats du storyboard
 * compris (par le serveur, qui sait le défaire avec Ctrl+Z ; le storyboard est relu ensuite).
 */
async function insertClip(m: AvailableMedia, at: number) {
  if (!isVideo(m)) {
    toast(tr("editing.insertNotVideo"), true);
    return;
  }
  const len = Math.round((m.duration ?? 4) * 1000) / 1000;
  let done: { id: string; at: number } | null = null as { id: string; at: number } | null;
  M.edit((x) => { done = insertAroll(x, at, { src: m.src, in: 0, out: len }); }, 0);
  if (!done) return;
  const from = done.at;
  M.shiftBeats(from, len);
  selection.value = { item: { track: "aroll", id: done.id } };
  seek(from);
  toast(tr("editing.inserted", { name: m.name, tc: tcd(from) }));
  await M.flush();
  await SB.load();
}

/**
 * Met l'A-roll en pause sous un motion (on) ou retire sa pause : la suite est décalée d'autant, beats du storyboard
 * compris (relu ensuite).
 */
async function setPause(id: string, on: boolean) {
  let shifts: Shift[] = [];
  M.edit((x) => { shifts = on ? pauseMotion(x, id) : [unpauseMotion(x, id)].filter((v): v is Shift => !!v); }, 0);
  if (!shifts.length) return;
  for (const s of shifts) M.shiftBeats(s.at, s.length);
  const len = shifts[shifts.length - 1].length;
  toast(on ? tr("editing.paused", { dur: `${len.toFixed(1)} s` }) : tr("editing.unpaused"));
  await M.flush();
  await SB.load();
}

/** Un média lâché sur la timeline : dans l'A-roll sur sa piste, sinon posé au-dessus (B-roll, son). */
function dropMedia(m: AvailableMedia, at: number, aroll: boolean) {
  if (aroll) return insertClip(m, at);
  let added = null as ReturnType<typeof addMedia> | null;
  M.edit((x) => { added = addMedia(x, m, at); });
  if (added) selection.value = { item: added };
}

function describe(s: Selection): string {
  if ("range" in s) return tr("editing.range", { from: tcd(s.range[0]), to: tcd(s.range[1]) });
  const span = tl.value ? (s.item.fx ? fxSpan(tl.value, s.item.track, s.item.id, s.item.fx) : spanOf(tl.value, s.item.track, s.item.id)) : null;
  const what = `${trackLabel(s.item.track)} ${s.item.id}`;
  return `${s.item.fx ? tr("transitions.of", { item: what }) : what}${span ? ` · ${tcd(span[0])}` : ""}`;
}

function pick(s: Selection) {
  selection.value = s;
  const span = "range" in s ? s.range : tl.value ? spanOf(tl.value, s.item.track, s.item.id) : null;
  if (span) seek(span[0]);
}

// --- les demandes à Daryl : celle dont on voit la conversation (null : une nouvelle demande)
const current = ref<string | null>(null);
const task = computed(() => view.value?.tasks.find((x) => x.id === current.value) ?? null);
// à l'ouverture : la dernière demande
watch(() => !!view.value, (ready) => { if (ready) current.value = view.value!.tasks.at(-1)?.id ?? null; }, { once: true });

async function send(text: string, sel: Selection | null, shot: Shot | null) {
  if (player.playing.value) player.toggle();
  const id = await M.send(text, sel, shot, task.value?.id ?? null);
  if (id) current.value = id;
}

/** Une nouvelle demande, pendant que les autres attendent ou tournent. */
async function newRequest() {
  current.value = null;
  await nextTick();
}

/** Ouvre une demande de la file : sa conversation, et sa portée dans la timeline. */
function openTask(x: MontageTask) {
  current.value = x.id;
  const first = x.messages.find((m) => m.role === "user");
  if (first?.selection) pick(first.selection);
  else if (first?.frame != null) seek(first.frame);
}

/** Discuter de l'image en pause : l'aperçu capturé tel qu'on le voit, dans une nouvelle demande. */
async function discussFrame() {
  const at = t.value;
  const image = await preview.value?.capture().catch(() => null) ?? null;
  await newRequest();
  chat.value?.frame({ t: at, image });
}

/** Commenter, demandes de l'inspecteur : une nouvelle demande sur la sélection. */
async function comment(text?: string) {
  await newRequest();
  chat.value?.compose(text ?? "");
}

// --- storyboard : les beats cochés pas encore faits, en pointillés sur la piste des beats et en slide sur l'aperçu ;
// on crée leur animation un par un (pour tester vite) ou tous d'un coup ; zooms et B-roll vidéo se posent tels quels.
// On en pose aussi à la main (M) : un motion à sa consigne vide, qu'on tire sur son passage et qu'on écrit sur sa slide
const SB = useStoryboard(project.value.id);
const pending = computed(() => (SB.view.value?.board?.beats ?? [])
  .filter((b) => b.on && !SB.view.value?.composed[b.id]));
const ghosts = computed(() => pending.value.map((b) => ({
  id: b.id, at: b.at, dur: b.dur, on: b.on, label: b.show || tr(`editing.storyboard.types.${b.type}`), color: TYPE_COLOR[b.type],
})));
/** le beat sélectionné sur la timeline (sa fiche remplace l'inspecteur) */
const beatSel = ref<string | null>(null);
const selBeat = computed(() => pending.value.find((b) => b.id === beatSel.value) ?? null);
function openBeat(id: string) {
  beatSel.value = id;
  selection.value = null;
}
watch(selection, (s) => { if (s) beatSel.value = null; });
/** la popup des images du beat sélectionné, et son onglet */
const imagePopup = ref<ImageTab | null>(null);
watch(beatSel, () => { imagePopup.value = null; });
/** les recherches d'images des beats encore à faire, dans la file à côté du chat */
const imageJobs = computed(() => pending.value
  .filter((b) => SB.view.value?.image_jobs?.[b.id])
  .map((b) => ({ beat: b, job: SB.view.value!.image_jobs[b.id] })));
/** rouvre la popup d'un beat sur sa recherche */
async function openSearch(id: string) {
  openBeat(id);
  await nextTick();
  imagePopup.value = "search";
}
/** un beat déplacé ou tiré sur la timeline (enregistré au lâcher) */
function moveBeat(id: string, at: number, dur: number) {
  SB.edit((list) => { const b = list.find((x) => x.id === id); if (b) Object.assign(b, { at, dur }); }, 60_000);
}
function changeBeat(id: string, change: (b: Beat) => void, delay = 150) {
  SB.edit((list) => { const b = list.find((x) => x.id === id); if (b) change(b); }, delay);
}
/** un beat à la tête de lecture, sur la plage sélectionnée s'il y en a une */
async function addBeat() {
  const r = selection.value && "range" in selection.value ? selection.value.range : null;
  const at = r ? r[0] : Math.min(t.value, Math.max(0, M.total.value - 1));
  const id = await SB.add(at, r ? r[1] - r[0] : 3);
  if (id) openBeat(id);
}
/** parler d'un beat à Daryl, le monteur */
function askBeat(id: string) {
  const b = pending.value.find((x) => x.id === id);
  if (!b) return;
  comment(tr("editing.beat.askText", { id, tc: tcd(b.at) }));
}
/** une image tout juste importée n'est connue qu'une fois les médias relus */
async function knowMedia(srcs: string[]) {
  if (srcs.some((s) => !SB.view.value?.visuals.some((v) => v.src === s))) {
    await SB.flush();
    await SB.load();
  }
}
/** le média d'un B-roll (comme au Storyboard : une image va en plein écran ou sur un côté) */
async function pickMedia(id: string, src: string) {
  if (src) await knowMedia([src]);
  SB.edit((list) => {
    const b = list.find((x) => x.id === id);
    if (!b) return;
    // un autre média : le plan le montre depuis son début
    if (b.src !== src) b.start = 0;
    b.src = src;
    if (isImage(src) && !["full", "left", "right"].includes(b.place)) b.place = "full";
  }, 150);
}
/** les images et vidéos de référence d'un motion */
async function setImages(id: string, srcs: string[]) {
  await knowMedia(srcs);
  SB.edit((list) => {
    const b = list.find((x) => x.id === id);
    if (!b) return;
    b.images = srcs;
    delete b.src;
  }, 150);
}
/** supprime un beat du storyboard depuis l'aperçu, après confirmation (sa création en file ou en cours est arrêtée) */
async function removeBeat(id: string) {
  const b = pending.value.find((x) => x.id === id);
  if (!b || !confirm(tr("editing.storyboard.confirmRemove", { show: b.show || tr(`editing.storyboard.types.${b.type}`) }))) return;
  if (SB.busy.value || SB.chatBusy.value) {
    toast(tr("editing.storyboard.removeBusy"), true);
    return;
  }
  if (["queued", "running"].includes(anims.value[id]?.status ?? "")) await SB.stopAnim(id);
  SB.edit((list) => list.filter((x) => x.id !== id), 0);
  if (beatSel.value === id) beatSel.value = null;
}
/** les beats dont on vient de demander la création : affichés « en file » tout de suite, sans attendre le serveur */
const launching = ref<string[]>([]);
const anims = computed<Record<string, AnimState>>(() => {
  const a = { ...(SB.view.value?.anim_jobs ?? {}) };
  for (const id of launching.value)
    if (!["queued", "running"].includes(a[id]?.status ?? "")) a[id] = { status: "queued", activity: null, error: null };
  return a;
});
const ORDER = ["running", "queued", "error"];
/** les créations visibles dans la barre des tâches : en cours d'abord, puis en file, puis ratées */
const tasks = computed(() => pending.value
  .filter((b) => anims.value[b.id] && anims.value[b.id].status !== "cancelled")
  .map((b) => ({ beat: b, ...anims.value[b.id] }))
  .sort((x, y) => ORDER.indexOf(x.status) - ORDER.indexOf(y.status) || x.beat.at - y.beat.at));
const counts = computed(() => ({
  running: tasks.value.filter((x) => x.status === "running").length,
  queued: tasks.value.filter((x) => x.status === "queued").length,
}));
/** les beats qu'on peut encore lancer (ni en file ni en cours, un B-roll avec son média) : à animer, ou à poser */
const launchable = computed(() => pending.value.filter((b) => !["queued", "running"].includes(anims.value[b.id]?.status ?? "")
  && (b.type !== "broll" || !!b.src)));
const toAnimate = computed(() => launchable.value.filter(needsAnim));
const toPlace = computed(() => launchable.value.filter((b) => !needsAnim(b)));
async function createAnimations(ids: string[]) {
  // un double clic ne relance pas ce qui part déjà
  ids = ids.filter((id) => !launching.value.includes(id));
  if (!ids.length) return;
  launching.value = [...launching.value, ...ids];
  try {
    const r = await SB.animate(ids);
    if (r?.skipped.length) toast(tr("editing.storyboard.skipped", r.skipped.length));
    if (r?.missing.length) toast(tr("editing.storyboard.broll.missingToast", r.missing.length));
    await M.load();
  } finally {
    launching.value = launching.value.filter((id) => !ids.includes(id));
  }
}
// une animation terminée : la timeline relue pour afficher sa composition
watch(() => Object.keys(SB.view.value?.composed ?? {}).join(","), () => M.load());

// les contrôles dépendent de l'A-roll : relus quand il change
watch(() => JSON.stringify(tl.value?.aroll ?? []), () => SB.load());

// --- export vers Resolve
const exporting = ref(false);
async function exportResolve() {
  exporting.value = true;
  const r = await M.exportResolve();
  exporting.value = false;
  if (!r) return;
  toast(r.problems.length
    ? tr("editing.exportedWithIssues", { n: r.problems.length, list: r.problems.slice(0, 2).join(" · ") }, r.problems.length)
    : tr("editing.exported", { name: r.name }));
}
async function reveal() {
  if (!view.value) return;
  if (!view.value.export.exists) await M.exportResolve();
  await post(`/api/projects/${project.value.id}/reveal`, { rel: view.value.export.rel }).catch((e) => toast((e as Error).message, true));
}

// --- raccourcis clavier
function edges(): number[] {
  if (!tl.value) return [];
  const s = clipStarts(tl.value);
  return [...s, M.total.value];
}
function onKey(e: KeyboardEvent) {
  const el = e.target as HTMLElement | null;
  if (el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))) return;
  const ctrl = e.ctrlKey || e.metaKey, k = e.key.toLowerCase();
  const fps = view.value?.source?.fps || 25;
  let handled = true;
  if (ctrl && k === "z") M.undo();
  else if (ctrl && k === "b") blade("aroll", "", t.value);
  else if (k === "b" && !ctrl) tool.value = "blade";
  else if (k === "a" && !ctrl) tool.value = "select";
  else if (k === "k") { if (player.playing.value) player.toggle(); }
  else if (k === "l") { if (!player.playing.value) player.toggle(); }
  else if (k === "j") seek(t.value - 5);
  else if (e.key === "ArrowLeft") seek(e.shiftKey ? t.value - 1 : frameStep(t.value, -1, fps));
  else if (e.key === "ArrowRight") seek(e.shiftKey ? t.value + 1 : frameStep(t.value, 1, fps));
  else if (e.key === "ArrowUp") seek([...edges()].reverse().find((x) => x < t.value - 0.01) ?? 0);
  else if (e.key === "ArrowDown") seek(edges().find((x) => x > t.value + 0.01) ?? M.total.value);
  else if (e.key === "Home") seek(0);
  else if (e.key === "End") seek(M.total.value);
  else if ((e.key === "Delete" || e.key === "Backspace") && selection.value && "item" in selection.value) {
    const { track, id, fx } = selection.value.item;
    // une transition sélectionnée : on ne retire qu'elle
    if (fx === "transition") M.edit((x) => { const c = x.aroll.find((k) => k.id === id); if (c) c.transition = null; });
    else if (fx) M.edit((x) => { const it = (x[track] as (Broll | Motion)[]).find((k) => k.id === id); if (it) delete it[fx]; });
    else M.edit((x) => remove(x, track, id));
    selection.value = fx ? { item: { track, id } } : null;
  } else if (k === "m" && !ctrl) addBeat();
  else if (k === "i" && !ctrl) {
    const b = selection.value && "range" in selection.value ? Math.max(selection.value.range[1], t.value + 0.1) : Math.min(M.total.value, t.value + 5);
    selection.value = { range: [t.value, b] };
  } else if (k === "o" && !ctrl) {
    const a = selection.value && "range" in selection.value ? Math.min(selection.value.range[0], t.value - 0.1) : Math.max(0, t.value - 5);
    selection.value = { range: [a, t.value] };
  } else if (k === "x" && e.altKey) selection.value = null;
  else if (e.key === "Escape") { selection.value = null; beatSel.value = null; tool.value = "select"; }
  else if (k === "z" && e.shiftKey) timeline.value?.fit();
  else if (e.key === "+" || e.key === "=") timeline.value?.zoomBy(1.5);
  else if (e.key === "-") timeline.value?.zoomBy(1 / 1.5);
  else handled = false;
  if (handled) e.preventDefault();
}
onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <div class="screen">
    <div class="main">
      <div v-if="!view" class="eyebrow">{{ tr("common.loading") }}</div>
      <div v-else-if="!view.source" class="dashed-box">
        {{ tr("editing.needSource") }}
        <RouterLink :to="`/p/${project.id}/transcript`">{{ tr("editing.goToSource") }}</RouterLink>
      </div>

      <template v-else-if="tl">
        <div class="top">
          <Preview ref="preview" class="pv" :player="player" :tl="tl" :view="view" :beats="pending" create :anims="anims" :visuals="SB.view.value?.visuals"
            :text-sel="textSel" editable
            @create="(id: string) => createAnimations([id])" @stop="(id: string) => SB.stopAnim(id)" @remove="removeBeat" @report="discussFrame" @pick="pickMedia"
            @show="(id: string, text: string) => changeBeat(id, (b) => { b.show = text; }, 800)"
            @pick-text="(id: string) => (selection = { item: { track: 'texts', id } })" @move-text="moveText" />
          <BeatPanel v-if="selBeat" class="insp" :beat="selBeat" :anims="anims" :visuals="SB.view.value?.visuals ?? []"
            :places="SB.view.value?.places ?? []" @change="(c, d) => changeBeat(selBeat!.id, c, d)" @create="(id: string) => createAnimations([id])"
            @stop="(id: string) => SB.stopAnim(id)" @remove="removeBeat" @ask="askBeat" @seek="seek" @close="beatSel = null"
            @image="(src: string) => pickMedia(selBeat!.id, src)" @images="(srcs: string[]) => setImages(selBeat!.id, srcs)"
            :image-popup="imagePopup" @image-popup="(tab: ImageTab | null) => (imagePopup = tab)" />
          <Inspector v-else v-model:selection="selection" class="insp" :tl="tl" :view="view" :available="M.available.value"
            :t="t" :total="M.total.value" @edit="edit" @comment="comment" @seek="seek" @beat="addBeat"
            @insert="(m: AvailableMedia) => insertClip(m, t)" @media="M.loadAvailable()" @rerender="M.retryRenders()"
            @pause="setPause" />
        </div>

        <div class="toolbar">
          <div class="tools">
            <button :class="{ on: tool === 'select' }" :title="tr('editing.toolbar.selectTitle')" @click="tool = 'select'">{{ tr("editing.toolbar.select") }}</button>
            <button :class="{ on: tool === 'blade' }" :title="tr('editing.toolbar.bladeTitle')" @click="tool = 'blade'">{{ tr("editing.toolbar.blade") }}</button>
          </div>
          <div class="tools">
            <button :title="tr('editing.toolbar.zoomOut')" @click="timeline?.zoomBy(1 / 1.5)">−</button>
            <button :title="tr('editing.toolbar.fitTitle')" @click="timeline?.fit()">{{ tr("editing.toolbar.fit") }}</button>
            <button :title="tr('editing.toolbar.zoomIn')" @click="timeline?.zoomBy(1.5)">+</button>
          </div>
          <FindSaid :pid="project.id" @seek="seek" />
          <button v-if="toAnimate.length" class="btn sm" :disabled="M.busy.value" :title="tr('editing.storyboard.createAllTitle')"
            @click="createAnimations(toAnimate.map((b) => b.id))">
            {{ tr("editing.storyboard.createAll", toAnimate.length) }}
          </button>
          <button v-if="toPlace.length" class="btn sm" :disabled="M.busy.value" :title="tr('editing.storyboard.placeAllTitle')"
            @click="createAnimations(toPlace.map((b) => b.id))">
            {{ tr("editing.storyboard.placeAll", toPlace.length) }}
          </button>
          <span v-if="M.dirty.value" class="saving mono">{{ tr("common.saving") }}</span>
          <span v-else-if="M.busy.value" class="busy mono">{{ tr("editing.toolbar.busy") }}</span>
          <span class="spacer" />
          <StylePicker :pid="project.id" />
          <button class="link-btn" :disabled="!view.can_undo" title="Ctrl+Z" @click="M.undo()">{{ tr("editing.toolbar.undo") }}</button>
          <button class="btn" :disabled="exporting" :title="tr('editing.toolbar.exportTitle')" @click="exportResolve">{{ tr("editing.toolbar.export") }}</button>
          <button class="btn" :title="tr('editing.toolbar.revealTitle')" @click="reveal">{{ tr("common.openFolder") }}</button>
        </div>

        <div v-if="tasks.length" class="tasks">
          <span class="tasks-title mono">
            {{ tr("editing.anims.title") }}<template v-if="counts.running"> · {{ tr("editing.anims.nRunning", counts.running) }}</template><template v-if="counts.queued"> · {{ tr("editing.anims.nQueued", counts.queued) }}</template>
          </span>
          <span v-for="x in tasks" :key="x.beat.id" class="task" :class="x.status" :title="x.error || x.beat.show">
            <button class="task-tc mono" @click="seek(x.beat.at + 0.05)">{{ tcd(x.beat.at) }}</button>
            <span class="task-st">{{ x.status === "running" ? (x.activity || tr("editing.anims.running")) : tr(`editing.anims.${x.status}`) }}</span>
            <button v-if="x.status !== 'error'" class="x-btn" :title="tr('common.stop')" @click="SB.stopAnim(x.beat.id)">×</button>
            <button v-else class="link-btn" @click="createAnimations([x.beat.id])">{{ tr("editing.anims.retry") }}</button>
          </span>
        </div>

        <Timeline ref="timeline" v-model:selection="selection" :tl="tl" :total="M.total.value" :t="t" :tool="tool"
          :source-duration="view.source.duration" :analysis="view.analysis" :peaks="peaks"
          :media="view.media" :motions="view.motions" :playing="player.playing.value" :ghosts="ghosts" :beat-sel="beatSel"
          :words="SB.view.value?.words" :lead="SB.view.value?.lead" :tail="SB.view.value?.tail"
          @seek="seek" @edit="edit" @commit="M.save(150)" @hold="(h: boolean) => (M.holding.value = h)" @blade="blade"
          @ghost="openBeat" @beat="moveBeat" @beat-commit="SB.flush()" @drop="dropMedia" />
        <p class="keys mono">
          {{ tr("editing.keys") }}
        </p>
      </template>
    </div>

    <div v-if="view" class="side">
      <div class="tabs">
        <span class="tab on" :title="tr('editing.chat.sub')">{{ tr("common.assistant") }}</span>
        <span class="spacer" />
        <button class="link-btn new" :disabled="!current" @click="newRequest">{{ tr("editing.chat.new") }}</button>
      </div>
      <ImageSearchQueue v-if="imageJobs.length" :jobs="imageJobs" @open="openSearch" @stop="SB.stopSearch" @dismiss="SB.dismissSearch" />
      <TaskQueue v-if="view.tasks.length" :tasks="view.tasks" :current="current" :describe="describe"
        @open="openTask" @stop="M.stop" @close="M.close" />
      <MonteurChat ref="chat" :task="task" :usage="view.usage" :selection="selection" :describe="describe"
        @send="send" @stop="M.stop(current!)" @pick="pick" @seek="seek" />
    </div>
  </div>
</template>

<style scoped>
.screen { padding: 16px 24px 24px 32px; display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 24px; align-items: start; }
.main { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.dashed-box { display: flex; flex-direction: column; gap: 10px; align-items: center; }
.top { display: flex; gap: 24px; flex-wrap: wrap; align-items: flex-start; }
.pv { flex: 1 1 440px; max-width: 640px; }
.insp { flex: 1 1 240px; max-width: 380px; }
.toolbar { display: flex; align-items: center; gap: 10px; border-top: 1px solid var(--line); padding-top: 10px; flex-wrap: wrap; }
.tools { display: flex; border: 1px solid var(--line-strong); border-radius: 4px; overflow: hidden; }
.tools button { border: none; background: #fff; padding: 6px 10px; font-size: 12.5px; cursor: pointer; color: var(--ink-2); }
.tools button + button { border-left: 1px solid var(--line-soft); }
.tools button.on { background: var(--ink); color: #fff; }
.busy { font-size: 11.5px; color: #7C5CE0; }
.saving { font-size: 11px; color: var(--faint); }
.toolbar .link-btn { font-size: 12.5px; }
.side {
  position: sticky; top: 0; height: calc(100vh - 150px); min-height: 520px; display: flex; flex-direction: column;
  border: 1px solid var(--line); border-radius: 6px; background: #fff; overflow: hidden;
}
.tabs { display: flex; align-items: center; gap: 2px; padding: 0 10px; border-bottom: 1px solid var(--line); background: var(--bg-soft); min-height: 38px; }
.tab {
  height: 38px; padding: 0 12px; border: none; background: transparent; cursor: pointer;
  font-size: 13px; color: var(--muted); border-bottom: 2px solid transparent; margin-bottom: -1px;
}
.tab.on { color: var(--ink); font-weight: 600; border-bottom-color: var(--red); display: inline-flex; align-items: center; }
.tab:hover:not(.on) { color: var(--ink); }
.tabs .new { font-size: 12px; }
.tasks { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.tasks-title { font-size: 11px; color: var(--muted); margin-right: 4px; }
.task { display: inline-flex; align-items: center; gap: 6px; padding: 2px 4px 2px 8px; border: 1px solid var(--line-strong); border-radius: 3px; font-size: 12px; background: #fff; }
.task.running { border-color: #7C5CE0; background: #F6F3FE; }
.task.error { border-color: var(--red-bg); color: var(--red-ink); }
.task-tc { border: none; background: none; padding: 0; font-size: 11px; color: var(--ink-2); cursor: pointer; }
.task-tc:hover { color: var(--red-ink); }
.task-st { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--muted); }
.task .link-btn { font-size: 11.5px; }
.keys { margin: 0; font-size: 10.5px; color: var(--off); line-height: 1.6; }
</style>
