<script setup lang="ts">
/**
 * Sélection : Claude lit le transcript de la vidéo source et propose les moments forts qui feront des shorts.
 * Chaque short est une suite d'extraits, écoutés ici dans la vidéo source ; un short valide est monté
 * par ffmpeg, puis « Monter → » l'ouvre à l'étape Montage (sous-titres, slides, rendu).
 */
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import Seg from "../../components/Seg.vue";
import { api } from "../../lib/api";
import { usePref } from "../../lib/composables";
import { duration, mmss, tc } from "../../lib/format";
import { toast } from "../../lib/toast";
import { store } from "../store";
import type { SourceTranscript } from "../types";
import { usePlaylist, type Piece } from "./derush/usePlaylist";
import { locale } from "../../i18n";
import { FORMATS, isActive, MAX_DURATIONS, selectionStatus, type Format, type Short } from "./shorts/types";
import { startStep, useSelection, useWanted } from "./shorts/useSelection";

const { t } = useI18n();
const router = useRouter();
const project = computed(() => store.project!);
const base = computed(() => `/api/projects/${project.value.id}`);
const S = useSelection(project);
const sel = S.sel;

// --- réglages d'une nouvelle sélection (mémorisés d'une sélection à l'autre)
const maxDuration = usePref("shorts.max_duration", 90);
const count = usePref("shorts.count", 0);
const context = usePref("shorts.context", "");
const format = usePref<Format>("shorts.format", "vertical");
const request = ref("");
const fresh = ref(false);
const settingsOpen = ref(false);
const creating = ref(false);

const maxDurSeg = computed({
  get: () => String(maxDuration.value),
  set: (v: string) => { maxDuration.value = Number(v); },
});
const MAX_OPTIONS = computed(() => MAX_DURATIONS.map((v) => [String(v), t(`clips.maxDurations.${v}`)] as const));
const FORMAT_OPTIONS = computed(() => FORMATS.map((f) => [f, t(`clips.formats.${f}`)] as const));
const COUNTS = [0, 1, 2, 3, 4, 5, 6, 7, 8];

const showForm = computed(() => S.loaded.value && !S.running.value && (!sel.value || fresh.value));

async function create() {
  creating.value = true;
  const ok = await S.create(request.value, {
    max_duration: maxDuration.value, count: count.value, context: context.value, format: format.value,
  });
  creating.value = false;
  if (ok) {
    request.value = "";
    fresh.value = false;
    selected.value = null;
  }
}


const reply = ref("");
async function send(text = reply.value) {
  if (!text.trim() || S.running.value) return;
  if (await S.send(text)) reply.value = "";
}

const lastMessage = computed(() => [...(sel.value?.messages ?? [])].reverse().find((m) => m.role === "assistant"));
const statusLabel = computed(() => {
  const s = sel.value;
  if (!s) return "";
  return s.activity ? t("clips.activity", { activity: s.activity }) : selectionStatus(s.status);
});

