<script setup lang="ts">
/**
 * À côté de l'aperçu : l'élément sélectionné (réglages, Commenter, Supprimer), la plage sélectionnée
 * (à confier au monteur), ou sinon de quoi ajouter au curseur (beat, zoom, texte, chapitre, et par la popup des médias :
 * rush, B-roll, son, musique). Une vidéo peut aussi s'insérer dans l'A-roll (depuis la popup, ou glissée sur sa piste).
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import Seg from "../../../components/Seg.vue";
import TransitionPicker from "../../../components/TransitionPicker.vue";
import type { Fx } from "../../../lib/transitions";
import { post } from "../../../lib/api";
import { duration as fmtDur } from "../../../lib/format";
import { toast } from "../../../lib/toast";
import MediaPicker from "./MediaPicker.vue";
import { addMedia as addMediaTo, addText as addTextTo, pauseOf, remove } from "./ops";
import {
  fxSpan, newId, prevJoined, spanOf, tcd, trackLabel, ZOOM_STYLES,
  type AvailableMedia, type ArollClip, type Broll, type MediaTab, type Marker, type MontageView, type Motion, type Selection, type Sound, type TextNote, type Timeline, type Zoom,
  type ZoomStyle,
} from "./types";

const props = defineProps<{
  tl: Timeline; view: MontageView; available: AvailableMedia[]; t: number; total: number;
}>();
const emit = defineEmits<{
  edit: [(t: Timeline) => void]; comment: [string?]; seek: [number]; insert: [AvailableMedia]; media: []; beat: []; rerender: [];
  /** mettre l'A-roll en pause sous un motion (on), ou la retirer */
  pause: [string, boolean];
}>();
const sel = defineModel<Selection | null>("selection", { required: true });
const { t: tr } = useI18n();

const item = computed(() => {
  const s = sel.value;
  if (!s || !("item" in s)) return null;
  const list = props.tl[s.item.track] as { id: string }[];
  const found = list.find((x) => x.id === s.item.id);
  return found ? { track: s.item.track, data: found } : null;
});
const range = computed(() => (sel.value && "range" in sel.value ? sel.value.range : null));
const span = computed(() => (item.value ? spanOf(props.tl, item.value.track, item.value.data.id) : null));
const kind = computed(() => {
  const it = item.value;
  if (!it) return "";
  if (it.track === "audio") return tr((it.data as Sound).role === "music" ? "editing.inspector.music" : "editing.inspector.sound");
  if (it.track === "markers") return tr("editing.inspector.chapter");
  return trackLabel(it.track);
});

/** Modifie l'élément sélectionné. */
function set<T>(change: (x: T) => void) {
  const it = item.value;
  if (!it) return;
  emit("edit", (tl) => {
    const x = (tl[it.track] as { id: string }[]).find((k) => k.id === it.data.id);
    if (x) change(x as T);
  });
}
/** L'entrée ou la sortie d'un B-roll ou d'un motion ; null : coupe franche. */
function setEnd(key: "enter" | "exit", v: Fx | null | undefined) {
  set<Broll | Motion>((x) => { if (v) x[key] = v; else delete x[key]; });
}
/** Le B-roll ou le motion sélectionné est collé au précédent de sa piste : son entrée s'enchaîne avec lui. */
const joined = computed(() => {
  const it = item.value;
  return !!it && (it.track === "broll" || it.track === "motion") && !!prevJoined(props.tl, it.track, it.data.id);
});

// --- une transition sélectionnée dans la timeline
const fx = computed(() => (sel.value && "item" in sel.value ? sel.value.item.fx ?? null : null));
const fxValue = computed(() => {
  const it = item.value;
  if (!it || !fx.value) return null;
  return fx.value === "transition" ? (it.data as ArollClip).transition : (it.data as Broll | Motion)[fx.value] ?? null;
});
const fxWhere = computed(() => (item.value && fx.value ? fxSpan(props.tl, item.value.track, item.value.data.id, fx.value) : null));
const fxTitle = computed(() => (fx.value === "transition" ? tr("transitions.withPrev")
  : fx.value === "enter" ? (joined.value ? tr("transitions.joinPrev") : tr("transitions.enter")) : tr("transitions.exit")));
