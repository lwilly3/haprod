<script setup lang="ts">
/** Tout ce que contient le dossier du projet, rangé par catégorie ; « Ajouter des médias » (ou un glisser-déposer) l'enrichit. */
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import MediaLightbox from "../components/MediaLightbox.vue";
import Thumb from "../components/Thumb.vue";
import { api, post } from "../lib/api";
import { usePref } from "../lib/composables";
import { duration as fmtDuration } from "../lib/format";
import { toast } from "../lib/toast";
import { droppedFiles, upload } from "../lib/upload";
import AddMediaModal, { ADD_TABS, type AddTab } from "./media/AddMediaModal.vue";
import { open, store } from "./store";

interface Item { name: string; rel: string; kind: string; duration: number | null; size: number }
interface Group { k: string; items: Item[] }

/** Les catégories de la bibliothèque (libellés : library.categories.<clé>). */
const LIBRARY = ["broll", "musique", "sfx", "images", "logos", "personnes", "lieux", "portraits", "vignettes"] as const;

const { t } = useI18n();

const route = useRoute();
const router = useRouter();
const pid = computed(() => String(route.params.pid));
const groups = ref<Group[]>([]);
/** "all", ou un groupe renvoyé par l'API */
const tab = ref("all");
const over = ref(false);
const uploading = ref<number | null>(null);

// --- sons suggérés : Claude lit le script et les rushes, chaque idée est cherchée parmi les sons libres ---

interface FreeSound { id: string; title: string; creator: string; license: string; url: string; preview: string; duration: number | null; required: boolean }
interface SoundIdea { kind: "sfx" | "musique"; query: string; label: string; moment: string; why: string; results: FreeSound[]; error: string | null }
interface SoundIdeas {
  status: string; finished: boolean; error: string | null; activity: string | null;
  result: { items: SoundIdea[]; message: string } | null;
}
const ideas = ref<SoundIdeas | null>(null);
const ideasNote = ref("");
const ideasOpen = ref(false);
const soundAdding = ref<string[]>([]);
const soundAdded = ref<string[]>([]);
const player = ref<HTMLAudioElement | null>(null);
const sound = ref<string | null>(null);
let ideasTimer: ReturnType<typeof setTimeout> | undefined;

async function loadIdeas() {
  clearTimeout(ideasTimer);
  ideas.value = await api<SoundIdeas | null>(`/api/projects/${pid.value}/sounds/suggest`);
  if (ideas.value && !ideas.value.finished) ideasTimer = setTimeout(() => loadIdeas().catch(() => undefined), 1500);
}

async function suggestSounds() {
  try {
    ideas.value = await post<SoundIdeas>(`/api/projects/${pid.value}/sounds/suggest`, { note: ideasNote.value });
    ideasOpen.value = true;
    ideasTimer = setTimeout(() => loadIdeas().catch(() => undefined), 1500);
  } catch (e) {
    toast((e as Error).message, true);
  }
}

// --- pose sur la timeline : Claude choisit un son par idée et le place dans le montage ---

interface PlacedSound {
  label: string; kind: "sfx" | "musique"; why: string; at: number; dur: number; title: string; creator: string;
  license: string; required: boolean; url: string; said: string;
}
interface SoundPlace {
  status: string; finished: boolean; error: string | null; activity: string | null;
  result: { placed: PlacedSound[]; skipped: { label: string; reason: string }[]; message: string } | null;
}
const place = ref<SoundPlace | null>(null);
let placeTimer: ReturnType<typeof setTimeout> | undefined;
const clock = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

async function loadPlace() {
  clearTimeout(placeTimer);
  place.value = await api<SoundPlace | null>(`/api/projects/${pid.value}/sounds/place`);
  if (place.value && !place.value.finished) placeTimer = setTimeout(() => loadPlace().catch(() => undefined), 1500);
}

async function placeSounds() {
  if (place.value?.result && !confirm(t("media.sounds.placeAgainConfirm"))) return;
  try {
    place.value = await post<SoundPlace>(`/api/projects/${pid.value}/sounds/place`, { note: ideasNote.value });
    placeTimer = setTimeout(() => loadPlace().catch(() => undefined), 1500);
  } catch (e) {
    toast((e as Error).message, true);
  }
}

function toggleSound(x: FreeSound): void {
  const el = player.value!;
  if (sound.value === x.id) {
    el.pause();
    sound.value = null;
    return;
  }
  el.src = x.preview;
  el.play().catch((e) => e.name !== "AbortError" && toast(e.message, true));
  sound.value = x.id;
}

