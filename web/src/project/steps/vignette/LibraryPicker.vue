<script setup lang="ts">
/**
 * Choix d'images d'une catégorie de la bibliothèque (plusieurs à la fois), ou parmi les images du projet
 * (assets et fichiers ajoutés) ; on peut y glisser de nouvelles images, rangées dans la catégorie et
 * cochées d'emblée.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../../../lib/api";
import { toast } from "../../../lib/toast";
import { droppedFiles, upload } from "../../../lib/upload";
import { PROJECT_PREFIX, refUrl } from "./refs";

interface Item { name: string; rel: string; category: string; type: string; project: string | null; kind: string }

const props = defineProps<{ pid: string; category: string; title: string; selected: string[]; max: number }>();
const emit = defineEmits<{ done: [rels: string[]]; cancel: [] }>();

const { t } = useI18n();
const items = ref<Item[]>([]);
const own = ref<Item[]>([]);
const picked = ref<string[]>([...props.selected]);
const over = ref(false);
const uploading = ref<number | null>(null);
// la catégorie du sélecteur d'abord, mais on peut piocher dans toutes les images de la bibliothèque
const filter = ref<string>(props.category);
const query = ref("");

const images = computed(() => [...own.value, ...items.value].filter((x) => x.kind === "Images"));
const categories = computed(() => {
  const counts = new Map<string, { type: string; n: number }>();
  for (const x of images.value) {
    const c = counts.get(x.category) ?? { type: x.type, n: 0 };
    counts.set(x.category, { ...c, n: c.n + 1 });
  }
  return [...counts].map(([key, c]) => ({ key, ...c }));
});
const shown = computed(() => {
  const q = query.value.trim().toLowerCase();
  return images.value.filter((x) => (filter.value === "all" || x.category === filter.value)
    && (!q || `${x.name} ${x.project ?? ""} ${x.type}`.toLowerCase().includes(q)));
});

// trois lignes de cinq : la page tient dans la fenêtre sans défiler
const PAGE = 15;
const page = ref(0);
const pages = computed(() => Math.max(1, Math.ceil(shown.value.length / PAGE)));
const paged = computed(() => shown.value.slice(page.value * PAGE, (page.value + 1) * PAGE));
watch([filter, query], () => (page.value = 0));

// les médias du projet, comme le panneau Médias du script
const PROJECT_GROUPS = ["Assets", "Fichiers ajoutés"];

onMounted(async () => {
  const [lib, res] = await Promise.all([
    api<{ items: Item[] }>("/api/projects/library"),
    api<{ groups: { k: string; items: { name: string; rel: string; kind: string }[] }[] }>(`/api/projects/${props.pid}/resources`),
  ]);
  items.value = lib.items;
  own.value = res.groups.filter((g) => PROJECT_GROUPS.includes(g.k)).flatMap((g) => g.items).map((x) => ({
    ...x, rel: `${PROJECT_PREFIX}${x.rel}`, category: PROJECT_PREFIX, type: t("thumbnail.picker.project"), project: null,
  }));
  if (!images.value.some((x) => x.category === props.category)) filter.value = "all";
});

function toggle(rel: string) {
  if (picked.value.includes(rel)) picked.value = picked.value.filter((r) => r !== rel);
  else if (picked.value.length >= props.max) toast(t("thumbnail.picker.max", { n: props.max }), true);
  else picked.value = [...picked.value, rel];
}

async function onDrop(e: DragEvent) {
  over.value = false;
  const files = droppedFiles(e).filter((f) => f.type.startsWith("image/"));
  if (!files.length) return;
  const before = new Set(items.value.map((x) => x.rel));
  uploading.value = 0;
  try {
    items.value = (await upload<{ items: Item[] }>("/api/projects/library/upload", files, "files",
      { category: props.category }, (f) => (uploading.value = Math.round(f * 100)))).items;
    filter.value = props.category;
    query.value = "";
    const added = shown.value.filter((x) => !before.has(x.rel)).map((x) => x.rel);
    picked.value = [...picked.value, ...added].slice(0, props.max);
  } catch (err) {
    toast((err as Error).message, true);
  } finally {
    uploading.value = null;
  }
}
</script>

<template>
  <div class="backdrop" @click="emit('cancel')" />
  <div class="picker" @dragover.prevent="over = true" @dragleave.self="over = false" @drop.prevent="onDrop">
    <div class="head">
      <span class="h">{{ title }}</span>
      <span class="eyebrow">{{ t("thumbnail.picker.picked", picked.length) }}</span>
      <span class="spacer" />
      <button class="x-btn" :title="t('common.close')" @click="emit('cancel')">×</button>
    </div>
    <div class="filters">
      <input v-model="query" class="input search" :placeholder="t('thumbnail.picker.search')">
      <button class="chip" :class="{ on: filter === 'all' }" @click="filter = 'all'">{{ t("thumbnail.picker.all", { n: images.length }) }}</button>
      <button
        v-for="c in categories" :key="c.key" class="chip" :class="{ on: filter === c.key }"
        @click="filter = c.key">
        {{ c.type }} · {{ c.n }}
      </button>
    </div>
    <div class="grid">
      <button v-for="x in paged" :key="x.rel" class="cell" :class="{ on: picked.includes(x.rel) }" :title="`${x.type} · ${x.name}`" @click="toggle(x.rel)">
        <img :src="refUrl(pid, x.rel)" alt="">
        <span v-if="picked.includes(x.rel)" class="n">{{ picked.indexOf(x.rel) + 1 }}</span>
      </button>
      <span v-if="!shown.length" class="nothing">
        {{ query ? t("thumbnail.picker.noMatch") : t("thumbnail.picker.emptyCategory") }}
      </span>
    </div>
    <div v-if="pages > 1" class="pager">
      <button class="btn" :disabled="page === 0" @click="page--">‹</button>
      <span class="mono">{{ t("thumbnail.picker.page", { n: page + 1, total: pages }) }}</span>
      <button class="btn" :disabled="page >= pages - 1" @click="page++">›</button>
    </div>
    <div class="drop-zone" :class="{ over }">
      <template v-if="uploading != null">{{ t("thumbnail.picker.uploading", { n: uploading }) }}</template>
      <template v-else>{{ t("thumbnail.picker.drop") }}</template>
    </div>
    <div class="foot">
      <button class="btn" @click="emit('cancel')">{{ t("common.cancel") }}</button>
      <button class="btn dark" @click="emit('done', picked)">{{ t("common.validate") }}</button>
    </div>
  </div>
</template>

<style scoped>
.backdrop { position: fixed; inset: 0; z-index: 40; background: rgba(24, 25, 27, .35); }
.picker {
  position: fixed; z-index: 41; top: 8vh; left: 50%; transform: translateX(-50%); width: min(880px, 92vw);
  max-height: 84vh; background: #fff; border-radius: 6px; box-shadow: 0 16px 48px rgba(0, 0, 0, .2);
  padding: 20px 22px; display: flex; flex-direction: column; gap: 14px; overflow-y: auto;
}
.head { display: flex; align-items: baseline; gap: 12px; }
.h { font-size: 16px; font-weight: 600; }
.filters { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.search { width: 240px; margin-right: 6px; }
.chip { background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 4px 9px; font-size: 12px; cursor: pointer; }
.chip:hover { border-color: var(--border-hover); }
.chip.on { background: var(--ink); border-color: var(--ink); color: #fff; }
.grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
.cell {
  position: relative; aspect-ratio: 1; padding: 0; border: none; border-radius: 4px; overflow: hidden;
  cursor: pointer; background: var(--bg-soft); outline-offset: 2px;
}
/* hors du flux : une capture très haute ne doit pas agrandir sa cellule et déborder sur la ligne suivante */
.cell img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; object-position: top; display: block; }
.cell.on { outline: 2px solid var(--red); }
.cell .n {
  position: absolute; top: 6px; right: 6px; min-width: 20px; height: 20px; border-radius: 10px; padding: 0 5px;
  background: var(--red); color: #fff; font-family: var(--mono); font-size: 11px; line-height: 20px;
}
.nothing { grid-column: 1 / -1; padding: 10px 0; font-size: 13.5px; color: var(--faint); }
.pager { display: flex; align-items: center; justify-content: center; gap: 12px; font-size: 12px; color: var(--muted); }
.pager .btn { padding: 2px 10px; }
.drop-zone { padding: 14px; }
.foot { display: flex; justify-content: flex-end; gap: 8px; }
</style>
