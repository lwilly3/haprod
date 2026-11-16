<script setup lang="ts">
/**
 * Retrouver un passage des rushes en le décrivant : ce qu'on y voit (un modèle de vision local, qui
 * doit d'abord regarder les rushes) et ce qui s'y dit (les transcripts). Un clic va au passage.
 */
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { api, post } from "../../../lib/api";
import { mmss } from "../../../lib/format";
import { toast } from "../../../lib/toast";

const props = defineProps<{ pid: string }>();
const emit = defineEmits<{ seek: [string, number] }>();
const { t } = useI18n();

interface Status { available: boolean; rushes: number; indexed: number; running: boolean; progress: number; activity: string | null; error: string | null }
interface Hit { kind: "seen" | "said"; rush: string; name: string; t: number; text: string; score: number }

const status = ref<Status | null>(null);
const query = ref("");
const busy = ref(false);
const results = ref<{ seen: Hit[]; said: Hit[] } | null>(null);
let timer: ReturnType<typeof setTimeout> | undefined;

async function refresh() {
  clearTimeout(timer);
  status.value = await api<Status>(`/api/projects/${props.pid}/search/status`);
  if (status.value.running) timer = setTimeout(() => refresh().catch(() => undefined), 1500);
}

async function index() {
  try {
    status.value = await post<Status>(`/api/projects/${props.pid}/search/index`);
    timer = setTimeout(() => refresh().catch(() => undefined), 1500);
  } catch (e) {
    toast((e as Error).message, true);
  }
}

async function search() {
  if (!query.value.trim() || busy.value) return;
  busy.value = true;
  try {
    results.value = await api(`/api/projects/${props.pid}/search?${new URLSearchParams({ q: query.value.trim() })}`);
  } catch (e) {
    toast((e as Error).message, true);
  } finally {
    busy.value = false;
  }
}

const frame = (h: Hit) => `/api/projects/${props.pid}/rushes/${h.rush}/frame?t=${Math.floor(h.t)}`;

onMounted(() => refresh().catch((e) => toast(e.message, true)));
onBeforeUnmount(() => clearTimeout(timer));
</script>

<template>
  <div class="search">
    <div class="bar">
      <input v-model="query" class="input" :placeholder="t('derush.search.placeholder')" @keydown.enter="search">
      <button class="btn dark" :disabled="!query.trim() || busy" @click="search">{{ busy ? t("derush.search.searching") : t("derush.search.go") }}</button>
    </div>
    <div v-if="status" class="index">
      <template v-if="!status.available">{{ t("derush.search.unavailable") }}</template>
      <template v-else-if="status.running">
        <span class="spinner" /> {{ status.activity ?? t("derush.search.indexing") }} · {{ Math.round(status.progress * 100) }} %
      </template>
      <template v-else>
        {{ t("derush.search.indexed", { n: status.indexed, total: status.rushes }) }}
        <button v-if="status.indexed < status.rushes" class="link-btn" @click="index">{{ t("derush.search.index") }}</button>
      </template>
      <span v-if="status.error" class="err">{{ status.error }}</span>
    </div>
    <template v-if="results">
      <span class="eyebrow">{{ t("derush.search.seen", { n: results.seen.length }) }}</span>
      <div class="grid">
        <button v-for="(h, i) in results.seen" :key="`v${i}`" class="card" :title="h.name" @click="emit('seek', h.rush, h.t)">
          <img :src="frame(h)" loading="lazy" alt="">
          <span class="meta"><span class="name">{{ h.name }}</span><span class="mono">{{ mmss(h.t) }}</span></span>
        </button>
      </div>
      <span v-if="!results.seen.length" class="none">{{ status?.indexed ? t("derush.search.noneSeen") : t("derush.search.notIndexed") }}</span>
      <span class="eyebrow">{{ t("derush.search.said", { n: results.said.length }) }}</span>
      <button v-for="(h, i) in results.said" :key="`s${i}`" class="line" @click="emit('seek', h.rush, h.t)">
        <span class="mono">{{ mmss(h.t) }}</span><span class="name">{{ h.name }}</span><span class="text">{{ h.text }}</span>
      </button>
      <span v-if="!results.said.length" class="none">{{ t("derush.search.noneSaid") }}</span>
    </template>
    <span v-else class="hint">{{ t("derush.search.hint") }}</span>
  </div>
</template>

<style scoped>
.search { display: flex; flex-direction: column; gap: 10px; padding: 12px 14px; overflow: auto; height: 100%; font-size: 13.5px; }
.bar { display: flex; gap: 8px; }
.bar .input { flex: 1; }
.index { display: flex; gap: 8px; align-items: center; color: var(--muted, #777); font-size: 12.5px; }
.err { color: var(--red, #c33); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
.card { display: flex; flex-direction: column; gap: 4px; padding: 0; border: 1px solid var(--line-soft); border-radius: 6px; overflow: hidden; background: none; cursor: pointer; text-align: left; }
.card:hover, .line:hover { border-color: var(--ink); }
.card img { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; background: #111; display: block; }
.meta { display: flex; justify-content: space-between; gap: 6px; padding: 0 6px 5px; font-size: 12px; }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--muted, #777); }
.line { display: grid; grid-template-columns: 44px 110px minmax(0, 1fr); gap: 10px; padding: 6px 8px; border: 1px solid transparent; border-radius: 6px; background: none; cursor: pointer; text-align: left; font-size: 13.5px; }
.text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.none, .hint { color: var(--muted, #777); }
</style>