async function addSound(idea: SoundIdea, x: FreeSound) {
  if (soundAdding.value.includes(x.id)) return;
  soundAdding.value = [...soundAdding.value, x.id];
  try {
    await post("/api/projects/library/free", { category: idea.kind, id: x.id });
    soundAdded.value = [...soundAdded.value, x.id];
    toast(t("library.free.added", { title: x.title }));
  } catch (e) {
    toast((e as Error).message, true);
  } finally {
    soundAdding.value = soundAdding.value.filter((id) => id !== x.id);
  }
}

onBeforeUnmount(() => {
  clearTimeout(ideasTimer);
  clearTimeout(placeTimer);
  player.value?.pause();
});

async function load() {
  groups.value = (await api<{ groups: Group[] }>(`/api/projects/${pid.value}/resources`)).groups;
}

watch(pid, async (id) => {
  try {
    await open(id);
    await load();
    await loadIdeas();
    await loadPlace();
  } catch {
    router.replace("/");
  }
}, { immediate: true });

// --- la popup « Ajouter des médias » ; ?add=youtube l'ouvre sur un onglet (liens du storyboard)
const addTab = usePref<AddTab>("media.addTab", "files");
const linked = route.query.add as AddTab | undefined;
if (linked && ADD_TABS.includes(linked)) addTab.value = linked;
const adding = ref(!!linked);

function closeAdd() {
  adding.value = false;
  // la page est rendue par chemin complet : retirer ?add la recharge
  if (route.query.add) router.replace({ query: {} });
  else load();
}

// des images validées dans la popup apparaissent derrière, sans attendre sa fermeture
async function onAdded() {
  await load();
  tab.value = "Assets";
}

// un téléchargement YouTube qui se termine arrive dans la liste
const downloaded = computed(() => store.project?.runtime.assets.downloads.filter((d) => d.finished).length ?? 0);
watch(downloaded, (n, before) => { if (n > before) load(); });

const total = computed(() => groups.value.reduce((a, g) => a + g.items.length, 0));
const items = computed(() => tab.value === "all"
  ? groups.value.flatMap((g) => g.items.map((x) => ({ ...x, k: g.k })))
  : (groups.value.find((g) => g.k === tab.value)?.items ?? []).map((x) => ({ ...x, k: x.kind })));

function onDrop(e: DragEvent) {
  over.value = false;
  if (adding.value) return;
  const files = droppedFiles(e);
  if (files.length) uploadFiles(files);
}

async function uploadFiles(files: File[]) {
  uploading.value = 0;
  try {
    groups.value = (await upload<{ groups: Group[] }>(`/api/projects/${pid.value}/resources/upload`, files, "files", {},
      (f) => (uploading.value = Math.round(f * 100)))).groups;
    tab.value = "Fichiers ajoutés";
    toast(t("media.filesAdded", files.length));
  } catch (e) {
    toast((e as Error).message, true);
  } finally {
    uploading.value = null;
  }
}

// les rushes hors du dossier du projet (chemin absolu) n'ont pas d'URL : l'aperçu retombe sur les hachures
const fileUrl = (rel: string) => `/api/projects/${pid.value}/files/${rel.split("/").map(encodeURIComponent).join("/")}`;

function reveal(rel: string) {
  post(`/api/projects/${pid.value}/reveal`, { rel }).catch((e) => toast(e.message, true));
}

/** ce qui s'ouvre dans l'aperçu : images, vidéos, sons du dossier du projet */
const zoom = ref<(Item & { url: string }) | null>(null);
const zoomable = computed(() => items.value
  .filter((x) => ["Images", "Vidéo", "Audio"].includes(x.kind) && !/^([a-zA-Z]:|\/)/.test(x.rel))
  .map((x) => ({ ...x, url: fileUrl(x.rel) })));

function onClick(x: Item): void {
  const z = zoomable.value.find((e) => e.rel === x.rel);
  if (z) zoom.value = z;
  else reveal(x.rel);
}

async function toLibrary(item: Item, category: string) {
  if (!category) return;
  try {
    await post(`/api/projects/${pid.value}/resources/to-library`, { rel: item.rel, category });
    toast(t("media.addedToLibrary", { category: t(`library.categories.${category}`) }));
  } catch (e) {
    toast((e as Error).message, true);
  }
}
</script>

