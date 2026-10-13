<script setup lang="ts">
/**
 * Description : titre, description et tags de chaque vidéo (la longue et les shorts de la sélection).
 * La vidéo longue a aussi sa vignette, son test A/B (jusqu'à 3 couples titre + vignette) et ses
 * chapitres, tirés des marqueurs du montage ; un short montre son passage et peut renvoyer à la longue.
 * Ce qu'on insère (chapitres, lien) se place au-dessus de la description par défaut des réglages.
 */
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../../lib/api";
import { usePref } from "../../lib/composables";
import { contentText, contentTextAll, loadChannelLanguage } from "../../lib/content";
import { mmss } from "../../lib/format";
import { toast } from "../../lib/toast";
import { store } from "../store";
import {
  MAX_DESC, MAX_TITLE, MAX_VARIANTS, metaMissing, thumbUrl, titleCount, titleOk, usePublish, type Video,
} from "./publish/usePublish";

const { t: tr } = useI18n();
const project = computed(() => store.project!);
const P = usePublish(project);
const selId = usePref<string>(`publish.sel.${project.value.id}`, "long");
const sel = computed<Video | undefined>(() => P.videos.value.find((v) => v.id === selId.value) ?? P.videos.value[0]);
const newTag = ref("");

const set = (patch: Parameters<typeof P.setMeta>[1]) => sel.value && P.setMeta(sel.value.id, patch);

// --- vignettes : les variantes de l'étape Vignette qui ont une image
const thumbOptions = computed(() => project.value.thumbs
  .filter((t) => t.id && thumbUrl(project.value, t.id))
  .map((t) => ({ id: t.id!, label: `${t.v}${t.text ? ` · ${t.text}` : ""}` })));

// --- test A/B : la variante A (titre et vignette de la vidéo), puis B et C
const variants = computed(() => {
  const m = sel.value?.meta;
  if (!m) return [];
  return [{ thumb: m.thumb ?? null, title: m.title }, ...(m.ab ?? [])].map((a, i) => ({ ...a, l: "ABC"[i], i }));
});
function setVariant(i: number, patch: { thumb?: string | null; title?: string }) {
  if (i === 0) return set(patch);
  const ab = [...(sel.value!.meta.ab ?? [])];
  ab[i - 1] = { ...ab[i - 1], ...patch };
  set({ ab });
}
const addVariant = () => set({ ab: [...(sel.value!.meta.ab ?? []), { thumb: sel.value!.meta.thumb ?? null, title: "" }] });
const removeVariant = (i: number) => set({ ab: (sel.value!.meta.ab ?? []).filter((_, j) => j !== i - 1) });