function setFx(v: Fx | null | undefined) {
  if (fx.value === "transition") set<ArollClip>((x) => { x.transition = v ?? null; });
  else if (fx.value) setEnd(fx.value, v);
  // retirée : on revient à son plan
  if (!v && item.value) sel.value = { item: { track: item.value.track, id: item.value.data.id } };
}

function del() {
  const it = item.value;
  if (!it) return;
  emit("edit", (tl) => remove(tl, it.track, it.data.id));
  sel.value = null;
}
const nameOf = (src: string) => props.view.media[src]?.name ?? src.split("/").pop() ?? src;
const motionState = computed(() => (item.value?.track === "motion" ? props.view.motions[item.value.data.id] : null));
const paused = computed(() => (item.value?.track === "motion" ? !!pauseOf(props.tl, item.value.data.id) : false));
const pausedMotion = (id: string) => props.tl.motion.find((m) => m.id === id)?.title || id;

// --- ajouter au curseur
const at = computed(() => Math.min(props.t, Math.max(0, props.total - 0.5)));
/** l'onglet sur lequel la popup des médias est ouverte ; null : fermée */
const picker = ref<MediaTab | null>(null);
const MEDIA_BUTTONS = computed(() => [["rush", tr("editing.inspector.addRush")], ["broll", tr("editing.inspector.addBroll")],
  ["sfx", tr("editing.inspector.addSfx")], ["musique", tr("editing.inspector.addMusic")]] as const);

function addZoom(scale: number, style: ZoomStyle = "smooth", dur = 3) {
  let id = "";
  emit("edit", (tl) => {
    id = newId(tl, "z");
    tl.zooms.push({ id, at: round(at.value), dur, scale, x: 0, y: 0, ...(style === "smooth" ? {} : { style }) });
  });
  if (id) sel.value = { item: { track: "zooms", id } };
}
const zoomStyles = computed(() => ZOOM_STYLES.map((s) => [s, tr(`editing.inspector.zoomStyles.${s}`)] as const));
function setZoomStyle(style: ZoomStyle) {
  set<Zoom>((x) => { if (style === "smooth") delete x.style; else x.style = style; });
}
function addText() {
  let id = "";
  emit("edit", (tl) => { id = addTextTo(tl, at.value); });
  if (id) sel.value = { item: { track: "texts", id } };
}
/** les couleurs proposées pour un texte : blanc, jaune surligneur, rouge correction, cyan */
const TEXT_COLORS = ["#FFFFFF", "#FFE066", "#FF5A4E", "#7FE3FF"];
function addMedia(m: AvailableMedia) {
  let added = null as ReturnType<typeof addMediaTo> | null;
  emit("edit", (tl) => { added = addMediaTo(tl, m, at.value); });
  if (added) sel.value = { item: added };
}
function addChapter() {
  let id = "";
  emit("edit", (tl) => { id = newId(tl, "k"); tl.markers.push({ id, t: round(props.t), text: "", kind: "chapter", by: "user", done: false }); });
  if (id) sel.value = { item: { track: "markers", id } };
}
const round = (n: number) => Math.round(n * 1000) / 1000;
const num = (e: Event) => Number((e.target as HTMLInputElement).value);

/** Le son sélectionné tel que le connaît la bibliothèque (sa copie dans le projet porte le même nom). */
const libraryRel = computed(() => {
  const it = item.value;
  if (!it || it.track !== "audio") return null;
  const parts = (it.data as Sound).src.split("/");
  const rel = parts.slice(-2).join("/");
  return props.available.some((m) => m.src === `library/${rel}`) ? rel : null;
});
const libraryGain = computed(() => props.available.find((m) => m.src === `library/${libraryRel.value}`)?.gain_db);
/** Retient le volume du son sélectionné : les prochains seront posés à ce niveau. */
async function rememberGain() {
  const it = item.value;
  if (!libraryRel.value || !it) return;
  try {
    await post("/api/projects/library/gain", { rel: libraryRel.value, gain_db: (it.data as Sound).gain_db });
    emit("media");
    toast(tr("editing.inspector.gainRemembered", { gain: (it.data as Sound).gain_db }));
  } catch (err) {
    toast((err as Error).message, true);
  }
}
const fmtGain = (db?: number) => (db ? `${db > 0 ? "+" : ""}${db} dB` : "0 dB");
const SOUND_ROLES = computed(() => [["sfx", tr("editing.inspector.sound")], ["music", tr("editing.inspector.music")]] as const);
</script>