<template>
  <div class="page" :class="{ over }" @dragover.prevent="over = !adding" @dragleave.self="over = false" @drop.prevent="onDrop">
    <div class="titles">
      <span class="eyebrow">{{ store.project?.title }}</span>
      <span class="h1">{{ t("media.title") }}</span>
    </div>
    <div class="tab-bar">
      <div class="tabs">
        <button :class="{ on: tab === 'all' }" @click="tab = 'all'">{{ t("common.all") }}<span class="n">{{ total }}</span></button>
        <button v-for="g in groups" :key="g.k" :class="{ on: tab === g.k }" @click="tab = g.k">{{ g.k }}<span class="n">{{ g.items.length }}</span></button>
      </div>
      <span v-if="uploading != null && !adding" class="mono faint uploading">{{ t("media.uploading", { pct: uploading }) }}</span>
      <button class="btn dark add" @click="adding = true">{{ t("media.add.open") }}</button>
    </div>
    <div class="ideas">
      <div class="ideas-bar">
        <span class="ideas-title">{{ t("media.sounds.title") }}</span>
        <input v-model="ideasNote" class="input" :placeholder="t('media.sounds.note')" @keydown.enter="suggestSounds">
        <button class="btn dark" :disabled="!!ideas && !ideas.finished" @click="suggestSounds">
          {{ ideas && !ideas.finished ? (ideas.activity ?? t("media.sounds.running")) : ideas?.result ? t("media.sounds.again") : t("media.sounds.suggest") }}
        </button>
        <button class="btn" :disabled="!!place && !place.finished" @click="placeSounds">
          {{ place && !place.finished ? (place.activity ?? t("media.sounds.running")) : t("media.sounds.place") }}
        </button>
        <button v-if="ideas?.result" class="link-btn" @click="ideasOpen = !ideasOpen">{{ ideasOpen ? t("media.sounds.hide") : t("media.sounds.show", { n: ideas.result.items.length }) }}</button>
      </div>
      <span class="muted hint">{{ t("media.sounds.hint") }}</span>
      <span v-if="ideas?.status === 'error'" class="state err">{{ ideas.error }}</span>
      <span v-if="place?.status === 'error'" class="state err">{{ place.error }}</span>
      <div v-if="place?.result" class="placed">
        <div class="idea-head">
          <span class="idea-label">{{ t("media.sounds.placed", { n: place.result.placed.length }) }}</span>
          <RouterLink :to="`/p/${pid}/montage`">{{ t("media.sounds.openEdit") }}</RouterLink>
        </div>
        <p v-if="place.result.message" class="ideas-message">{{ place.result.message }}</p>
        <div v-for="(x, i) in place.result.placed" :key="i" class="placed-row">
          <span class="mono">{{ clock(x.at) }}</span>
          <span class="idea-kind">{{ t(`library.categories.${x.kind}`) }}</span>
          <span class="name" :title="x.why"><b>{{ x.label }}</b> · {{ x.title }}</span>
          <a class="muted" :href="x.url" target="_blank" rel="noopener">{{ x.creator }}</a>
          <span class="license" :class="{ credit: x.required }">{{ x.license }}</span>
        </div>
        <span v-for="(x, i) in place.result.skipped" :key="`s${i}`" class="faint">{{ t("media.sounds.skipped", { label: x.label, reason: x.reason }) }}</span>
        <span class="muted hint">{{ t("media.sounds.placedHint") }}</span>
      </div>
      <template v-if="ideasOpen && ideas?.result">
        <p v-if="ideas.result.message" class="ideas-message">{{ ideas.result.message }}</p>
        <div v-for="(idea, i) in ideas.result.items" :key="i" class="idea">
          <div class="idea-head">
            <span class="idea-kind">{{ t(`library.categories.${idea.kind}`) }}</span>
            <span class="idea-label">{{ idea.label }}</span>
            <span class="mono faint">{{ idea.query }}</span>
          </div>
          <span class="muted">{{ idea.moment }} — {{ idea.why }}</span>
          <div v-for="x in idea.results" :key="x.id" class="idea-row" :class="{ playing: sound === x.id }">
            <button class="play" :title="sound === x.id ? t('common.pause') : t('common.play')" @click="toggleSound(x)">{{ sound === x.id ? "❚❚" : "▶" }}</button>
            <span class="name" :title="x.title">{{ x.title }}</span>
            <a class="muted" :href="x.url" target="_blank" rel="noopener">{{ x.creator }}</a>
            <span class="license" :class="{ credit: x.required }" :title="x.required ? t('library.free.creditRequired') : t('library.free.noCredit')">{{ x.license }}</span>
            <span class="mono dur">{{ x.duration ? fmtDuration(x.duration) : "" }}</span>
            <button class="btn" :disabled="soundAdding.includes(x.id) || soundAdded.includes(x.id)" @click="addSound(idea, x)">
              {{ soundAdded.includes(x.id) ? t("library.free.inLibrary") : soundAdding.includes(x.id) ? t("library.free.adding") : t("library.free.add") }}
            </button>
          </div>
          <span v-if="!idea.results.length" class="faint">{{ idea.error ?? t("library.free.none") }}</span>
        </div>
      </template>
      <audio ref="player" @ended="sound = null" />
    </div>
    <div class="table">
      <div class="row head eyebrow"><span /><span>{{ t("common.name") }}</span><span>{{ t("common.type") }}</span><span>{{ t("common.duration") }}</span><span /></div>
      <div v-for="x in items" :key="x.rel" class="row" @click="onClick(x)">
        <Thumb :src="fileUrl(x.rel)" :kind="x.kind" :name="x.name" />
        <span class="name">{{ x.name }}</span>
        <span class="muted">{{ x.k }}</span>
        <span class="mono dur">{{ x.duration ? fmtDuration(x.duration) : "" }}</span>
        <select v-if="['Vidéo', 'Audio', 'Images'].includes(x.kind)" class="to-lib" @click.stop
          @change="toLibrary(x, ($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value = ''">
          <option value="">{{ t("media.toLibrary") }}</option>
          <option v-for="k in LIBRARY" :key="k" :value="k">{{ t(`library.categories.${k}`) }}</option>
        </select>
        <span v-else />
      </div>
      <span v-if="!items.length" class="nothing">{{ t("common.nothingYet") }}</span>
    </div>
    <AddMediaModal v-if="adding && store.project?.id === pid" v-model:tab="addTab" :uploading="uploading" @files="uploadFiles" @added="onAdded" @close="closeAdd" />
    <MediaLightbox v-model="zoom" :items="zoomable">
      <template #actions="{ item }"><button class="link-btn" @click="reveal(item.rel)">{{ t("common.showInExplorer") }}</button></template>
    </MediaLightbox>
  </div>
