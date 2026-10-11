<script setup lang="ts">
/** Vidéo source : la vidéo retravaillée (ou le dérush tel quel) sur laquelle travaillent les étapes suivantes, et son transcript. */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../../lib/api";
import { LANGUAGES, mmss } from "../../lib/format";
import { toast } from "../../lib/toast";
import { droppedFiles, upload } from "../../lib/upload";
import { stepById } from "../steps";
import { act, refresh, store } from "../store";
import type { SourceTranscript } from "../types";
import PlayerFrame from "./derush/PlayerFrame.vue";
import { useDerush } from "./derush/useDerush";
import { useFollowScroll, usePlaylist, type Piece } from "./derush/usePlaylist";

const { t } = useI18n();
const project = computed(() => store.project!);
const base = computed(() => `/api/projects/${project.value.id}`);
const source = computed(() => project.value.source);
const derush = useDerush(project);
const keptFmt = computed(() => mmss(derush.kept.value));

// --- choix de la vidéo
const uploading = ref<{ name: string; pct: number } | null>(null);
const over = ref(false);
const copying = computed(() => project.value.runtime.importing.find((i) => i.target === "source" && !i.error));
const importError = computed(() => project.value.runtime.importing.find((i) => i.target === "source" && i.error)?.error);

/** Import ou rendu en cours : libellé et avancement (%). */
const busy = computed(() => {
  if (uploading.value) return { label: t("source.importing", { name: uploading.value.name }), pct: uploading.value.pct };
  if (copying.value) return { label: t("source.importing", { name: copying.value.name }), pct: Math.round(copying.value.pct) };
  if (source.value?.pending) {
    const job = project.value.runtime.jobs.render;
    return { label: t("source.renderingDerush"), pct: Math.round((job?.progress ?? 0) * 100) };
  }
  return null;
});
const ready = computed(() => !busy.value && !!source.value);

async function onDrop(e: DragEvent) {
  over.value = false;
  const file = droppedFiles(e)[0];
  if (!file) return;
  uploading.value = { name: file.name, pct: 0 };
  try {
    await upload(`${base.value}/source/upload`, [file], "file", {}, (f) => {
      uploading.value = { name: file.name, pct: Math.round(f * 100) };
    });
    await refresh();
    toast(t("source.imported"));
  } catch (e) {
    toast(t("source.importFailed", { e: (e as Error).message }), true);
  } finally {
    uploading.value = null;
  }
}

function useDerushAsIs() {
  if (derush.ready.value) act("/source/derush");
}

function replace() {
  if (confirm(t("source.confirmReplace"))) act("/source", undefined, "DELETE");
}

// --- transcript
const transcript = ref<SourceTranscript | null>(null);
const job = computed(() => project.value.runtime.source_transcript);
watch(() => `${source.value?.transcript}:${job.value?.status}`, async () => {
  const id = source.value?.transcript;
  transcript.value = null;
  if (!id) return;
  try {
    const tx = await api<SourceTranscript | null>(`${base.value}/source/transcript`);
    if (source.value?.transcript === id) transcript.value = tx;
  } catch (e) {
    toast(t("source.transcriptUnreadable", { e: (e as Error).message }), true);
  }
}, { immediate: true });

// --- lecture
const duration = computed(() => source.value?.duration ?? transcript.value?.duration ?? 0);
const pieces = computed<Piece[]>(() => (ready.value && source.value
  ? [{ src: `${base.value}/source/media?v=${encodeURIComponent(`${source.value.path}:${duration.value}`)}`, start: 0, end: duration.value, on: true }]
  : []));
const player = usePlaylist(pieces);

// --- transcript : états, recherche, ligne en cours
const txState = computed(() => {
  if (job.value && !job.value.finished) return "busy";
  return transcript.value?.status === "done" ? "done" : "none";
});
const txPct = computed(() => Math.round((job.value?.progress ?? 0) * 100));
const lines = computed(() => transcript.value?.lines ?? []);

function transcribe(ask = false) {
  if (ask && !confirm(t("source.confirmRegen"))) return;
  act("/source/transcribe");
}

const query = ref("");
const q = computed(() => query.value.trim().toLowerCase());
const hits = computed(() => new Set(q.value ? lines.value.flatMap((l, i) => (l.text.toLowerCase().includes(q.value) ? [i] : [])) : []));

const cur = computed(() => {
  const time = player.t.value;
  let found = -1;
  for (let i = 0; i < lines.value.length && lines.value[i].start <= time; i++) found = i;
  return found;
});
const caption = computed(() => {
  const l = lines.value[cur.value];
  return l && player.t.value < l.end ? l.text : "";
});

const box = ref<HTMLElement | null>(null);
const { skipNext } = useFollowScroll(box, cur);
function seekLine(start: number) {
  skipNext();
  player.seek(start);
}

async function copy() {
  await navigator.clipboard.writeText(lines.value.map((l) => l.text).join("\n"));
  toast(t("source.copied"));
}