<template>
  <div class="inspector">
    <!-- une transition -->
    <template v-if="item && fx">
      <div class="head">
        <span class="eyebrow">{{ tr("transitions.selected") }}</span>
        <span class="mono time" @click="fxWhere && emit('seek', fxWhere[0])">{{ fxWhere ? `${tcd(fxWhere[0])} → ${tcd(fxWhere[1])}` : "" }}</span>
        <span class="spacer" />
        <button class="x-btn" :title="tr('editing.inspector.deselect')" @click="sel = null">×</button>
      </div>
      <fieldset>
        <TransitionPicker :title="fxTitle" :hint="joined && fx === 'enter' ? tr('transitions.enterHint') : undefined"
          :model-value="fxValue" @update:model-value="setFx" />
        <p class="hint">{{ tr("transitions.dragHint") }}</p>
      </fieldset>
      <div class="row actions">
        <button class="btn" @click="emit('comment')">{{ tr("common.comment") }}</button>
        <button class="link-btn" @click="setFx(null)">{{ tr("transitions.remove") }}</button>
      </div>
    </template>

    <!-- un élément -->
    <template v-else-if="item">
      <div class="head">
        <span class="eyebrow">{{ kind }}</span>
        <span class="mono time" @click="span && emit('seek', span[0])">{{ span ? (span[0] === span[1] ? tcd(span[0]) : `${tcd(span[0])} → ${tcd(span[1])}`) : "" }}</span>
        <span class="spacer" />
        <button class="x-btn" :title="tr('editing.inspector.deselect')" @click="sel = null">×</button>
      </div>
      <fieldset>
        <template v-if="item.track === 'aroll'">
          <template v-if="(item.data as ArollClip).pause">
            <span class="t">{{ tr("editing.pauseClip", { motion: pausedMotion((item.data as ArollClip).pause!) }) }}</span>
            <p class="hint">{{ tr("editing.inspector.pauseClipHint") }}</p>
          </template>
          <template v-else>
            <span class="t">{{ (item.data as ArollClip).src ? nameOf((item.data as ArollClip).src!) : tr("editing.inspector.sourceVideo") }}</span>
            <span class="mono sub">{{ tr("editing.inspector.inSource", { from: tcd((item.data as ArollClip).in), to: tcd((item.data as ArollClip).out), dur: fmtDur((item.data as ArollClip).out - (item.data as ArollClip).in) }) }}</span>
            <label class="f">{{ tr("editing.inspector.volume") }} <b class="mono">{{ fmtGain((item.data as ArollClip).gain_db) }}</b>
              <input type="range" min="-30" max="12" step="1" :value="(item.data as ArollClip).gain_db ?? 0"
                @input="set<ArollClip>((x) => { const v = num($event); if (v) x.gain_db = v; else delete x.gain_db; })"
                @dblclick="set<ArollClip>((x) => { delete x.gain_db; })">
            </label>
            <p v-if="(item.data as ArollClip).src" class="hint">{{ tr("editing.inspector.insertedHint") }}</p>
          </template>
          <TransitionPicker v-if="tl.aroll[0]?.id !== item.data.id" :title="tr('transitions.withPrev')"
            :model-value="(item.data as ArollClip).transition" @update:model-value="(v) => set<ArollClip>((x) => { x.transition = v ?? null; })" />
          <p class="hint">{{ tr("editing.inspector.arollHint") }}</p>
        </template>

        <template v-else-if="item.track === 'zooms'">
          <Seg size="sm" :options="zoomStyles" :model-value="(item.data as Zoom).style ?? 'smooth'" @update:model-value="setZoomStyle" />
          <p class="hint">{{ tr(`editing.inspector.zoomStyleHint.${(item.data as Zoom).style ?? "smooth"}`) }}</p>
          <label class="f">{{ tr("editing.inspector.scale") }} <b class="mono">×{{ (item.data as Zoom).scale.toFixed(2) }}</b>
            <input type="range" min="1.05" max="2" step="0.01" :value="(item.data as Zoom).scale" @input="set<Zoom>((x) => { x.scale = num($event); })">
          </label>
          <label class="f">{{ tr("editing.inspector.horizontal") }} <b class="mono">{{ (item.data as Zoom).x.toFixed(2) }}</b>
            <input type="range" min="-0.5" max="0.5" step="0.01" :value="(item.data as Zoom).x" @input="set<Zoom>((x) => { x.x = num($event); })">
          </label>
          <label class="f">{{ tr("editing.inspector.vertical") }} <b class="mono">{{ (item.data as Zoom).y.toFixed(2) }}</b>
            <input type="range" min="-0.5" max="0.5" step="0.01" :value="(item.data as Zoom).y" @input="set<Zoom>((x) => { x.y = num($event); })">
          </label>
        </template>

        <template v-else-if="item.track === 'broll'">
          <span class="t">{{ nameOf((item.data as Broll).src) }}</span>
          <span class="mono sub">{{ tr("editing.inspector.inMedia", { from: tcd((item.data as Broll).in), to: tcd((item.data as Broll).out) }) }}</span>
          <div class="ends">
            <TransitionPicker :title="joined ? tr('transitions.joinPrev') : tr('transitions.enter')" :hint="joined ? tr('transitions.enterHint') : undefined"
              :model-value="(item.data as Broll).enter" @update:model-value="(v) => setEnd('enter', v)" />
            <TransitionPicker :title="tr('transitions.exit')" :model-value="(item.data as Broll).exit" @update:model-value="(v) => setEnd('exit', v)" />
          </div>
        </template>

        <template v-else-if="item.track === 'motion'">
          <input class="input" :value="(item.data as Motion).title" :placeholder="tr('common.name')" @change="set<Motion>((x) => { x.title = ($event.target as HTMLInputElement).value; })">
          <span v-if="(item.data as Motion).kind" class="sub">{{ (item.data as Motion).kind }}</span>
          <label class="check" :title="tr('editing.inspector.pauseAroll.title')">
            <input type="checkbox" :checked="paused" @change="emit('pause', item.data.id, ($event.target as HTMLInputElement).checked)">
            {{ tr("editing.inspector.pauseAroll.label") }}
          </label>
          <p v-if="paused" class="hint">{{ tr("editing.inspector.pauseAroll.on") }}</p>
          <p v-if="(item.data as Motion).idea" class="idea">{{ (item.data as Motion).idea }}</p>
          <div class="ends">
            <TransitionPicker :title="joined ? tr('transitions.joinPrev') : tr('transitions.enter')" :hint="joined ? tr('transitions.enterHint') : undefined"
              :model-value="(item.data as Motion).enter" @update:model-value="(v) => setEnd('enter', v)" />
            <TransitionPicker :title="tr('transitions.exit')" :model-value="(item.data as Motion).exit" @update:model-value="(v) => setEnd('exit', v)" />
          </div>
          <span v-if="motionState" class="mono sub" :class="{ err: motionState.render === 'error' }">
            {{ motionState.render === "ready" ? tr("editing.inspector.renderReady") : motionState.render === "none" ? tr("editing.inspector.renderNone")
              : motionState.render === "error" ? tr("editing.inspector.renderError", { error: motionState.error ?? "" })
              : motionState.render === "rendering" ? tr("editing.inspector.renderProgress", { pct: Math.round(motionState.progress * 100) }) : tr("editing.inspector.renderPending") }}
          </span>
          <div v-if="motionState?.render === 'error'" class="row">
            <button class="btn sm" @click="emit('rerender')">{{ tr("editing.inspector.retryRender") }}</button>
            <button class="btn sm" @click="emit('comment', tr('editing.inspector.askFixRender', { id: item.data.id, error: motionState.error ?? '' }))">
              {{ tr("editing.inspector.fixRender") }}</button>
          </div>
        </template>

        <template v-else-if="item.track === 'audio'">
          <span class="t">{{ nameOf((item.data as Sound).src) }}</span>
          <label class="f">{{ tr("editing.inspector.volume") }} <b class="mono">{{ (item.data as Sound).gain_db }} dB</b>
            <input type="range" min="-40" max="6" step="1" :value="(item.data as Sound).gain_db" @input="set<Sound>((x) => { x.gain_db = num($event); })">
          </label>
          <button v-if="libraryRel && libraryGain !== (item.data as Sound).gain_db" class="link-btn" :title="tr('editing.inspector.rememberGainHint')"
            @click="rememberGain">{{ tr("editing.inspector.rememberGain", { gain: (item.data as Sound).gain_db }) }}</button>
          <Seg :model-value="(item.data as Sound).role" :options="SOUND_ROLES" size="sm"
            @update:model-value="(v: 'sfx' | 'music') => set<Sound>((x) => { x.role = v; })" />
        </template>

        <template v-else-if="item.track === 'texts'">
          <textarea class="input area" rows="3" :value="(item.data as TextNote).text" :placeholder="tr('editing.inspector.textPlaceholder')"
            @input="set<TextNote>((x) => { x.text = ($event.target as HTMLTextAreaElement).value; })" />
          <label class="f">{{ tr("editing.inspector.textSize") }} <b class="mono">{{ Math.round((item.data as TextNote).size * 1000) / 10 }} %</b>
            <input type="range" min="0.03" max="0.2" step="0.005" :value="(item.data as TextNote).size" @input="set<TextNote>((x) => { x.size = num($event); })">
          </label>
          <label class="f">{{ tr("editing.inspector.textAngle") }} <b class="mono">{{ (item.data as TextNote).angle }}°</b>
            <input type="range" min="-20" max="20" step="1" :value="(item.data as TextNote).angle"
              @input="set<TextNote>((x) => { x.angle = num($event); })" @dblclick="set<TextNote>((x) => { x.angle = 0; })">
          </label>
          <div class="row">
            <button v-for="c in TEXT_COLORS" :key="c" class="swatch" :class="{ on: (item.data as TextNote).color === c }" :style="{ background: c }"
              :title="c" @click="set<TextNote>((x) => { x.color = c; })" />
            <input type="color" class="color-picker" :value="(item.data as TextNote).color" :title="tr('editing.inspector.textColor')"
              @input="set<TextNote>((x) => { x.color = ($event.target as HTMLInputElement).value.toUpperCase(); })">
            <span class="spacer" />
            <button class="link-btn" @click="set<TextNote>((x) => { x.x = 0.5; x.y = 0.8; })">{{ tr("editing.inspector.textReset") }}</button>
          </div>
          <p class="hint">{{ tr("editing.inspector.textHint") }}</p>
        </template>

        <template v-else-if="item.track === 'markers'">
          <input class="input" :value="(item.data as Marker).text" :placeholder="tr('editing.inspector.chapterTitle')"
            @input="set<Marker>((x) => { x.text = ($event.target as HTMLInputElement).value; })">
          <span class="sub">{{ tr((item.data as Marker).by === "ai" ? "editing.inspector.byAi" : "editing.inspector.byUser") }}</span>
        </template>
      </fieldset>
      <div class="row actions">
        <button class="btn" @click="emit('comment')">{{ tr("common.comment") }}</button>
        <button class="link-btn" :disabled="item.track === 'aroll' && tl.aroll.length < 2" @click="del">{{ tr("common.delete") }}</button>
      </div>
    </template>

    <!-- une plage -->
    <template v-else-if="range">
      <div class="head">
        <span class="eyebrow">{{ tr("editing.inspector.range") }}</span>
        <span class="mono time">{{ tcd(range[0]) }} → {{ tcd(range[1]) }} · {{ fmtDur(range[1] - range[0]) }}</span>
        <span class="spacer" />
        <button class="x-btn" :title="tr('editing.inspector.clearRange')" @click="sel = null">×</button>
      </div>
      <p class="hint">{{ tr("editing.inspector.rangeHint") }}</p>
      <div class="chips">
        <button class="chip" @click="emit('comment', tr('editing.inspector.askMotion'))">{{ tr("editing.inspector.motionDesign") }}</button>
        <button class="chip" @click="emit('comment', tr('editing.inspector.askBroll'))">{{ tr("editing.inspector.broll") }}</button>
        <button class="chip" @click="emit('comment', tr('editing.inspector.askZooms'))">{{ tr("editing.inspector.zooms") }}</button>
        <button class="chip" @click="emit('comment', tr('editing.inspector.askSound'))">{{ tr("editing.inspector.soundDesign") }}</button>
        <button class="chip" @click="emit('comment')">{{ tr("editing.inspector.otherRequest") }}</button>
      </div>
    </template>

    <!-- rien : ajouter au curseur -->
    <template v-else>
      <span class="eyebrow">{{ tr("editing.inspector.addAtCursor", { tc: tcd(t) }) }}</span>
      <fieldset class="adds">
        <div class="row">
          <button class="btn sm" @click="addZoom(1.15)">{{ tr("editing.inspector.zoomLight") }}</button>
          <button class="btn sm" @click="addZoom(1.35)">{{ tr("editing.inspector.zoomStrong") }}</button>
          <button class="btn sm" :title="tr('editing.inspector.zoomStyleHint.cut')" @click="addZoom(1.3, 'cut', 2)">{{ tr("editing.inspector.zoomCut") }}</button>
          <button class="btn sm" :title="tr('editing.inspector.zoomStyleHint.slow')" @click="addZoom(1.1, 'slow', 8)">{{ tr("editing.inspector.zoomSlow") }}</button>
          <button class="btn sm" :title="tr('editing.inspector.addTextTitle')" @click="addText">{{ tr("editing.inspector.addText") }}</button>
          <button class="btn sm" :title="tr('editing.inspector.addBeatTitle')" @click="emit('beat')">{{ tr("editing.inspector.addBeat") }}</button>
          <button class="btn sm" @click="addChapter">{{ tr("editing.inspector.addChapter") }}</button>
        </div>
        <div class="row">
          <button v-for="[k, label] in MEDIA_BUTTONS" :key="k" class="btn sm" @click="picker = k">{{ label }}</button>
        </div>
      </fieldset>
      <p class="hint">{{ tr("editing.inspector.motionHint") }}</p>
    </template>
    <MediaPicker v-model="picker" :available="available" :t="t" @add="addMedia" @insert="(m) => emit('insert', m)" />
  </div>
