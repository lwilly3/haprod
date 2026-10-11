<script setup lang="ts">
/**
 * Rendu final : la vidéo longue (timeline du montage rendue par ffmpeg, en 1080p ou 4K) et chaque
 * short monté (rendu HyperFrames de l'étape Montage des shorts). Chaque rendu se lance à part, depuis
 * sa ligne, et se télécharge une fois terminé.
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import Seg from "../../components/Seg.vue";
import { api, post } from "../../lib/api";
import { usePolling, usePref } from "../../lib/composables";
import { mmss } from "../../lib/format";
import { toast } from "../../lib/toast";
import { store } from "../store";

type Quality = "1080p" | "4k";
interface RenderState { status: string; progress: number; stage: string | null; error: string | null; url: string | null }
interface LongRender extends RenderState {
  quality: Quality; size: [number, number] | null; duration: number; can_render: boolean; current: boolean; rel?: string;
}
interface ShortItem {
  id: string; title: string; duration: number; montage: string | null; size: [number, number] | null; busy: boolean;
  render: (RenderState & { id: string }) | null;
}
interface View { long: LongRender; shorts: { selection: string | null; items: ShortItem[] } }

const { t } = useI18n();
const project = computed(() => store.project!);
const base = `/api/projects/${project.value.id}/rendu`;
const quality = usePref<Quality>("rendu.quality", (project.value.source?.width ?? 0) >= 3840 ? "4k" : "1080p");
// la sélection de shorts ouverte aux étapes Sélection et Montage
const selection = usePref<string | null>(`shorts.selection.${project.value.id}`, null);
const view = ref<View | null>(null);
// la ligne dont le lancement ou l'arrêt est en cours d'envoi
const sending = ref<string | null>(null);

const query = () => `quality=${quality.value}${selection.value ? `&selection=${selection.value}` : ""}`;
const body = (target: string) => ({ target, quality: quality.value, selection: selection.value });
const active = (status?: string | null) => !!status && !["none", "done", "error", "cancelled"].includes(status);

async function load() {
  const q = query();
  const v = await api<View>(`${base}?${q}`);
  if (q === query()) view.value = v;
}
usePolling(async () => {
  await load();
  return rendering.value ? 1000 : 4000;
});

interface Row {
  key: string; name: string; f: string; dur: string; pct: number; status: string; tone: "" | "red" | "done";
  title?: string; url?: string | null; link?: string;
  /** rendu en file ou en cours : on peut l'arrêter */
  running?: boolean;
  /** on peut lancer (ou relancer) ce rendu depuis la ligne */
  can?: boolean;
  /** rendu terminé mais le montage a changé depuis */
  stale?: boolean;
}

function row(r: RenderState | null, ready: boolean): Pick<Row, "pct" | "status" | "tone" | "title" | "running" | "stale"> {
  if (!r || r.status === "none") return { pct: 0, status: t("render.status.ready"), tone: "" };
  if (active(r.status)) {
    return {
      pct: r.progress, status: r.status === "queued" ? t("render.status.queued") : t("render.status.percent", { p: Math.round(r.progress * 100) }),
      tone: "", title: r.stage ?? undefined, running: true,
    };
  }
  if (r.status === "error") return { pct: 0, status: t("render.status.error"), tone: "red", title: r.error ?? undefined };
  if (r.status === "cancelled") return { pct: 0, status: t("render.status.cancelled"), tone: "" };
  if (!r.url) return { pct: 0, status: t("render.status.ready"), tone: "" };
  return ready ? { pct: 1, status: t("render.status.done"), tone: "done" }
    : { pct: 1, status: t("render.status.stale"), tone: "red", title: t("render.staleTitle"), stale: true };
}

const size = (s: [number, number] | null) => (s ? `${s[0]} × ${s[1]}` : "—");

const rows = computed<Row[]>(() => {
  const v = view.value;
  if (!v) return [];
  const l = v.long;
  const long: Row = {
    key: "long", name: t("render.longVideo"), f: size(l.size), dur: mmss(l.duration), url: l.url, can: l.can_render,
    ...(l.can_render ? row(l, l.current) : { pct: 0, status: "—", tone: "", title: t("render.noEditYet") }),
  };
  if (!l.can_render) long.link = "montage";
  const shorts = v.shorts.items.map((s, i): Row => {
    const name = t("render.shortName", { n: String(i + 1).padStart(2, "0"), title: s.title });
    const common = { key: s.id, name, f: size(s.size), dur: mmss(s.duration) };
    if (!s.montage) return { ...common, pct: 0, status: t("render.status.notEdited"), tone: "", link: "smontage" };
    if (s.busy && !active(s.render?.status)) return { ...common, pct: 0, status: t("render.status.editing"), tone: "", title: t("render.darylEditing") };
    return { ...common, ...row(s.render, true), url: s.render?.url ? `${s.render.url}?download=true` : null, can: true };
  });
  return [long, ...shorts];
});