// --- colonne de droite
const meta = computed(() => {
  const s = source.value;
  if (!s) return "";
  const parts = [s.kind === "import" ? t("source.kind.import") : t("source.kind.derush"), mmss(duration.value)];
  if (s.width && s.height) parts.push(`${s.width} × ${s.height}`);
  return parts.join(" · ");
});
const stats = computed(() => {
  const lang = transcript.value?.language;
  return [
    { k: t("source.stats.duration"), v: mmss(duration.value) },
    { k: t("source.stats.words"), v: txState.value === "done" ? String(lines.value.reduce((a, l) => a + l.text.split(/\s+/).filter(Boolean).length, 0)) : "—" },
    { k: t("source.stats.highlights"), v: String(project.value.runtime.shorts.count) },
    { k: t("source.stats.language"), v: lang ? LANGUAGES[lang] ?? lang : "—" },
  ];
});

// --- ensuite : la vidéo longue, ou les shorts (une branche pas encore portée reste grisée)
const next = computed(() => [
  { step: "storyboard", t: t("source.next.longT"), d: t("source.next.longD") },
  { step: "selection", t: t("source.next.shortsT"), d: t("source.next.shortsD") },
].map((n) => ({ ...n, on: !!stepById(n.step) && txState.value === "done" })));
</script>

<template>
  <div class="screen">
    <div class="main">
      <div v-if="busy" class="busy">
        <span class="busy-label">{{ t("source.busy", { label: busy.label, p: busy.pct }) }}</span>
        <div class="progress bar"><div :style="{ width: `${busy.pct}%` }" /></div>
      </div>

      <template v-else-if="!source">
        <div class="cards">
          <div class="card drop" :class="{ over }" @click="act('/source/browse')"
            @dragover.prevent="over = true" @dragleave="over = false" @drop.prevent="onDrop">
            <span class="card-t">{{ t("source.cards.importT") }}</span>
            <span class="card-d">{{ t("source.cards.importD") }}</span>
            <span class="card-ext">.mov · .mp4</span>
          </div>
          <div v-if="project.mode !== 'video'" class="card solid" :class="{ disabled: !derush.ready.value }"
            :title="derush.ready.value ? '' : t('source.cards.derushNeedsTranscript')" @click="useDerushAsIs">
            <span class="card-t">{{ t("source.cards.derushT") }}</span>
            <span v-if="derush.ready.value" class="card-d">{{ t("source.cards.derushD", { d: keptFmt }) }}</span>
            <span v-else class="card-d">{{ t("source.cards.derushNotReady") }}</span>
          </div>
        </div>
        <span v-if="importError" class="error">{{ t("source.importFailed", { e: importError }) }}</span>
      </template>

      <template v-else>
        <PlayerFrame :player="player" :height="280" :caption="caption" />

        <div v-if="source.drift" class="drift">
          <span>{{ t("source.drift", { d: mmss(duration), kept: keptFmt }) }}</span>
          <button class="btn dark regen" @click="transcribe()">{{ t("source.regenerateTranscript") }}</button>
        </div>

        <div class="transcript">
          <div class="tx-head">
            <span class="tx-title">{{ t("source.transcript") }}</span>
            <input v-model="query" class="input search" :placeholder="t('source.search')">
            <span v-if="q" class="hits">{{ t("source.hits", hits.size) }}</span>
            <button class="btn tool" :disabled="txState !== 'done'" @click="copy">{{ t("common.copy") }}</button>
            <a v-if="txState === 'done'" class="btn tool" :href="`/api/transcript/jobs/${source.transcript}/export?fmt=srt&level=line`" download>.srt</a>
            <button v-if="txState === 'done'" class="link-btn" @click="transcribe(true)">{{ t("source.regenerate") }}</button>
          </div>

          <div v-if="txState === 'busy'" class="state">
            <span class="busy-label">{{ t("source.transcribing", { p: txPct }) }}</span>
            <div class="progress bar"><div :style="{ width: `${txPct}%` }" /></div>
          </div>

          <div v-else-if="txState === 'none'" class="state">
            <button class="btn dark gen" @click="transcribe()">{{ t("source.generate") }}</button>
            <span v-if="transcript?.error" class="error">{{ transcript.error }}</span>
          </div>

          <div v-else ref="box" class="lines">
            <div v-for="(l, i) in lines" :key="i" :data-li="i" class="line"
              :class="{ on: i === cur, hit: hits.has(i), dim: q && !hits.has(i) }" @click="seekLine(l.start)">
              <span class="tc">{{ mmss(l.start) }}</span>
              <span class="text">{{ l.text }}</span>
            </div>
          </div>
        </div>
      </template>
    </div>

    <aside>
      <template v-if="ready && source">
        <div class="file">
          <span class="file-name">{{ source.name }}</span>
          <span class="file-meta">{{ meta }}</span>
          <button class="link-btn replace" @click="replace">{{ t("source.replace") }}</button>
        </div>
        <div v-for="m in stats" :key="m.k" class="stat">
          <span>{{ m.k }}</span><span class="mono">{{ m.v }}</span>
        </div>
        <span class="eyebrow next-label">{{ t("source.next.label") }}</span>
        <component :is="n.on ? 'RouterLink' : 'div'" v-for="n in next" :key="n.step" class="next" :class="{ off: !n.on }"
          :to="n.on ? `/p/${project.id}/${n.step}` : undefined"
          :title="n.on ? '' : stepById(n.step) ? t('source.next.needsTranscript') : t('source.next.notAvailable')">
          <span class="next-t">{{ n.t }}</span>
          <span class="next-d">{{ n.d }}</span>
        </component>
      </template>
    </aside>
  </div>
