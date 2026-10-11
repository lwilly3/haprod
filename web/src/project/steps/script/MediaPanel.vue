<script setup lang="ts">
/**
 * Onglet Médias du script : les fichiers du projet et de la bibliothèque, à glisser sur un paragraphe.
 * Les groupes se replient ; un clic montre le fichier en grand.
 */
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import MediaLightbox from "../../../components/MediaLightbox.vue";
import Thumb from "../../../components/Thumb.vue";
import { api } from "../../../lib/api";
import { usePref } from "../../../lib/composables";
import { duration as fmtDuration } from "../../../lib/format";
import { store } from "../../store";
import type { PlanMedia } from "../../types";
import { MEDIA_MIME } from "./plans";

interface Item { name: string; rel: string; kind: string; duration: number | null; rush?: string }
interface Entry extends PlanMedia { key: string }

const props = defineProps<{
  /** combien de plans utilisent chaque fichier (par url) */
  used: Record<string, number>;
  /** dans l'onglet Plan : un clic choisit le fichier (au lieu de le glisser sur le texte) */
  picking?: boolean;
}>();
const emit = defineEmits<{ pick: [media: PlanMedia] }>();

const { t } = useI18n();
const pid = store.project!.id;
const KINDS = ["Vidéo", "Audio", "Images"];
// les groupes de Ressources qui servent au montage
const GROUPS = ["Rushes", "Assets", "Fichiers ajoutés"];

/** `lib` : le libellé de la catégorie de la bibliothèque (le nom du groupe est traduit à l'affichage) */
const groups = ref<{ k: string; lib?: string; items: Entry[] }[]>([]);
const search = ref("");
const loading = ref(true);

const enc = (rel: string) => rel.split("/").map(encodeURIComponent).join("/");

async function load(): Promise<void> {
  loading.value = true;
  try {
    const [res, lib] = await Promise.all([
      api<{ groups: { k: string; items: Item[] }[] }>(`/api/projects/${pid}/resources`),
      api<{ categories: Record<string, string>; items: (Item & { category: string })[] }>("/api/projects/library"),
    ]);
    const project = res.groups.filter((g) => GROUPS.includes(g.k)).map((g) => ({
      k: g.k,
      items: g.items.filter((x) => KINDS.includes(x.kind)).map((x) => ({
        key: `p:${x.rel}`, name: x.name, kind: x.kind, duration: x.duration,
        // un rush hors du dossier du projet se lit par son id
        url: x.rush ? `/api/projects/${pid}/rushes/${x.rush}/media` : `/api/projects/${pid}/files/${enc(x.rel)}`,
      })),
    }));
    const common = Object.entries(lib.categories).map(([cat, label]) => ({
      k: `Bibliothèque · ${label}`, lib: label,
      items: lib.items.filter((x) => x.category === cat && KINDS.includes(x.kind)).map((x) => ({
        key: `l:${x.rel}`, name: x.name, kind: x.kind, duration: x.duration,
        url: `/api/projects/library/file/${enc(x.rel)}`,
      })),
    }));
    groups.value = [...project, ...common].filter((g) => g.items.length);
  } finally {
    loading.value = false;
  }
}

onMounted(load);

const shown = computed(() => {
  const q = search.value.trim().toLowerCase();
  return groups.value
    .map((g) => ({ ...g, items: q ? g.items.filter((x) => x.name.toLowerCase().includes(q)) : g.items }))
    .filter((g) => g.items.length);
});

/** Les groupes repliés (gardés d'une visite à l'autre) ; une recherche les déplie tous. */
const closed = usePref<string[]>("script.media.closed", []);
const isOpen = (k: string) => !!search.value.trim() || !closed.value.includes(k);

function toggle(k: string): void {
  closed.value = closed.value.includes(k) ? closed.value.filter((c) => c !== k) : [...closed.value, k];
}

// --- le fichier en grand ---------------------------------------------------------------