</template>

<style scoped>
.ideas { display: flex; flex-direction: column; gap: 8px; padding: 14px 16px; border: 1px solid var(--line-soft); border-radius: 8px; }
.ideas-bar { display: flex; gap: 10px; align-items: center; }
.ideas-bar .input { flex: 1; max-width: 460px; }
.ideas-title { font-weight: 600; }
.ideas-message { margin: 4px 0; font-size: 13.5px; }
.placed { display: flex; flex-direction: column; gap: 4px; padding: 10px 0; border-top: 1px solid var(--line-soft); font-size: 13.5px; }
.placed-row { display: grid; grid-template-columns: 50px 96px minmax(0, 2fr) minmax(0, 1fr) 110px; gap: 12px; align-items: center; padding: 2px 0; }
.placed-row .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.idea { display: flex; flex-direction: column; gap: 4px; padding: 10px 0; border-top: 1px solid var(--line-soft); font-size: 13.5px; }
.idea-head { display: flex; gap: 10px; align-items: baseline; }
.idea-kind { font-size: 11.5px; padding: 1px 6px; border-radius: 4px; border: 1px solid var(--line-soft); }
.idea-label { font-weight: 600; }
.idea-row { display: grid; grid-template-columns: 34px minmax(0, 1.6fr) minmax(0, 1fr) 110px 60px 170px; gap: 12px; align-items: center; padding: 3px 0; }
.idea-row .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.license { font-size: 11.5px; padding: 2px 6px; border-radius: 4px; border: 1px solid var(--line-soft); text-align: center; white-space: nowrap; }
.license.credit { border-color: #D8C68E; background: #F4E9C8; color: var(--ink); }
.page { flex: 1; overflow: auto; padding: 32px 40px; display: flex; flex-direction: column; gap: 20px; }
.titles { display: flex; flex-direction: column; gap: 4px; }
.h1 { font-size: 24px; font-weight: 600; letter-spacing: -0.015em; }
.page.over { outline: 2px dashed var(--ink); outline-offset: -8px; }
.tab-bar { display: flex; align-items: flex-end; gap: 16px; border-bottom: 1px solid var(--line); }
.tab-bar .tabs { flex: 1; border-bottom: none; }
.uploading { font-size: 12px; margin-bottom: 16px; }
.add { margin-bottom: 8px; }
.table { display: flex; flex-direction: column; }
.row {
  display: grid; grid-template-columns: 72px minmax(0, 1fr) 160px 90px 130px; gap: 16px; align-items: center;
  padding: 8px 0; border-top: 1px solid var(--line-soft); font-size: 13.5px; cursor: pointer;
}
.row:hover:not(.head) { background: var(--bg-softer); }
.row.head { border-top: none; padding: 0 0 8px; cursor: default; }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dur { font-size: 12px; text-align: right; }
.to-lib { height: 28px; border: 1px solid var(--line-strong); border-radius: 4px; background: #fff; font-size: 12px; color: var(--muted); cursor: pointer; }
.nothing { padding: 14px 0; border-top: 1px solid var(--line-soft); font-size: 13.5px; color: var(--faint); }
</style>