</template>

<style scoped>
.screen { padding: 20px 32px 40px; display: grid; grid-template-columns: minmax(0, 1fr) 280px; gap: 32px; }
.main { display: flex; flex-direction: column; gap: 16px; min-width: 0; }

.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
.card {
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px;
  padding: 44px 24px; border-radius: 6px; text-align: center; cursor: pointer;
}
.card.drop { border: 1px dashed var(--off); }
.card.drop:hover, .card.drop.over { border-color: var(--ink); background: var(--bg-softer); }
.card.solid { border: 1px solid var(--line-strong); }
.card.solid:hover { border-color: var(--ink); }
.card.disabled { cursor: not-allowed; opacity: 0.55; }
.card.disabled:hover { border-color: var(--line-strong); }
.card-t { font-size: 15px; font-weight: 600; }
.card-d { font-size: 13px; color: var(--muted); line-height: 1.5; max-width: 300px; text-wrap: pretty; }
.card-ext { font-family: var(--mono); font-size: 11.5px; color: var(--faint); }
.error { font-size: 12.5px; color: var(--red-ink); }

.busy {
  display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 56px 24px;
  border: 1px dashed var(--dash); border-radius: 6px;
}
.busy-label { font-family: var(--mono); font-size: 12.5px; color: var(--muted); }
.progress.bar { width: 260px; }

.drift {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap; padding: 12px 14px;
  background: var(--bg-soft); border: 1px solid var(--line-strong); border-radius: 4px;
}
.drift > span { flex: 1; min-width: 240px; font-size: 13.5px; line-height: 1.5; color: var(--ink-2); }
.btn.regen { height: 34px; padding: 0 14px; }

.transcript { display: flex; flex-direction: column; gap: 10px; border-top: 1px solid var(--line); padding-top: 14px; }
.tx-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.tx-title { font-size: 14px; font-weight: 600; padding-right: 6px; }
.input.search { flex: 1; min-width: 140px; height: 32px; padding: 0 10px; font-size: 13.5px; }
.hits { font-family: var(--mono); font-size: 12px; color: var(--faint); }
.btn.tool { padding: 0 10px; font-size: 12.5px; }
a.btn.tool, a.btn.tool:hover { color: var(--ink); text-decoration: none; }
.link-btn { font-size: 12.5px; padding: 0 6px; }

.state {
  display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 36px 20px;
  border: 1px dashed var(--dash); border-radius: 4px;
}
.btn.gen { height: 38px; padding: 0 18px; font-size: 13.5px; }

.lines { position: relative; height: 400px; overflow-y: auto; display: flex; flex-direction: column; padding-right: 8px; }
.line { display: flex; gap: 14px; padding: 10px; border-left: 2px solid transparent; cursor: pointer; }
.line:hover { background: var(--bg-softer); }
.line.on { border-left-color: var(--red); background: var(--bg-softer); }
.line.hit { background: var(--red-bg-soft); }
.tc { width: 42px; flex-shrink: 0; font-family: var(--mono); font-size: 11.5px; color: var(--faint); padding-top: 3px; }
.text { flex: 1; font-size: 15px; line-height: 1.65; color: var(--ink-2); text-wrap: pretty; }
.line.dim .text { color: var(--off); }

aside { display: flex; flex-direction: column; gap: 12px; }
.file { display: flex; flex-direction: column; gap: 4px; padding-bottom: 12px; border-bottom: 1px solid var(--line-soft); }
.file-name { font-family: var(--mono); font-size: 12.5px; font-weight: 600; word-break: break-all; }
.file-meta { font-size: 12.5px; color: var(--muted); }
.link-btn.replace { align-self: flex-start; padding: 4px 0 0; font-size: 12.5px; }
.stat {
  display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--line-soft); font-size: 13.5px;
}
.stat > span:first-child { color: var(--muted); }
.stat .mono { font-size: 13px; }
.next-label { font-size: 10.5px; padding-top: 14px; }
.next {
  display: flex; flex-direction: column; gap: 6px; padding: 16px; border: 1px solid var(--line-strong); border-radius: 4px;
  color: var(--ink) !important; text-decoration: none !important;
}
a.next:hover { border-color: var(--ink); }
.next.off { cursor: not-allowed; opacity: .5; }
.next-t { font-size: 15px; font-weight: 600; }
.next-d { font-size: 12.5px; color: var(--muted); line-height: 1.45; }
</style>