</template>

<style scoped>
.ends { display: flex; flex-direction: column; gap: 10px; margin-top: 4px; }
.inspector { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
fieldset { border: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.head { display: flex; align-items: center; gap: 10px; }
.head .eyebrow { font-size: 10.5px; }
.time { font-size: 12px; color: var(--muted); cursor: pointer; }
.t { font-size: 14.5px; font-weight: 600; word-break: break-all; }
.sub { font-size: 12px; color: var(--muted); }
.sub.err { color: var(--red-ink); }
.idea { margin: 0; font-size: 13px; color: var(--muted); line-height: 1.5; }
.f { display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; color: var(--muted); }
.f b { font-weight: 500; color: var(--ink); }
.f input[type="range"] { accent-color: var(--ink); }
.check { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--ink); cursor: pointer; }
.check input { accent-color: var(--ink); margin: 0; }
.input { height: 36px; padding: 0 10px; font-size: 13.5px; }
.input.area { height: auto; padding: 8px 10px; resize: vertical; font-family: inherit; line-height: 1.4; }
.swatch { width: 20px; height: 20px; border-radius: 50%; border: 1px solid var(--line-strong); cursor: pointer; padding: 0; }
.swatch.on { outline: 2px solid var(--ink); outline-offset: 1px; }
.color-picker { width: 26px; height: 22px; padding: 0; border: none; background: none; cursor: pointer; }
.row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.actions .link-btn { font-size: 12.5px; }
.hint { margin: 0; font-size: 12px; color: var(--faint); line-height: 1.5; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { border: 1px solid var(--line-strong); border-radius: 3px; background: #fff; padding: 5px 9px; font-size: 12.5px; cursor: pointer; }
.chip:hover { border-color: var(--ink); }
</style>