const renderable = computed(() => rows.value.filter((r) => !r.link));
const doneCount = computed(() => renderable.value.filter((r) => r.tone === "done").length);
const rendering = computed(() => rows.value.some((r) => r.running));

async function send(path: string, target: string) {
  sending.value = target;
  try {
    view.value = await post<View>(path, body(target));
  } catch (e) {
    toast((e as Error).message, true);
  } finally {
    sending.value = null;
  }
}
const start = (r: Row) => send(base, r.key);
const stop = (r: Row) => send(`${base}/stop`, r.key);

async function reveal() {
  const rel = view.value?.long.rel;
  if (rel) await post(`/api/projects/${project.value.id}/reveal`, { rel }).catch((e) => toast((e as Error).message, true));
}

function setQuality(q: Quality) {
  quality.value = q;
  view.value = null;
  load();
}
const qualityModel = computed({ get: () => quality.value, set: setQuality });
</script>

<template>
  <div class="screen">
    <div class="bar">
      <span class="label">{{ t("render.longVideo") }}</span>
      <Seg v-model="qualityModel" :options="[['1080p', '1080p'], ['4k', '4K']]" />
      <span class="spacer" />
      <span class="mono faint sum">{{ t("render.doneCount", { done: doneCount, total: renderable.length }) }}</span>
    </div>

    <div v-if="!view" class="eyebrow">{{ t("common.loading") }}</div>
    <div v-else class="rows">
      <div v-for="r in rows" :key="r.key" class="row">
        <span class="name" :title="r.name">{{ r.name }}</span>
        <span class="mono meta">{{ r.f }}</span>
        <span class="mono meta">{{ r.dur }}</span>
        <div class="track"><div :class="r.tone" :style="{ width: `${r.pct * 100}%` }" /></div>
        <span class="mono status" :class="r.tone" :title="r.title">{{ r.status }}</span>
        <span class="act">
          <RouterLink v-if="r.link" :to="`/p/${project.id}/${r.link}`">{{ t("render.edit") }}</RouterLink>
          <template v-else>
            <a v-if="r.url && !r.running" :href="r.url" download>{{ t("render.download") }}</a>
            <button v-if="r.running" class="link-btn" :disabled="sending === r.key" @click="stop(r)">{{ t("common.stop") }}</button>
            <button v-else-if="r.can" class="btn sm" :class="{ red: !r.url || r.stale }"
              :disabled="sending === r.key" @click="start(r)">{{ r.url ? t("common.rerun") : t("render.render") }}</button>
          </template>
        </span>
      </div>
      <i18n-t v-if="!view.shorts.items.length" keypath="render.noShorts" tag="p" class="hint" scope="global">
        <template #step><RouterLink :to="`/p/${project.id}/selection`">{{ t("render.clipsStep") }}</RouterLink></template>
      </i18n-t>
      <p v-if="view.long.rel" class="hint">
        {{ t("render.longInFolder") }} <button class="link-btn" @click="reveal">{{ t("common.openFolder") }}</button>
      </p>
    </div>
  </div>
</template>

<style scoped>
.screen { padding: 20px 32px 40px; display: flex; flex-direction: column; gap: 18px; max-width: 980px; }
.bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.label { font-size: 13px; font-weight: 500; }
.spacer { flex: 1; }
.sum { font-size: 12px; }
.rows { display: flex; flex-direction: column; }
.row {
  display: grid; grid-template-columns: minmax(0, 1fr) 110px 60px 180px 70px 180px; gap: 16px; align-items: center;
  padding: 14px 0; border-top: 1px solid var(--line-soft); font-size: 14px;
}
.name { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.meta { font-size: 12px; color: var(--muted); }
.track { height: 4px; background: var(--line-soft); }
.track > div { height: 4px; background: var(--red); transition: width .4s; }
.track > div.done { background: var(--ink); }
.status { font-size: 12px; text-align: right; }
.status.red { color: var(--red-ink); }
.act { display: flex; align-items: center; justify-content: flex-end; gap: 12px; font-size: 13px; }
.hint { margin: 14px 0 0; font-size: 13px; color: var(--muted-2); }
.hint .link-btn { font-size: 13px; text-decoration: underline; }
</style>
