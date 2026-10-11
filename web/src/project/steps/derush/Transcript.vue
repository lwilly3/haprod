<script setup lang="ts">
/**
 * Le transcript de la timeline, bout par bout : ce qu'on lit est ce qu'on obtiendra.
 * Clic sur un mot = la lecture s'y place et sa phrase est sélectionnée ; sélectionner du texte à la
 * souris = une plage au mot près. Suppr retire la sélection de la timeline ; ✂ retire la phrase.
 */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { mmss } from "../../../lib/format";
import type { DerushClip, DerushSeg } from "../../types";
import { clipLen, offsets, type Selection } from "./clips";
import { useFollowScroll, type Playlist } from "./usePlaylist";

const props = defineProps<{
  clips: DerushClip[]; segs: Record<string, DerushSeg[]>; player: Playlist; names: Record<string, string>;
}>();
const emit = defineEmits<{ remove: [a: number, b: number] }>();
const sel = defineModel<Selection>("selection", { required: true });
const { t } = useI18n();

/** Un mot ou un silence, à sa place sur la timeline [a, b] ; [pa, pb] est sa phrase (ou son silence). */
interface Tok { n: number; a: number; b: number; pa: number; pb: number; text: string; sil: boolean; voice?: boolean; type: DerushSeg["type"]; clip: string }
interface Line { n: number; head: string; start: number; toks: Tok[] }

const model = computed(() => {
  const lines: Line[] = [], toks: Tok[] = [], o = offsets(props.clips);
  props.clips.forEach((c, k) => {
    const at = (rt: number) => o[k] + rt - c.in;
    let line: Line = { n: lines.length, head: `${props.names[c.rush] ?? c.rush} · ${mmss(c.in)} → ${mmss(c.out)}`, start: o[k], toks: [] };
    lines.push(line);
    const open = () => { line = { n: lines.length, head: "", start: 0, toks: [] }; lines.push(line); };
    const push = (tok: Omit<Tok, "n">) => {
      const full = { ...tok, n: toks.length };
      if (!line.toks.length) line.start = full.a;
      line.toks.push(full);
      toks.push(full);
    };
    for (const s of props.segs[c.rush] ?? []) {
      if (s.end <= c.in || s.start >= c.out) continue;
      const pa = at(Math.max(s.start, c.in)), pb = at(Math.min(s.end, c.out));
      if (pb - pa < 0.01) continue;
      const hasSpeech = line.toks.some((x) => !x.sil);
      if (s.type === "sil") {
        if (hasSpeech) open();
        push({ a: pa, b: pb, pa, pb, sil: true, type: s.type, clip: c.id, text: `${(pb - pa).toFixed(1).replace(".", ",")} s` });
        continue;
      }
      if (hasSpeech) open();
      const words = s.words.filter((w) => w[0] >= c.in && w[0] < c.out);
      if (!words.length) {
        // du son sans mots : de la voix que Whisper n'a pas transcrite, ou un bruit
        push({ a: pa, b: pb, pa, pb, sil: false, voice: true, type: s.type, clip: c.id,
          text: t("derush.untranscribed", { d: (pb - pa).toFixed(1).replace(".", ",") }) });
        continue;
      }
      words.forEach((w, j) => push({
        a: j ? at(w[0]) : pa, b: j < words.length - 1 ? at(words[j + 1][0]) : pb,
        pa, pb, sil: false, type: s.type, clip: c.id, text: w[2],
      }));
    }
    if (!line.toks.length && !line.head) lines.pop();
  });
  return { lines, toks };
});
const total = computed(() => props.clips.reduce((a, c) => a + clipLen(c), 0));

// --- sélection surlignée
const selIds = computed(() => new Set(sel.value && "clips" in sel.value ? sel.value.clips : []));
function inSel(k: Tok) {
  if (selIds.value.has(k.clip)) return true;
  if (!sel.value || !("range" in sel.value)) return false;
  const [a, b] = sel.value.range;
  return k.a < b - 1e-3 && k.b > a + 1e-3;
}

// --- le mot en cours de lecture : marqué sans redessiner tout le transcript, et suivi au défilement
const box = ref<HTMLElement | null>(null);
const nowTok = computed(() => {
  const ts = model.value.toks, time = props.player.t.value;
  let lo = 0, hi = ts.length - 1;
  if (hi < 0 || ts[0].a > time) return -1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (ts[mid].a <= time) lo = mid; else hi = mid - 1;
  }
  return lo;
});
const lineOf = computed(() => {
  const m = new Map<number, number>();
  for (const l of model.value.lines) for (const k of l.toks) m.set(k.n, l.n);
  return m;
});
const curLine = computed(() => lineOf.value.get(nowTok.value) ?? -1);
const { skipNext } = useFollowScroll(box, curLine);
watch([nowTok, model], ([n], old) => {
  box.value?.querySelector(`[data-w="${old?.[0]}"]`)?.classList.remove("now");
  box.value?.querySelector(`[data-w="${n}"]`)?.classList.add("now");
}, { flush: "post" });