const zoom = ref<Entry | null>(null);
/** Les fichiers visibles, dans l'ordre : ← → passent de l'un à l'autre. */
const visible = computed(() => shown.value.filter((g) => isOpen(g.k)).flatMap((g) => g.items));

function onClick(x: Entry): void {
  if (props.picking) emit("pick", { url: x.url, name: x.name, kind: x.kind, duration: x.duration });
  else zoom.value = x;
}

function onDragStart(e: DragEvent, x: Entry): void {
  const media: PlanMedia = { url: x.url, name: x.name, kind: x.kind, duration: x.duration };
  e.dataTransfer!.setData(MEDIA_MIME, JSON.stringify(media));
  e.dataTransfer!.effectAllowed = "copy";
}
</script>

<template>
  <div class="media">
    <input v-model="search" class="input search" :placeholder="t('script.media.search')">
    <span v-if="picking" class="hint">{{ t("script.media.pickHint") }}</span>
    <span v-else class="hint">{{ t("script.media.dragHint") }}</span>
    <span v-if="loading" class="hint">{{ t("common.loading") }}</span>
    <i18n-t v-else-if="!groups.length" keypath="script.media.empty" tag="span" class="hint">
      <template #link><RouterLink :to="`/p/${pid}/ressources`">{{ t("script.media.mediaLink") }}</RouterLink></template>
    </i18n-t>
    <div v-for="g in shown" :key="g.k" class="group">
      <button class="eyebrow head" :class="{ open: isOpen(g.k) }" @click="toggle(g.k)">
        <span class="chev">▸</span>{{ g.lib ? t("script.media.library", { label: g.lib }) : g.k }}<span class="count">{{ g.items.length }}</span>
      </button>
      <div v-for="x in isOpen(g.k) ? g.items : []" :key="x.key" class="item" draggable="true" :title="x.name"
        @dragstart="onDragStart($event, x)" @click="onClick(x)">
        <Thumb :src="x.url" :kind="x.kind" :name="x.name" />
        <div class="meta">
          <span class="name">{{ x.name }}</span>
          <span class="sub mono">
            {{ x.duration ? fmtDuration(x.duration) : x.kind }}<template v-if="props.used[x.url]"> · ×{{ props.used[x.url] }}</template>
          </span>
        </div>
      </div>
    </div>
    <button v-if="!loading" class="link-btn reload" @click="load">{{ t("script.media.refresh") }}</button>

    <MediaLightbox v-model="zoom" :items="visible">
      <template #meta="{ item }"><template v-if="props.used[item.url]"> · ×{{ props.used[item.url] }}</template></template>
    </MediaLightbox>
  </div>
</template>

<style scoped>
.media { display: flex; flex-direction: column; gap: 8px; }
.search { height: 32px; font-size: 13px; }
.hint { font-size: 12px; color: var(--faint); line-height: 1.45; }
.group { display: flex; flex-direction: column; gap: 2px; padding-top: 8px; }
.head {
  display: flex; align-items: center; gap: 6px; padding: 2px 0 4px; border: none; background: none;
  font-size: 10px; text-align: left; cursor: pointer;
}
.head:hover { color: var(--ink); }
.chev { display: inline-block; transition: transform .15s; }
.head.open .chev { transform: rotate(90deg); }
.count { margin-left: auto; color: var(--off); }
.item { display: flex; gap: 8px; align-items: center; padding: 4px; border-radius: 4px; cursor: pointer; }
.item:active { cursor: grabbing; }
.item:hover { background: var(--bg-soft); }
.item :deep(.thumb) { width: 56px; height: 32px; border-radius: 3px; flex-shrink: 0; }
.meta { display: flex; flex-direction: column; min-width: 0; }
.name { font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sub { font-size: 10.5px; color: var(--faint); }
.reload { align-self: flex-start; font-size: 12px; margin-top: 6px; }
</style>
