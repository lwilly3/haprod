<script setup lang="ts">
/** Tout ce que contient le dossier du projet, rangé par catégorie ; « Ajouter des médias » (ou un glisser-déposer) l'enrichit. */
import { computed, ref, watch } from "vue";
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

async function load() {
  groups.value = (await api<{ groups: Group[] }>(`/api/projects/${pid.value}/resources`)).groups;
}

watch(pid, async (id) => {
  try {
    await open(id);
    await load();
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
    <AddMediaModal v-if="adding && store.project?.id === pid" v-model:tab="addTab" :uploading="uploading" @files="uploadFiles" @close="closeAdd" />
    <MediaLightbox v-model="zoom" :items="zoomable">
      <template #actions="{ item }"><button class="link-btn" @click="reveal(item.rel)">{{ t("common.showInExplorer") }}</button></template>
    </MediaLightbox>
  </div>
</template>

<style scoped>
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