function label(s: { created_at: number; count: number; status: string }) {
  const at = new Date(s.created_at * 1000).toLocaleString(locale(), { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  return t("clips.label", { at, state: isActive(s.status) ? t("clips.inProgress") : t("clips.shortCount", s.count) });
}

// --- le short choisi, et sa lecture dans la vidéo source
const selected = ref<string | null>(null);
const short = computed<Short | null>(() => S.shorts.value.find((s) => s.id === selected.value) ?? S.shorts.value[0] ?? null);
const index = (s: Short) => S.shorts.value.indexOf(s) + 1;
const num = (s: Short) => String(index(s)).padStart(2, "0");

const media = computed(() => {
  const src = project.value.source;
  return src && !src.pending ? `${base.value}/source/media?v=${encodeURIComponent(`${src.path}:${src.duration}`)}` : "";
});
const pieces = computed<Piece[]>(() => (short.value && media.value
  ? short.value.clips.map((c) => ({ src: media.value, start: c.start, end: c.end, on: true }))
  : []));
const player = usePlaylist(pieces);
const video = ref<HTMLVideoElement | null>(null);
watch(video, (v) => { player.video.value = v; });

/** Début de chaque extrait dans le short. */
const offsets = computed(() => {
  let a = 0;
  return (short.value?.clips ?? []).map((c) => { const o = a; a += c.end - c.start; return o; });
});

// un autre short : on repart de son début
watch(() => short.value?.id, () => {
  player.seek(0);
  if (player.playing.value) player.toggle();
});

function pick(s: Short) {
  selected.value = s.id;
}

async function play(s: Short) {
  if (short.value?.id === s.id) return player.toggle();
  pick(s);
  await nextTick();
  player.toggle();
}

// --- transcript de la vidéo source : les phrases de chaque extrait, en temps du short
const lines = ref<SourceTranscript["lines"]>([]);
watch(() => S.transcript.value, async (id) => {
  lines.value = [];
  if (!id) return;
  try {
    const t = await api<SourceTranscript | null>(`${base.value}/source/transcript`);
    lines.value = t?.lines ?? [];
  } catch { /* sans transcript : le texte des extraits suffit */ }
}, { immediate: true });

interface Row { i: number; head: string; t: number; text: string }
const rows = computed<Row[]>(() => {
  const s = short.value;
  if (!s) return [];
  const out: Row[] = [];
  s.clips.forEach((c, k) => {
    const inside = lines.value.filter((l) => (l.start + l.end) / 2 >= c.start && (l.start + l.end) / 2 <= c.end);
    const parts = inside.length ? inside.map((l) => ({ start: l.start, text: l.text })) : [{ start: c.start, text: c.text }];
    parts.forEach((l, j) => out.push({
      i: out.length, head: j === 0 ? `${t("clips.part", { n: k + 1 })}${c.role ? ` · ${c.role}` : ""}` : "",
      t: offsets.value[k] + Math.max(0, l.start - c.start), text: l.text,
    }));
  });
  return out;
});
const cur = computed(() => {
  let found = -1;
  for (const r of rows.value) if (r.t <= player.t.value + 0.05) found = r.i;
  return found;
});
const caption = computed(() => rows.value[cur.value]?.text ?? "");
const part = computed(() => Math.max(0, player.index.value) + 1);

const follow = ref(true);
const box = ref<HTMLElement | null>(null);
let skip = false;
watch(cur, (i) => {
  if (skip) { skip = false; return; }
  if (!follow.value) return;
  const el = box.value?.querySelector<HTMLElement>(`[data-ri="${i}"]`);
  if (el) box.value!.scrollTo({ top: el.offsetTop - 40, behavior: "smooth" });
});
function seekRow(r: Row) {
  skip = true;
  player.seek(r.t);
}

// --- un short
function line(s: Short) {
  const n = s.clips.length, first = s.clips[0], last = s.clips[n - 1];
  const span = first ? `${mmss(first.start)} → ${mmss(last.end)}` : "";
  return [t("clips.parts", n), span, duration(s.duration)].filter(Boolean).join(" · ");
}
const tooLong = (s: Short) => !!sel.value && s.duration > sel.value.settings.max_duration;

const wanted = useWanted(project.value.id);
const sent = (s: Short) => !!s.project || wanted.value.includes(s.id);
const opening = ref<string | null>(null);
/**
 * « Monter → » : le short part au montage. Sa vidéo est découpée à ce moment-là (ffmpeg) ; l'étape
 * Montage suit la découpe et crée le montage dès qu'elle est finie.
 */
async function onMount(s: Short) {
  if (player.playing.value) player.toggle();
  opening.value = s.id;
  if (s.project || s.render?.url) {
    await S.montage(s);
  } else {
    await S.cut(s.id);
    if (!wanted.value.includes(s.id)) wanted.value = [...wanted.value, s.id];
    startStep("smontage");
  }
  opening.value = null;
  router.push({ path: `/p/${project.value.id}/smontage`, query: { short: s.id } });
}

function remove(s: Short) {
  if (confirm(t("clips.dismissConfirm", { title: s.title }))) S.removeShort(s.id);
}

/** Liste des extraits, à coller dans des notes ou un ticket. */
async function copyEdit(s: Short) {
  const out = s.clips.map((c, i) =>
    `${i + 1}. ${tc(c.start, true)} → ${tc(c.end, true)} (${duration(c.end - c.start)})${c.role ? ` · ${c.role}` : ""}\n   ${c.text}`);
  await navigator.clipboard.writeText(`${s.title} — ${duration(s.duration)}\n${s.hook}\n\n${out.join("\n")}\n`);
  toast(t("clips.copied"));
}

const vertical = computed(() => (sel.value?.settings.format ?? format.value) === "vertical");
const formatModel = computed({
  get: () => sel.value?.settings.format ?? format.value,
  set: (v: Format) => { if (sel.value && v !== sel.value.settings.format) S.setFormat(v); },
});
</script>

<template>
  <div class="screen">
    <div class="main">
      <div v-if="!project.source" class="dashed-box">
        {{ t("clips.needSource") }}
        <RouterLink :to="`/p/${project.id}/transcript`">{{ t("clips.goToSource") }}</RouterLink>
      </div>
      <div v-else-if="!S.transcript.value" class="dashed-box">
        {{ t("clips.transcriptNotReady") }}
        <RouterLink :to="`/p/${project.id}/transcript`">{{ t("clips.seeSource") }}</RouterLink>
      </div>

      <template v-else>
        <!-- en-tête : la sélection affichée -->
        <div v-if="sel && !fresh" class="head">
          <span class="retained">
            {{ S.shorts.value.length ? t("clips.suggested", S.shorts.value.length) : t("clips.shorts") }}
            <span v-if="S.shorts.value.length" class="mono faint">{{ t("clips.total", { d: duration(S.total.value) }) }}</span>
          </span>
          <Seg v-model="formatModel" :options="FORMAT_OPTIONS" size="sm" />
          <button v-if="!S.running.value" class="btn" @click="send(t('clips.more'))">{{ t("clips.suggestMore") }}</button>
          <template v-else>
            <span class="status mono">{{ statusLabel }}…</span>
            <button class="btn" @click="S.stop()">{{ t("common.stop") }}</button>
          </template>
        </div>

        <!-- réglages et lancement d'une sélection -->
        <div v-if="showForm" class="start">
          <span class="start-t">{{ t("clips.intro") }}</span>
          <button class="link-btn" @click="settingsOpen = !settingsOpen">{{ settingsOpen ? t("clips.hideSettings") : t("clips.settings") }}</button>
          <div v-if="settingsOpen" class="settings">
            <div class="field">
              <span class="eyebrow">{{ t("clips.maxDuration") }}</span>
              <Seg v-model="maxDurSeg" :options="MAX_OPTIONS" size="sm" />
            </div>
            <div class="field">
              <span class="eyebrow">{{ t("clips.count") }}</span>
              <select v-model.number="count" class="input select">
                <option v-for="n in COUNTS" :key="n" :value="n">{{ n ? n : t("clips.darylChooses") }}</option>
              </select>
            </div>
            <div class="field">
              <span class="eyebrow">{{ t("clips.format") }}</span>
              <Seg v-model="format" :options="FORMAT_OPTIONS" size="sm" />
            </div>
            <label class="field wide">
              <span class="eyebrow">{{ t("clips.context") }}</span>
              <input v-model="context" class="input" :placeholder="t('clips.contextPlaceholder')">
            </label>
            <label class="field wide">
              <span class="eyebrow">{{ t("clips.request") }}</span>
              <textarea v-model="request" class="textarea" rows="2" :placeholder="t('clips.requestPlaceholder')" />
            </label>
          </div>
          <div class="start-actions">
            <button v-if="sel" class="btn md" @click="fresh = false">{{ t("common.cancel") }}</button>
            <button class="btn dark lg" :disabled="creating" @click="create">{{ t("clips.suggest") }}</button>
          </div>
        </div>

        <!-- Claude travaille, rien à montrer encore -->
        <div v-else-if="S.running.value && !S.shorts.value.length" class="busy">
          <span class="mono busy-label">{{ t("clips.analyzing", { status: statusLabel }) }}</span>
          <div class="progress bar indeterminate"><div /></div>
          <button class="link-btn" @click="S.stop()">{{ t("common.stop") }}</button>
        </div>

        <template v-if="sel && !fresh">
          <p v-if="sel.status === 'error'" class="error">{{ t("clips.error", { error: sel.error ?? "" }) }}</p>
          <p v-else-if="lastMessage?.text" class="message">
            {{ lastMessage.text }}
            <span v-if="lastMessage.fixes" class="faint">{{ t("clips.fixes", lastMessage.fixes) }}</span>
          </p>

          <div v-for="s in S.shorts.value" :key="s.id" class="card" :class="{ on: short?.id === s.id }" @click="pick(s)">
            <div class="card-body">
              <span class="card-t"><span class="num mono">{{ num(s) }}</span>{{ s.title }}</span>
              <span class="card-d">{{ s.hook }}</span>
              <span class="card-l mono" :class="{ bad: tooLong(s) || s.errors.length }">{{ line(s) }}<template v-if="sent(s)">{{ t("clips.sentToEditing") }}</template></span>
              <ul v-if="s.errors.length" class="errors">
                <li v-for="e in s.errors" :key="e">{{ e }}</li>
              </ul>
              <div v-if="short?.id === s.id" class="exports" @click.stop>
                <a v-if="s.render?.url" class="link-btn" :href="`${s.render.url}&download=1`" :title="t('clips.mp4Title')">.mp4</a>
                <a class="link-btn" :href="`${S.base.value}/shorts/${s.id}/srt`" :title="t('clips.srtTitle')">.srt</a>
                <button class="link-btn" :title="t('clips.copyTitle')" @click="copyEdit(s)">{{ t("clips.copyEdit") }}</button>
              </div>
            </div>
            <div class="card-actions" @click.stop>
              <button class="btn md" :disabled="!media" @click="play(s)">{{ short?.id === s.id && player.playing.value ? t("clips.pause") : t("clips.play") }}</button>
              <button class="btn md dark" :disabled="opening === s.id" @click="onMount(s)">{{ sent(s) ? t("clips.openEdit") : t("clips.edit") }}</button>
              <button class="x-btn" :disabled="S.running.value" :title="t('clips.dismissTitle')" @click="remove(s)">×</button>
            </div>
          </div>

          <p v-if="!S.shorts.value.length && !S.running.value && sel.status !== 'error'" class="dashed-box">{{ t("clips.empty") }}</p>

          <!-- retouches : la suite de la discussion avec Claude -->
          <div v-if="S.shorts.value.length || !S.running.value" class="refine">
            <textarea
              v-model="reply" class="textarea soft" rows="2" :disabled="S.running.value"
              :placeholder="t('clips.refinePlaceholder')"
              @keydown.enter.exact.prevent="send()"
            />
            <button class="btn md dark" :disabled="S.running.value || !reply.trim()" @click="send()">{{ t("common.send") }}</button>
          </div>

          <div class="history">
            <select v-if="S.list.value.length > 1" class="input select" :value="sel.id" :title="t('clips.historyTitle')"
              @change="S.open(($event.target as HTMLSelectElement).value)">
              <option v-for="x in [...S.list.value].reverse()" :key="x.id" :value="x.id">{{ label(x) }}</option>
            </select>
            <span v-else class="mono faint">{{ label(sel) }}</span>
            <button class="link-btn" :disabled="S.running.value" @click="fresh = true; settingsOpen = true">{{ t("clips.newClips") }}</button>
            <button class="link-btn" :disabled="S.running.value" @click="S.removeSelection()">{{ t("clips.deleteClips") }}</button>
          </div>
        </template>
      </template>
    </div>

    <!-- aperçu : les extraits du short lus dans la vidéo source -->
    <aside v-if="short && sel && !fresh">
      <span class="preview-t">{{ short.title }}</span>
      <div class="phone hatch-dark" :class="{ wide: !vertical }">
        <video ref="video" preload="metadata" playsinline @click="player.toggle()" />
        <span v-if="caption" class="cap">{{ caption }}</span>
        <div class="pbar"><div :style="{ width: `${player.total.value ? (player.elapsed.value / player.total.value) * 100 : 0}%` }" /></div>
      </div>
      <div class="transport">
        <button class="btn dark play" :disabled="!media" @click="player.toggle()">{{ player.playing.value ? "❚❚" : "▶" }}</button>
        <span class="mono info">{{ t("clips.partOf", { i: part, n: short.clips.length, elapsed: mmss(player.elapsed.value), total: mmss(player.total.value) }) }}</span>
      </div>
      <label class="follow"><input v-model="follow" type="checkbox">{{ t("clips.follow") }}</label>
      <div class="tx">
        <span class="eyebrow">{{ t("clips.transcript") }}</span>
        <div ref="box" class="rows">
          <div v-for="r in rows" :key="r.i" :data-ri="r.i">
            <span v-if="r.head" class="row-head mono">{{ r.head }}</span>
            <div class="row" :class="{ on: r.i === cur, past: r.i < cur }" @click="seekRow(r)">
              <span class="tc mono">{{ mmss(r.t) }}</span>
              <span class="text">{{ r.text }}</span>
            </div>
          </div>
        </div>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.screen { padding: 20px 32px 40px; display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 28px; }
.main { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.dashed-box { display: flex; flex-direction: column; gap: 8px; align-items: center; }

.head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding-bottom: 4px; }
.retained { flex: 1; font-size: 14px; color: var(--muted); }
.status { font-size: 12px; color: var(--muted); }

.start {
  display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 36px 20px;
  border: 1px dashed var(--dash); border-radius: 4px; text-align: center;
}
.start-t { font-size: 14px; color: var(--muted); max-width: 420px; line-height: 1.5; text-wrap: pretty; }
.start .link-btn { font-size: 12.5px; }
.settings {
  display: grid; grid-template-columns: repeat(3, auto); gap: 14px 22px; justify-content: center;
  text-align: left; width: 100%; max-width: 620px; padding: 6px 0;
}
.field { display: flex; flex-direction: column; gap: 6px; }
.field.wide { grid-column: 1 / -1; }
.field .eyebrow { font-size: 10.5px; }
.field .input { height: 34px; font-size: 13.5px; }
.field .textarea { font-size: 13.5px; }
.select { height: 30px; padding: 0 8px; font-size: 13px; }
.start-actions { display: flex; gap: 8px; }

.busy {
  display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 44px 20px;
  border: 1px dashed var(--dash); border-radius: 4px;
}
.busy-label { font-size: 12.5px; color: var(--muted); }
.progress.bar { width: 260px; overflow: hidden; }
.progress.indeterminate > div { width: 30%; animation: slide 1.2s infinite ease-in-out; }
@keyframes slide { from { transform: translateX(-100%); } to { transform: translateX(340%); } }

.message { margin: 0 0 6px; font-size: 13.5px; line-height: 1.55; color: var(--muted); white-space: pre-wrap; text-wrap: pretty; }
.error { margin: 0; font-size: 13px; color: var(--red-ink); }

.card {
  display: flex; gap: 16px; padding: 16px; border: 1px solid var(--line); background: #fff; border-radius: 4px;
  align-items: flex-start; cursor: pointer; flex-wrap: wrap;
}
.card.on { border-color: var(--ink); background: var(--bg-softer); }
.card-body { flex: 1; min-width: 220px; display: flex; flex-direction: column; gap: 6px; }
.card-t { font-size: 15.5px; font-weight: 600; line-height: 1.35; }
.num { font-size: 11px; font-weight: 400; color: var(--faint); margin-right: 8px; }
.card-d { font-size: 13.5px; color: var(--muted); line-height: 1.5; text-wrap: pretty; }
.card-l { font-size: 11.5px; color: var(--faint); padding-top: 2px; }
.card-l.bad { color: var(--red-ink); }
.errors { margin: 0; padding-left: 16px; font-size: 12.5px; color: var(--red-ink); line-height: 1.45; }
.exports { display: flex; gap: 14px; padding-top: 4px; }
.exports .link-btn { font-size: 12.5px; }
.card-actions { display: flex; gap: 8px; align-items: center; }
.card-actions .x-btn { padding-left: 4px; }

.refine { display: flex; gap: 8px; align-items: flex-end; padding-top: 6px; }
.refine .textarea { flex: 1; font-size: 13.5px; resize: none; }
.history { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; padding-top: 10px; border-top: 1px solid var(--line-soft); margin-top: 6px; }
.history .mono { font-size: 11.5px; }
.history .select { max-width: 300px; }
.history .link-btn { font-size: 12.5px; }

aside { display: flex; flex-direction: column; gap: 10px; position: sticky; top: 0; align-self: start; }
.preview-t { font-size: 13px; font-weight: 600; line-height: 1.4; }
.phone {
  position: relative; height: 340px; aspect-ratio: 9 / 16; align-self: center; overflow: hidden;
  display: flex; align-items: flex-end; justify-content: center;
}
.phone.wide { height: auto; width: 100%; aspect-ratio: 16 / 9; }
.phone video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; cursor: pointer; }
.phone.wide video { object-fit: contain; }
.cap {
  position: relative; margin: 0 14px 28px; text-align: center; font-size: 14px; font-weight: 600; line-height: 1.35;
  color: #fff; text-wrap: pretty; text-shadow: 0 2px 8px rgba(0, 0, 0, .6); pointer-events: none;
}
.pbar { position: absolute; left: 0; right: 0; bottom: 0; height: 3px; background: rgba(255, 255, 255, .2); }
.pbar > div { height: 3px; background: var(--red); }
.transport { display: flex; align-items: center; gap: 10px; }
.btn.play { width: 40px; padding: 0; font-size: 12px; }
.info { font-size: 12px; color: var(--muted); }
.follow { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--muted); cursor: pointer; }
.follow input { accent-color: var(--red); margin: 0; }
.tx { display: flex; flex-direction: column; gap: 4px; border-top: 1px solid var(--line); padding-top: 8px; }
.tx .eyebrow { font-size: 11px; }
.rows { position: relative; height: 260px; overflow-y: auto; display: flex; flex-direction: column; }
.row-head { display: block; font-size: 11px; font-weight: 600; color: var(--muted); padding: 10px 8px 4px; }
.row { display: flex; gap: 10px; padding: 5px 8px; border-radius: 3px; cursor: pointer; }
.row:hover { background: var(--bg-soft); }
.row.on { background: var(--red-bg); }
.row .tc { width: 38px; flex-shrink: 0; font-size: 11px; color: var(--faint); padding-top: 2px; }
.row .text { flex: 1; font-size: 13.5px; line-height: 1.45; color: var(--ink-2); }
.row.on .text { font-weight: 600; }
.row.past .text { color: var(--faint); }
</style>