// --- tags
function addTag() {
  const t = newTag.value.trim().replace(/^#/, "");
  if (!t || !sel.value) return;
  if (!sel.value.meta.tags.includes(t)) set({ tags: [...sel.value.meta.tags, t] });
  newTag.value = "";
}
const removeTag = (t: string) => set({ tags: sel.value!.meta.tags.filter((x) => x !== t) });

// les textes insérés dans la description sont dans la langue de la chaîne
loadChannelLanguage();

// --- la description par défaut (réglages) : le bloc commun, qu'on garde en bas
const footer = ref("");
onMounted(async () => {
  footer.value = (await api<{ description: string }>("/api/settings/publish").catch(() => ({ description: "" }))).description;
});
/** Ajoute un bloc à la description : juste au-dessus du bloc commun s'il y est, sinon à la fin. */
function insert(desc: string, block: string): string {
  const at = footer.value ? desc.lastIndexOf(footer.value) : -1;
  if (at < 0) return `${desc.trimEnd()}${desc.trim() ? "\n\n" : ""}${block}`;
  const head = desc.slice(0, at).trimEnd();
  return `${head}${head ? "\n\n" : ""}${block}\n\n${desc.slice(at)}`;
}

// --- chapitres (vidéo longue)
const chaptersText = computed(() => (sel.value?.chapters ?? []).map((c) => `${c.t} ${c.label}`).join("\n"));
function insertChapters() {
  const m = sel.value!.meta;
  if (m.desc.includes("00:00")) return toast(tr("details.chaptersAlready"));
  set({ desc: insert(m.desc, `${contentText("chapters")}\n${chaptersText.value}`) });
  toast(tr("details.chaptersInserted"));
}

// --- lien vers la vidéo longue (short)
const longVideo = computed(() => P.videos.value.find((v) => v.kind === "long"));
function addLongLink() {
  const m = sel.value!.meta;
  const url = longVideo.value?.upload?.url;
  const prefix = contentText("fullVideo");
  const line = `${prefix} ${url || P.longTitle.value}`;
  // déjà là, même ajouté quand la chaîne avait une autre langue
  if (contentTextAll("fullVideo").some((p) => m.desc.includes(p))) return toast(tr("details.linkAlready"));
  set({ desc: insert(m.desc, line) });
  toast(url ? tr("details.linkAdded") : tr("details.linkPending"));
}

async function copyAll() {
  const v = sel.value!;
  const tags = v.kind === "short" ? v.meta.tags.map((t) => `#${t}`).join(" ") : v.meta.tags.join(", ");
  await navigator.clipboard.writeText([v.meta.title, v.meta.desc, tags].filter(Boolean).join("\n\n"));
  toast(tr("details.copied", { name: v.name }));
}

const status = (v: Video) => (metaMissing(v).length ? tr("details.todo") : "✓");
</script>

<template>
  <div v-if="!P.data.value" class="eyebrow pad">{{ tr("common.loading") }}</div>
  <div v-else-if="sel" class="screen">
    <nav class="list">
      <span class="eyebrow head">{{ tr("details.videos", { n: P.videos.value.length }) }}</span>
      <button v-for="v in P.videos.value" :key="v.id" class="vid" :class="{ on: v.id === sel.id }" @click="selId = v.id; newTag = ''">
        <span class="vid-top">
          <span class="vid-name">{{ v.name }}</span>
          <span class="mono vid-st" :class="{ bad: metaMissing(v).length }">{{ status(v) }}</span>
        </span>
        <span class="vid-title">{{ v.meta.title }}</span>
      </button>
    </nav>

    <div class="main">
      <div class="name-row">
        <span class="name">{{ sel.name }}</span>
        <span class="mono faint">{{ sel.format }} · {{ mmss(sel.duration) }}</span>
      </div>

      <!-- vidéo longue : test A/B (titre et vignette) -->
      <div v-if="sel.kind === 'long' && sel.meta.ab_on" class="field">
        <div class="lab-row">
          <label>{{ tr("details.abLabel") }}</label>
          <span class="mono faint small">{{ tr("details.variantCount", { n: variants.length, max: MAX_VARIANTS }) }}</span>
          <span class="spacer" />
          <RouterLink :to="`/p/${project.id}/vignette`" class="link">{{ tr("details.thumbnails") }}</RouterLink>
          <button class="link-btn link" @click="set({ ab_on: false })">{{ tr("details.abOff") }}</button>
        </div>
        <div v-for="a in variants" :key="a.i" class="variant">
          <span class="mono letter">{{ a.l }}</span>
          <div class="v-thumb">
            <img v-if="thumbUrl(project, a.thumb)" :src="thumbUrl(project, a.thumb)!" alt="" class="img">
            <div v-else class="img hatch" />
            <select class="select" :value="a.thumb ?? ''" @change="setVariant(a.i, { thumb: ($event.target as HTMLSelectElement).value || null })">
              <option value="" disabled>{{ tr("details.choose") }}</option>
              <option v-for="o in thumbOptions" :key="o.id" :value="o.id">{{ o.label }}</option>
            </select>
          </div>
          <div class="v-title">
            <textarea class="textarea" :class="{ bad: !titleOk(a.title) }" rows="3" :placeholder="tr('details.variantTitle')"
              :value="a.title" @input="setVariant(a.i, { title: ($event.target as HTMLTextAreaElement).value })" />
            <div class="v-foot">
              <span class="mono small" :class="a.title.length > MAX_TITLE ? 'red' : 'faint'">{{ titleCount(a.title) }}</span>
              <span class="spacer" />
              <button v-if="a.i > 0" class="link-btn small" @click="removeVariant(a.i)">{{ tr("common.remove") }}</button>
            </div>
          </div>
        </div>
        <button v-if="variants.length < MAX_VARIANTS" class="btn add" @click="addVariant">{{ tr("details.addVariant") }}</button>
        <span class="note">{{ tr("details.abNote") }}</span>
      </div>

      <!-- titre seul (short, ou vidéo longue sans test) -->
      <template v-else>
        <div class="field">
          <div class="lab-row">
            <label>{{ tr("details.title") }}</label>
            <span class="spacer" />
            <button v-if="sel.kind === 'long'" class="link-btn link" @click="set({ ab_on: true })">{{ tr("details.abOn") }}</button>
            <span class="mono small" :class="sel.meta.title.length > MAX_TITLE ? 'red' : 'faint'">{{ titleCount(sel.meta.title) }}</span>
          </div>
          <input class="input title-input" :value="sel.meta.title" @input="set({ title: ($event.target as HTMLInputElement).value })">
        </div>
        <div v-if="sel.kind === 'long'" class="thumb-row">
          <img v-if="thumbUrl(project, sel.meta.thumb)" :src="thumbUrl(project, sel.meta.thumb)!" alt="" class="img sm">
          <div v-else class="img sm hatch" />
          <select class="select" :value="sel.meta.thumb ?? ''" @change="set({ thumb: ($event.target as HTMLSelectElement).value || null })">
            <option value="" disabled>{{ tr("details.chooseThumbnail") }}</option>
            <option v-for="o in thumbOptions" :key="o.id" :value="o.id">{{ o.label }}</option>
          </select>
          <RouterLink :to="`/p/${project.id}/vignette`" class="link">{{ tr("details.change") }}</RouterLink>
        </div>
      </template>

      <div class="field">
        <div class="lab-row">
          <label>{{ tr("details.description") }}</label>
          <span class="spacer" />
          <span class="mono small" :class="sel.meta.desc.length > MAX_DESC ? 'red' : 'faint'">{{ sel.meta.desc.length }}/{{ MAX_DESC }}</span>
        </div>
        <textarea class="textarea desc" :class="{ short: sel.kind === 'short' }" :value="sel.meta.desc"
          @input="set({ desc: ($event.target as HTMLTextAreaElement).value })" />
      </div>

      <div class="field">
        <label>{{ sel.kind === "long" ? tr("details.tags") : tr("details.hashtags") }}</label>
        <div class="tags">
          <span v-for="t in sel.meta.tags" :key="t" class="tag">{{ sel.kind === "short" ? `#${t}` : t }}
            <button class="x-btn" @click="removeTag(t)">×</button></span>
          <input v-model="newTag" class="tag-input" :placeholder="tr('details.tagPlaceholder')" @keydown.enter.prevent="addTag">
        </div>
      </div>
    </div>

    <aside class="side">
      <template v-if="sel.kind === 'long'">
        <span class="eyebrow">{{ tr("details.chaptersFromEdit") }}</span>
        <div v-for="(c, i) in sel.chapters" :key="i" class="chap"><span class="mono">{{ c.t }}</span><span>{{ c.label }}</span></div>
        <i18n-t v-if="!sel.chapters?.length" keypath="details.noChapters" tag="p" class="hint" scope="global">
          <template #editing><RouterLink :to="`/p/${project.id}/montage`">{{ tr("details.editing") }}</RouterLink></template>
        </i18n-t>
        <button class="btn dark wide" :disabled="!sel.chapters?.length" @click="insertChapters">{{ tr("details.insertChapters") }}</button>
      </template>
      <template v-else>
        <span class="eyebrow">{{ tr("details.passage") }}</span>
        <p class="passage">{{ tr("details.quoted", { text: sel.passage }) }}</p>
        <button class="btn dark wide" @click="addLongLink">{{ tr("details.addRelated") }}</button>
      </template>
      <button class="btn wide" @click="copyAll">{{ tr("details.copyAll") }}</button>
    </aside>
  </div>
</template>

<style scoped>
.pad { padding: 32px; }
.screen { padding: 20px 32px 40px; display: grid; grid-template-columns: 210px minmax(0, 1fr) 260px; gap: 28px; align-items: start; }
.list { display: flex; flex-direction: column; gap: 6px; }
.head { padding-bottom: 4px; }
.vid {
  display: flex; flex-direction: column; gap: 3px; padding: 9px 11px; border-radius: 4px; cursor: pointer; text-align: left;
  background: transparent; border: 1px solid var(--line); min-width: 0;
}
.vid:hover, .vid.on { border-color: var(--ink); }
.vid.on { background: #fff; }
.vid-top { display: flex; align-items: center; gap: 8px; }
.vid-name { font-size: 13.5px; font-weight: 500; flex: 1; }
.vid-st { font-size: 11px; color: var(--ink); }
.vid-st.bad { color: var(--red-ink); }
.vid-title { font-size: 12px; color: var(--muted-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.main { display: flex; flex-direction: column; gap: 20px; min-width: 0; }
.name-row { display: flex; align-items: baseline; gap: 10px; }
.name { font-size: 16px; font-weight: 600; }
.field { display: flex; flex-direction: column; gap: 8px; }
.field label { font-size: 13px; font-weight: 500; }
.lab-row { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.spacer { flex: 1; }
.small { font-size: 11.5px; }
.red { color: var(--red-ink); }
.link { font-size: 12.5px; color: var(--muted) !important; text-decoration: underline !important; }
.title-input { height: 44px; font-size: 15px; padding: 0 12px; }
.desc { min-height: 260px; font-size: 14px; line-height: 1.6; padding: 12px; resize: vertical; }
.desc.short { min-height: 140px; }
.variant { display: grid; grid-template-columns: 18px 120px minmax(0, 1fr); gap: 10px; align-items: start; padding: 10px 0; border-top: 1px solid var(--line-soft); }
.letter { font-size: 13px; font-weight: 600; padding-top: 6px; }
.v-thumb { display: flex; flex-direction: column; gap: 6px; }
.img { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; border-radius: 3px; display: block; }
.img.sm { width: 96px; }
.select { height: 28px; border: 1px solid var(--line-strong); border-radius: 4px; background: #fff; font-size: 12px; padding: 0 4px; min-width: 0; }
.v-title { display: flex; flex-direction: column; gap: 4px; }
.v-title .textarea { font-size: 14px; line-height: 1.4; padding: 8px 10px; resize: none; }
.textarea.bad { border-color: var(--red); }
.v-foot { display: flex; align-items: center; gap: 8px; }
.add { align-self: flex-start; }
.note { font-size: 12.5px; color: var(--muted-2); line-height: 1.5; }
.thumb-row { display: flex; align-items: center; gap: 12px; font-size: 13px; color: var(--muted); }
.thumb-row .select { width: 260px; height: 30px; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 8px; border: 1px solid var(--line-input); border-radius: 4px; }
.tag { display: flex; align-items: center; gap: 6px; padding: 4px 8px; background: var(--line-soft); border-radius: 3px; font-size: 13px; }
.tag-input { flex: 1; min-width: 120px; border: none; height: 28px; font-size: 13px; }
.app .tag-input:focus { outline: none; }

.side { display: flex; flex-direction: column; gap: 10px; }
.chap { display: flex; gap: 12px; padding: 7px 0; border-top: 1px solid var(--line-soft); font-size: 13.5px; }
.chap .mono { font-size: 12.5px; }
.hint { margin: 0; font-size: 13px; color: var(--muted-2); line-height: 1.5; }
.passage { margin: 0; font-size: 13.5px; line-height: 1.55; font-style: italic; padding: 10px 0; border-top: 1px solid var(--line-soft); }
.wide { height: 36px; font-size: 13.5px; }
</style>