function onMouseUp(e: MouseEvent) {
  const toks = model.value.toks, ds = window.getSelection();
  if (!ds || ds.isCollapsed || !box.value?.contains(ds.anchorNode)) {
    const el = (e.target as HTMLElement).closest<HTMLElement>("[data-w]");
    if (!el) return;
    const k = toks[Number(el.dataset.w)];
    skipNext();
    props.player.seek(k.a);
    sel.value = { range: [k.pa, k.pb] };
    return;
  }
  const r = ds.getRangeAt(0);
  const hit = [...box.value.querySelectorAll<HTMLElement>("[data-w]")].filter((el) => r.intersectsNode(el));
  ds.removeAllRanges();
  if (!hit.length) return;
  const a = toks[Number(hit[0].dataset.w)].a, b = toks[Number(hit[hit.length - 1].dataset.w)].b;
  skipNext();
  props.player.seek(a);
  sel.value = { range: [a, b] };
}

/** ✂ : retire la phrase de la ligne (une ligne sans parole : son silence). */
function cutLine(l: Line) {
  const speech = l.toks.filter((k) => !k.sil), list = speech.length ? speech : l.toks;
  emit("remove", list[0].a, list[list.length - 1].b);
}
</script>

<template>
  <div ref="box" class="lines" @mouseup="onMouseUp">
    <div v-if="!total" class="none">{{ t("derush.transcriptEmpty") }}</div>
    <div v-for="l in model.lines" :key="l.n" :data-li="l.n">
      <div v-if="l.head" class="clip-head">{{ l.head }}</div>
      <div v-if="l.toks.length" class="line" :class="{ on: l.n === curLine }">
        <span class="gutter">
          <span class="tc" :title="t('derush.jumpTo')" @click="skipNext(); player.seek(l.start)">{{ mmss(l.start) }}</span>
          <button class="scissors" :title="t('derush.transcriptTools.cutLine')" @mousedown.prevent @click.stop="cutLine(l)">✂</button>
        </span>
        <p>
          <span v-for="k in l.toks" :key="k.n" :data-w="k.n" class="w"
            :class="[k.type, { sil: k.sil, voice: k.voice, sel: inSel(k) }]">{{ k.text }}</span>
        </p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lines { position: absolute; inset: 0; overflow-y: auto; display: flex; flex-direction: column; padding-right: 8px; }
.none { padding: 24px; color: var(--muted); font-size: 13.5px; }
.clip-head {
  font-family: var(--mono); font-size: 11px; font-weight: 600; color: var(--muted);
  padding: 12px 12px 5px; border-bottom: 1px solid var(--line);
}
.line { display: flex; gap: 10px; padding: 6px 10px; border-left: 2px solid transparent; }
.line.on { border-left-color: var(--red); background: var(--bg-softer); }
.gutter { width: 42px; flex-shrink: 0; display: flex; flex-direction: column; align-items: flex-start; gap: 2px; padding-top: 5px; }
.tc { font-family: var(--mono); font-size: 11.5px; color: var(--faint); cursor: pointer; }
.tc:hover { color: var(--ink); }
.scissors {
  visibility: hidden; border: 1px solid var(--line-strong); background: #fff; border-radius: 3px;
  font-size: 11px; height: 20px; padding: 0 6px; cursor: pointer; color: var(--ink-3);
}
.line:hover .scissors { visibility: visible; }
.scissors:hover { border-color: var(--red); color: var(--red-ink); }
.line p { margin: 0; font-size: 15px; line-height: 1.85; text-wrap: pretty; color: var(--ink-2); }
.w { cursor: text; border-radius: 2px; }
.w:hover { background: #EDEDEA; }
.w.retake { text-decoration: underline wavy var(--faint); }
.w.sil {
  font-family: var(--mono); font-size: 11px; padding: 2px 6px; margin-right: 0.35em; color: #6E6F6B;
  background: var(--line-soft); cursor: pointer;
}
.w.sil::before { content: "⏸ "; }
.w.voice {
  font-family: var(--mono); font-size: 11px; padding: 2px 6px; margin-right: 0.35em; color: #8A5A12;
  background: #FBF1DC; cursor: pointer;
}
.w.voice::before { content: "♪ "; }
.w.sel { background: var(--red-bg); }
.w.now { box-shadow: inset 0 -2px 0 var(--red); }
</style>
