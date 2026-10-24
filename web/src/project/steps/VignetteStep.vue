<script setup lang="ts">
/**
 * Vignette : des variantes pour l'A/B test, chacune associée à l'un des titres retenus. Pour la générer
 * avec fal.ai : sa description, le texte que le modèle écrit dans l'image, ses portraits et ses vignettes
 * de style (pris dans la bibliothèque) ; plusieurs modèles peuvent tourner en parallèle, leurs images
 * s'ajoutent à la galerie de la variante. L'image générée est la vignette telle quelle : rien n'est posé dessus.
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import ConfirmX from "../../components/ConfirmX.vue";
import Seg from "../../components/Seg.vue";
import { post } from "../../lib/api";
import { toast } from "../../lib/toast";
import { act, failed, running, store, update } from "../store";
import type { Thumb, ThumbIdea, ThumbImage } from "../types";
import LibraryPicker from "./vignette/LibraryPicker.vue";
import VariantTile from "./vignette/VariantTile.vue";
import { refUrl } from "./vignette/refs";

// le plafond d'images de référence de fal (backend projects/thumbs.py)
const MAX_REFS = 10;
const MODELS_KEY = "studio.thumbModels";

const router = useRouter();
const { t: tr } = useI18n();
const project = computed(() => store.project!);
const angle = computed(() => {
  const p = project.value;
  return p.angle_sel != null ? p.angles[p.angle_sel] ?? null : null;
});
/** Les titres qu'on peut associer à une variante : ceux retenus à l'étape Titre, sinon tous. */
const titleChoices = computed(() => {
  const picked = project.value.titles.filter((t) => t.pick).map((t) => t.t);
  return picked.length ? picked : project.value.titles.map((t) => t.t);
});
/** Le titre d'une variante : celui qu'on lui a associé, sinon le premier retenu, sinon celui de l'angle. */
const titleOf = (t: Thumb | null) => t?.title || titleChoices.value[0] || angle.value?.t || project.value.title;
/** Le titre proposé pour la n-ième variante : les titres retenus, à tour de rôle. */
const defaultTitle = (n: number) => titleChoices.value.length ? titleChoices.value[n % titleChoices.value.length] : undefined;
const thumbs = computed(() => project.value.thumbs);
const sel = computed(() => project.value.thumb_sel);
const current = computed(() => thumbs.value[sel.value ?? 0] ?? null);

const newId = () => Math.random().toString(36).slice(2, 10);

onMounted(() => {
  if (!thumbs.value.length) {
    update({ thumbs: [{ id: newId(), v: "v1", text: "", title: defaultTitle(0) }], thumb_sel: 0 });
    return;
  }
  // les variantes d'avant : sans identifiant, sans titre, ou avec le réglage du texte posé par-dessus
  // (retiré : le texte est toujours écrit par le modèle, le texte par défaut ne doit pas finir dans l'image)
  type Legacy = Thumb & { text_in_image?: boolean };
  const legacy = (t: Legacy) => !t.id || (!t.title && !!titleChoices.value.length) || "text_in_image" in t || t.text === "NOUVEAU TEXTE";
  if (thumbs.value.some(legacy)) {
    update({
      thumbs: thumbs.value.map((t: Legacy, i) => {
        if (!legacy(t)) return t;
        const { text_in_image: _, ...rest } = t;
        return { ...rest, id: t.id || newId(), title: t.title || defaultTitle(i), text: t.text === "NOUVEAU TEXTE" ? "" : t.text };
      }),
    });
  }
});

function edit(t: Thumb, changes: Partial<Thumb>, delay = 0) {
  update({ thumbs: thumbs.value.map((x) => (x === t ? { ...x, ...changes } : x)) }, delay);
}

function addThumb() {
  const n = thumbs.value.length;
  // les portraits suivent d'une variante à l'autre ; le style, lui, est propre à chaque variante
  const portraits = [...(current.value?.portraits ?? [])];
  update({ thumbs: [...thumbs.value, { id: newId(), v: `v${n + 1}`, text: "", title: defaultTitle(n), portraits }], thumb_sel: n });
}

// --- A/B test : YouTube en compare 3 au plus ; elles prennent une lettre dans l'ordre des variantes ----
const MAX_AB = 3;
type Entry = { t: Thumb; i: number };
const entries = computed<Entry[]>(() => thumbs.value.map((t, i) => ({ t, i })));
const abList = computed(() => entries.value.filter((e) => e.t.pick));
const others = computed(() => entries.value.filter((e) => !e.t.pick));
const letter = (k: number) => String.fromCharCode(65 + k);

function togglePick(t: Thumb) {
  if (!t.pick && abList.value.length >= MAX_AB) {
    toast(tr("thumbnail.maxPicked", { n: MAX_AB }), true);
    return;
  }
  edit(t, { pick: !t.pick });
}

const tileProps = (e: Entry) => ({
  thumb: e.t, src: shownImage(e.t) ? fileUrl(shownImage(e.t)!) : null, editing: e.i === sel.value,
  busy: busy(e.t), titleChoices: titleChoices.value,
});

// --- images générées ------------------------------------------------------------------
const images = (t: Thumb | null): ThumbImage[] => (t?.id ? project.value.thumb_images?.[t.id] ?? [] : []);
/** L'image affichée : celle retenue, sinon la plus récente. */
const shownImage = (t: Thumb | null) => t?.image ?? images(t)[0]?.file ?? null;
const fileUrl = (file: string) => `/api/projects/${project.value.id}/files/vignettes/${encodeURIComponent(file)}`;

// --- compositions proposées par Claude (skill youtube-thumbnail) ---------------------
const ideaNote = ref("");
const ideasOpen = ref(false);
const ideas = computed(() => project.value.thumb_ideas ?? null);
const ideasJob = computed(() => project.value.runtime.jobs.thumb_ideas);
const ideasBusy = computed(() => running("thumb_ideas"));

function propose() {
  const t = current.value;
  if (t?.id && !ideasBusy.value) act(`/thumbs/${t.id}/ideas`, { note: ideaNote.value });
}

const fromIdea = (idea: ThumbIdea): Partial<Thumb> => ({ prompt: idea.scene, text: idea.text });

function useIdea(idea: ThumbIdea) {
  if (current.value) edit(current.value, fromIdea(idea));
  ideasOpen.value = false;
}

function ideaAsVariant(idea: ThumbIdea) {
  const n = thumbs.value.length;
  const t = current.value;
  update({
    thumbs: [...thumbs.value, { id: newId(), v: `v${n + 1}`, title: defaultTitle(n), ...fromIdea(idea),
                                portraits: [...(t?.portraits ?? [])], styles: [...(t?.styles ?? [])] } as Thumb],
    thumb_sel: n,
  });
  ideasOpen.value = false;
}

// --- génération -----------------------------------------------------------------------
const models = computed(() => project.value.runtime.thumbs.models);
const modelLabel = (id: string) => models.value.find((m) => m.id === id)?.label ?? id;
const chosen = ref<string[]>(JSON.parse(localStorage.getItem(MODELS_KEY) ?? '["nano-banana-pro", "seedream-5-pro"]'));
watch(chosen, (v) => localStorage.setItem(MODELS_KEY, JSON.stringify(v)));

function toggleModel(id: string) {
  chosen.value = chosen.value.includes(id) ? chosen.value.filter((m) => m !== id) : [...chosen.value, id];
}

const job = (t: Thumb, model: string) => `thumb:${t.id}:${model}`;
const busy = (t: Thumb | null) => !!t?.id && models.value.some((m) => running(job(t, m.id)));
/** L'état de chaque modèle lancé pour la variante (en cours, ou en erreur). */
const statuses = computed(() => {
  const t = current.value;
  if (!t?.id) return [];
  return models.value.flatMap((m) => {
    const j = project.value.runtime.jobs[job(t, m.id)];
    if (!j) return [];
    if (!j.finished) return [{ id: m.id, label: m.label, text: j.activity ?? tr("thumbnail.queued"), error: false }];
    const error = failed(job(t, m.id));
    return error ? [{ id: m.id, label: m.label, text: error, error: true }] : [];
  });
});

const refCount = (t: Thumb) => (t.portraits?.length ?? 0) + (t.styles?.length ?? 0);
const canGenerate = computed(() => {
  const t = current.value;
  return !!t && project.value.runtime.thumbs.ready && chosen.value.length > 0 && refCount(t) > 0
    && chosen.value.some((m) => !running(job(t, m)));
});

async function generate() {
  const t = current.value;
  if (!t?.id || !canGenerate.value) return;
  await act(`/thumbs/${t.id}/generate`, { models: chosen.value });
}

function removeImage(t: Thumb, file: string) {
  act(`/thumbs/${t.id}/images/${encodeURIComponent(file)}`, undefined, "DELETE");
}

// l'image de la galerie vue en grand ; ← → pour passer aux autres, Échap pour fermer
const zoom = ref<string | null>(null);
const zoomIndex = computed(() => images(current.value).findIndex((i) => i.file === zoom.value));
const zoomed = computed(() => images(current.value)[zoomIndex.value] ?? null);

/** Retire l'image vue en grand et passe à sa voisine. */
function removeZoomed() {
  const t = current.value, img = zoomed.value;
  if (!t || !img) return;
  const all = images(t);
  zoom.value = (all[zoomIndex.value + 1] ?? all[zoomIndex.value - 1])?.file ?? null;
  removeImage(t, img.file);
}

function step(delta: number) {
  const next = images(current.value)[zoomIndex.value + delta];
  if (next) zoom.value = next.file;
}

// --- retouche d'une image : elle repart vers un modèle avec une consigne, le reste ne bouge pas ---
const EDIT_MODELS_KEY = "studio.thumbEditModels";
const editChosen = ref<string[]>(JSON.parse(localStorage.getItem(EDIT_MODELS_KEY) ?? '["nano-banana-2"]'));
watch(editChosen, (v) => localStorage.setItem(EDIT_MODELS_KEY, JSON.stringify(v)));
const instruction = ref("");
// des images en plus pour cette retouche seulement (un logo à mettre, un objet à reprendre…)
const editRefs = ref<string[]>([]);
const pickingEditRefs = ref(false);

function toggleEditModel(id: string) {
  editChosen.value = editChosen.value.includes(id) ? editChosen.value.filter((m) => m !== id) : [...editChosen.value, id];
}

const canEdit = computed(() => {
  const t = current.value;
  return !!t && !!zoomed.value && project.value.runtime.thumbs.ready && !!instruction.value.trim()
    && editChosen.value.some((m) => !running(job(t, m)));
});

async function retouch() {
  const t = current.value, img = zoomed.value;
  if (!t?.id || !img || !canEdit.value) return;
  if (await act(`/thumbs/${t.id}/images/${encodeURIComponent(img.file)}/edit`,
                { instruction: instruction.value, models: editChosen.value, refs: editRefs.value })) {
    toast(tr("thumbnail.retouchStarted"));
    instruction.value = "";
    editRefs.value = [];
    zoom.value = null;
  }
}

function onKey(e: KeyboardEvent) {
  if (ideasOpen.value && e.key === "Escape") ideasOpen.value = false;
  if (!zoomed.value || pickingEditRefs.value) return;
  const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement;
  if (e.key === "Escape") zoom.value = null;
  else if (typing) return;
  else if (e.key === "ArrowLeft") step(-1);
  else if (e.key === "ArrowRight") step(1);
}
onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));

async function toLibrary(file: string) {
  try {
    await post(`/api/projects/${project.value.id}/resources/to-library`, { rel: `vignettes/${file}`, category: "vignettes" });
    toast(tr("thumbnail.addedToLibrary"));
  } catch (e) {
    toast((e as Error).message, true);
  }
}

// --- références -----------------------------------------------------------------------
const picking = ref<null | "portraits" | "styles">(null);
const PICKERS = {
  portraits: { category: "portraits", title: "thumbnail.myPortraits" },
  styles: { category: "vignettes", title: "thumbnail.styleRefs" },
} as const;
const pickerMax = computed(() => {
  const t = current.value;
  if (!t || !picking.value) return MAX_REFS;
  const other = picking.value === "portraits" ? t.styles?.length ?? 0 : t.portraits?.length ?? 0;
  return MAX_REFS - other;
});

function picked(rels: string[]) {
  if (current.value && picking.value) edit(current.value, { [picking.value]: rels });
  picking.value = null;
}

function unref(kind: "portraits" | "styles", rel: string) {
  const t = current.value;
  if (t) edit(t, { [kind]: (t[kind] ?? []).filter((r) => r !== rel) });
}

const feed = ref<"mobile" | "desktop">("mobile");
const feedOptions = computed(() => [["mobile", tr("thumbnail.mobile")], ["desktop", tr("thumbnail.desktop")]] as const);
const big = computed(() => feed.value === "desktop");
</script>

<template>
  <div class="wrap">
    <div class="angle">
      <span class="eyebrow">{{ tr("title.keptAngle") }}</span>
      <span class="angle-t">{{ angle?.t ?? tr("title.noAngle") }}</span>
      <button class="link-btn" @click="router.push(`/p/${project.id}/angle`)">{{ tr("common.change") }}</button>
    </div>

    <section class="group">
      <span class="eyebrow">{{ tr("thumbnail.keptForAb", { n: abList.length, max: MAX_AB }) }}</span>
      <div class="grid">
        <template v-for="k in MAX_AB" :key="k">
          <VariantTile
            v-if="abList[k - 1]" v-bind="tileProps(abList[k - 1])" :letter="letter(k - 1)"
            @select="update({ thumb_sel: abList[k - 1].i })" @title="edit(abList[k - 1].t, { title: $event })"
            @pick="togglePick(abList[k - 1].t)" />
          <div v-else class="slot">
            <span class="slot-letter mono">{{ letter(k - 1) }}</span>
            <span class="faint">{{ tr("thumbnail.slotEmpty") }}</span>
          </div>
        </template>
      </div>
    </section>

    <section class="group">
      <span v-if="others.length" class="eyebrow">{{ tr("thumbnail.otherVariants") }}</span>
      <div class="grid">
        <VariantTile
          v-for="e in others" :key="e.t.id ?? e.i" v-bind="tileProps(e)" :letter="null"
          @select="update({ thumb_sel: e.i })" @title="edit(e.t, { title: $event })" @pick="togglePick(e.t)" />
        <button class="add" @click="addThumb">{{ tr("thumbnail.newVariant") }}</button>
      </div>
    </section>

    <section v-if="current" class="editor">
      <span class="eyebrow">{{ tr("thumbnail.variant", { v: current.v }) }}</span>

      <div class="cols">
        <div class="col brief">
          <span class="col-title">{{ tr("thumbnail.brief") }}</span>
          <label class="label">{{ tr("thumbnail.promptLabel") }}</label>
          <textarea
            class="textarea soft" rows="4" :value="current.prompt ?? ''"
            :placeholder="tr('thumbnail.promptPlaceholder')"
            @input="edit(current, { prompt: ($event.target as HTMLTextAreaElement).value }, 500)" />
          <label class="label">{{ tr("thumbnail.textLabel") }}</label>
          <input
            class="input soft text-in" :value="current.text"
            :placeholder="tr('thumbnail.textPlaceholder')"
            @input="edit(current, { text: ($event.target as HTMLInputElement).value }, 500)">
          <span class="faint small">{{ tr("thumbnail.textHint", { title: titleOf(current) }) }}</span>

          <div v-for="kind in (['portraits', 'styles'] as const)" :key="kind" class="refs">
            <div class="refs-head">
              <label class="label">{{ kind === "portraits" ? tr("thumbnail.myPortraits") : tr("thumbnail.styleLabel") }}</label>
              <button class="link-btn" @click="picking = kind">{{ tr("thumbnail.pickFromLibrary") }}</button>
            </div>
            <div class="chips">
              <div v-for="rel in current[kind] ?? []" :key="rel" class="chip">
                <img :src="refUrl(project.id, rel)" alt="" :title="rel.split('/').pop()">
                <button class="x-btn" :title="tr('common.remove')" @click="unref(kind, rel)">×</button>
              </div>
              <span v-if="!(current[kind] ?? []).length" class="faint none">
                {{ kind === "portraits" ? tr("thumbnail.noPortrait") : tr("thumbnail.noStyle") }}
              </span>
            </div>
          </div>
          <span v-if="!refCount(current)" class="hint">{{ tr("thumbnail.needRef") }}</span>

          <button class="link-btn ideas-link" @click="ideasOpen = true">
            {{ ideasBusy ? tr("thumbnail.ideas.composingIdeas") : ideas?.items.length
              ? tr("thumbnail.ideas.see", { n: ideas.items.length })
              : tr("thumbnail.ideas.ask") }}
          </button>

          <div class="run">
            <div class="models">
              <button v-for="m in models" :key="m.id" class="model" :class="{ on: chosen.includes(m.id) }" @click="toggleModel(m.id)">
                {{ m.label }}
              </button>
            </div>
            <span class="spacer" />
            <button class="btn dark md" :disabled="!canGenerate" @click="generate">
              {{ busy(current) ? tr("thumbnail.generating") : tr("thumbnail.generate") }}
            </button>
          </div>
          <span v-if="!project.runtime.thumbs.ready" class="hint">
            <i18n-t keypath="thumbnail.falMissing" scope="global">
              <template #cmd><span class="mono">{{ tr("thumbnail.falCmd") }}</span></template>
            </i18n-t>
          </span>
          <span v-else-if="!chosen.length" class="hint">{{ tr("thumbnail.pickModel") }}</span>
        </div>

        <div class="col results">
          <span class="col-title">{{ tr("thumbnail.results") }}<span v-if="images(current).length" class="faint"> · {{ images(current).length }}</span></span>
          <div v-if="!images(current).length && !statuses.length" class="empty hatch">
            <span class="faint">{{ tr("thumbnail.resultsEmpty", { v: current.v }) }}</span>
          </div>
          <div v-else class="gallery">
            <!-- les modèles en cours (ou en échec) prennent la place de l'image à venir -->
            <div v-for="s in statuses" :key="s.id" class="shot ghost" :class="s.error ? 'failed' : 'hatch'">
              <span class="ghost-model">{{ s.label }}</span>
              <span class="ghost-text" :class="{ mono: !s.error }" :title="s.text">{{ s.text }}</span>
            </div>
            <div v-for="img in images(current)" :key="img.file" class="shot" :class="{ on: shownImage(current) === img.file }">
              <img :src="fileUrl(img.file)" alt="" :title="tr('thumbnail.zoom')" @click="zoom = img.file">
              <span class="shot-model mono" :title="img.edit ? tr('thumbnail.retouchOf', { edit: img.edit }) : undefined">
                {{ modelLabel(img.model) }}{{ img.edit ? tr("thumbnail.retouchSuffix") : "" }}
              </span>
              <span v-if="shownImage(current) === img.file" class="shot-kept">{{ tr("thumbnail.chosen") }}</span>
              <button v-else class="shot-pick" :title="tr('thumbnail.chooseTitle')" @click="edit(current, { image: img.file })">{{ tr("thumbnail.choose") }}</button>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="preview">
      <div class="preview-head">
        <span class="eyebrow">{{ tr("thumbnail.preview") }}</span>
        <Seg v-model="feed" :options="feedOptions" />
      </div>
      <div class="feed" :class="{ big }">
        <div class="item">
          <div class="frame" :class="{ hatch: !shownImage(current) }">
            <img v-if="shownImage(current)" :src="fileUrl(shownImage(current)!)" alt="">
          </div>
          <span class="v-title">{{ titleOf(current) }}</span>
          <span class="channel">{{ tr("thumbnail.yourChannel") }}</span>
        </div>
        <div v-for="k in 3" :key="k" class="item other">
          <div class="frame" />
          <div class="line" style="width: 90%" />
          <div class="line" style="width: 60%" />
        </div>
      </div>
    </section>

    <LibraryPicker
      v-if="picking && current" :pid="project.id" :category="PICKERS[picking].category" :title="tr(PICKERS[picking].title)"
      :selected="current[picking] ?? []" :max="pickerMax" @done="picked" @cancel="picking = null" />

    <template v-if="ideasOpen && current">
      <div class="backdrop" @click="ideasOpen = false" />
      <div class="modal ideas">
        <div class="modal-head">
          <span class="eyebrow">{{ tr("thumbnail.ideas.title") }}</span>
          <span class="spacer" />
          <button class="btn md" @click="ideasOpen = false">{{ tr("common.close") }}</button>
        </div>
        <div class="ideas-run">
          <input
            v-model="ideaNote" class="input soft" :disabled="ideasBusy"
            :placeholder="tr('thumbnail.ideas.placeholder')"
            @keydown.enter="propose">
          <button class="btn dark md" :disabled="ideasBusy" @click="propose">
            {{ ideasBusy ? tr("thumbnail.ideas.composing") : ideas?.items.length ? tr("thumbnail.ideas.more") : tr("thumbnail.ideas.propose") }}
          </button>
          <button v-if="ideasBusy" class="link-btn" @click="act('/jobs/thumb_ideas/stop')">{{ tr("thumbnail.ideas.stop") }}</button>
        </div>
        <span v-if="ideasBusy" class="mono faint small">{{ ideasJob?.activity ?? tr("thumbnail.queued") }}</span>
        <span v-else-if="failed('thumb_ideas')" class="error">{{ failed("thumb_ideas") }}</span>
        <template v-if="ideas?.items.length">
          <p v-if="ideas.message" class="advice">{{ ideas.message }}</p>
          <div class="idea-grid">
            <div v-for="(idea, k) in ideas.items" :key="k" class="idea">
              <div class="idea-head">
                <span class="idea-name">{{ idea.name }}</span>
                <span v-if="idea.text" class="idea-text">{{ idea.text }}</span>
                <span v-else class="faint small">{{ tr("thumbnail.ideas.noText") }}</span>
              </div>
              <p class="idea-scene">{{ idea.scene }}</p>
              <p class="faint small">{{ idea.colors }}</p>
              <p class="idea-hook">{{ idea.hook }}</p>
              <div class="idea-foot">
                <button class="link-btn" @click="useIdea(idea)">{{ tr("thumbnail.ideas.useFor", { v: current.v }) }}</button>
                <button class="link-btn" @click="ideaAsVariant(idea)">{{ tr("thumbnail.ideas.asVariant") }}</button>
              </div>
            </div>
          </div>
        </template>
      </div>
    </template>

    <template v-if="zoomed && current">
      <div class="backdrop" @click="zoom = null" />
      <div class="lightbox">
        <img :src="fileUrl(zoomed.file)" alt="">
        <div class="lightbox-foot">
          <button class="link-btn" :disabled="zoomIndex <= 0" @click="step(-1)">←</button>
          <span class="mono faint">{{ zoomIndex + 1 }} / {{ images(current).length }} · {{ modelLabel(zoomed.model) }}</span>
          <button class="link-btn" :disabled="zoomIndex >= images(current).length - 1" @click="step(1)">→</button>
          <span class="spacer" />
          <button class="link-btn small" :title="tr('thumbnail.toLibraryTitle')" @click="toLibrary(zoomed.file)">{{ tr("thumbnail.toLibrary") }}</button>
          <ConfirmX :label="tr('thumbnail.removeConfirm')" :title="tr('thumbnail.removeTitle')" @confirm="removeZoomed" />
          <span v-if="shownImage(current) === zoomed.file" class="kept">{{ tr("thumbnail.chosen") }}</span>
          <button v-else class="btn dark md" @click="edit(current, { image: zoomed.file })">{{ tr("thumbnail.chooseThis") }}</button>
          <button class="btn md" @click="zoom = null">{{ tr("common.close") }}</button>
        </div>
        <p v-if="zoomed.edit" class="faint small origin">{{ tr("thumbnail.retouchQuoted", { edit: zoomed.edit }) }}</p>
        <div class="retouch">
          <textarea
            v-model="instruction" class="textarea soft" rows="2"
            :placeholder="tr('thumbnail.retouchPlaceholder')"
            @keydown.ctrl.enter="retouch" />
          <div class="refs">
            <div class="refs-head">
              <label class="label">{{ tr("thumbnail.retouchRefs") }}</label>
              <button class="link-btn" @click="pickingEditRefs = true">{{ tr("thumbnail.pickFromLibrary") }}</button>
            </div>
            <div class="chips">
              <div v-for="rel in editRefs" :key="rel" class="chip">
                <img :src="refUrl(project.id, rel)" alt="" :title="rel.split('/').pop()">
                <button class="x-btn" :title="tr('common.remove')" @click="editRefs = editRefs.filter((r) => r !== rel)">×</button>
              </div>
              <span v-if="!editRefs.length" class="faint none">{{ tr("thumbnail.retouchRefsNone") }}</span>
            </div>
          </div>
          <div class="retouch-run">
            <button
              v-for="m in models" :key="m.id" class="model" :class="{ on: editChosen.includes(m.id) }"
              @click="toggleEditModel(m.id)">
              {{ m.label }}
            </button>
            <span class="spacer" />
            <button class="btn dark md" :disabled="!canEdit" @click="retouch">{{ tr("thumbnail.retouch") }}</button>
          </div>
        </div>
      </div>
    </template>

    <!-- après la visionneuse, pour passer par-dessus -->
    <LibraryPicker
      v-if="pickingEditRefs" :pid="project.id" category="images" :title="tr('thumbnail.retouchRefs')"
      :selected="editRefs" :max="MAX_REFS - 1" @done="editRefs = $event; pickingEditRefs = false" @cancel="pickingEditRefs = false" />
  </div>
</template>

<style scoped>
.wrap { padding: 24px 32px 40px; display: flex; flex-direction: column; gap: 28px; }

.angle { display: flex; align-items: center; gap: 12px; font-size: 14px; }
.angle-t { font-weight: 600; }

.group { display: flex; flex-direction: column; gap: 12px; }
.group + .group { margin-top: -12px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; }
.frame img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.slot {
  aspect-ratio: 16 / 9; border: 1px dashed var(--dash); border-radius: 4px; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 6px; font-size: 13px;
}
.slot-letter { font-size: 18px; font-weight: 700; color: var(--dash); }
.add {
  aspect-ratio: 16 / 9; border: 1px dashed var(--dash); border-radius: 4px; background: #fff;
  font-size: 13.5px; color: var(--muted); cursor: pointer;
}
.add:hover { border-color: var(--ink); color: var(--ink); }

.editor { display: flex; flex-direction: column; gap: 16px; padding: 20px; border: 1px solid var(--line); border-radius: 4px; }
.modal {
  position: fixed; z-index: 41; top: 50%; left: 50%; transform: translate(-50%, -50%); width: min(1100px, 92vw);
  max-height: 88vh; overflow-y: auto; background: #fff; border-radius: 6px; box-shadow: 0 16px 48px rgba(0, 0, 0, .3);
  padding: 18px 20px; display: flex; flex-direction: column; gap: 12px;
}
.modal-head { display: flex; align-items: center; }
.ideas-run { display: flex; gap: 10px; align-items: center; }
.ideas-run .input { flex: 1; height: 34px; padding: 0 10px; font-size: 13px; border-radius: 3px; }
.small { font-size: 12px; }
.advice { margin: 0; font-size: 13px; color: var(--muted); }
.idea-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.idea { display: flex; flex-direction: column; gap: 6px; padding: 12px 14px; border: 1px solid var(--line); border-radius: 4px; }
.idea p { margin: 0; }
.idea-head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.idea-name { font-size: 13.5px; font-weight: 600; }
.idea-text { font-size: 11.5px; font-weight: 700; background: var(--ink); color: #fff; padding: 2px 6px; }
.idea-scene { font-size: 13px; line-height: 1.45; }
.idea-hook { font-size: 12.5px; font-style: italic; color: var(--muted); }
.idea-foot { display: flex; gap: 14px; margin-top: auto; padding-top: 4px; }
.idea-foot .link-btn { font-size: 12.5px; }
.cols { display: grid; grid-template-columns: minmax(340px, 2fr) minmax(0, 3fr); gap: 28px; align-items: start; }
@media (max-width: 1100px) { .cols { grid-template-columns: minmax(0, 1fr); } }
.col { display: flex; flex-direction: column; gap: 10px; }
.brief { padding-right: 28px; border-right: 1px solid var(--line-soft); }
@media (max-width: 1100px) { .brief { padding-right: 0; border-right: 0; } }
.col-title { font-size: 11px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.ideas-link { align-self: flex-start; font-size: 12.5px; margin-top: 4px; }
.brief .run { padding-top: 14px; margin-top: 4px; border-top: 1px solid var(--line-soft); }
.empty { aspect-ratio: 16 / 9; max-width: 480px; display: grid; place-items: center; border-radius: 4px; font-size: 13px; }
.label { font-size: 13px; font-weight: 600; }
.text-in { height: 34px; padding: 0 10px; font-size: 13px; border-radius: 3px; }
.refs { display: flex; flex-direction: column; gap: 8px; }
.refs + .refs { margin-top: 6px; }
.refs-head { display: flex; justify-content: space-between; align-items: baseline; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; min-height: 56px; align-items: center; }
.chip { position: relative; width: 56px; height: 56px; border-radius: 4px; overflow: hidden; background: var(--bg-soft); }
.chip img { width: 100%; height: 100%; object-fit: cover; display: block; }
.chip .x-btn {
  position: absolute; top: 2px; right: 2px; width: 18px; height: 18px; border-radius: 9px;
  background: rgba(255, 255, 255, .9); font-size: 13px; padding: 0;
}
.none { font-size: 13px; }

.run { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.models { display: flex; gap: 6px; flex-wrap: wrap; }
.model {
  height: 30px; padding: 0 11px; border: 1px solid var(--line-strong); border-radius: 15px; background: #fff;
  font-size: 12.5px; color: var(--muted); cursor: pointer;
}
.model.on { border-color: var(--ink); background: var(--ink); color: #fff; }
.hint { font-size: 12.5px; color: var(--red-dark); }
.error { font-size: 12.5px; color: var(--red-dark); }

.gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; }
.shot { position: relative; aspect-ratio: 16 / 9; border-radius: 4px; overflow: hidden; }
.shot img { width: 100%; height: 100%; object-fit: cover; cursor: zoom-in; display: block; }
.shot.on { outline: 2px solid var(--red); outline-offset: 2px; }
.shot-model, .shot-kept, .shot-pick {
  position: absolute; bottom: 6px; font-size: 11px; padding: 3px 7px; border-radius: 3px; border: none;
}
.shot-model { left: 6px; background: rgba(24, 25, 27, .7); color: #fff; pointer-events: none; }
.shot-kept { right: 6px; background: var(--red); color: #fff; font-weight: 600; }
.shot-pick { right: 6px; background: #fff; color: var(--ink); cursor: pointer; opacity: 0; transition: opacity .12s; }
.shot:hover .shot-pick { opacity: 1; }
.ghost { display: flex; flex-direction: column; justify-content: center; gap: 4px; padding: 12px 14px; }
.ghost-model { font-size: 12.5px; font-weight: 600; }
.ghost-text { font-size: 12px; color: var(--muted); overflow: hidden; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }
.ghost.failed { border: 1px solid var(--red); background: #fff; }
.ghost.failed .ghost-text { color: var(--red-dark); }
.kept { font-size: 12px; font-weight: 600; color: var(--red); }

.backdrop { position: fixed; inset: 0; z-index: 40; background: rgba(24, 25, 27, .7); }
.lightbox {
  position: fixed; z-index: 41; top: 50%; left: 50%; transform: translate(-50%, -50%); width: min(1400px, 92vw);
  background: #fff; border-radius: 6px; box-shadow: 0 16px 48px rgba(0, 0, 0, .3); padding: 14px;
  display: flex; flex-direction: column; gap: 12px;
}
.lightbox img { width: 100%; max-height: calc(92vh - 220px); object-fit: contain; display: block; border-radius: 4px; }
.lightbox-foot { display: flex; align-items: center; gap: 12px; font-size: 12.5px; }
.lightbox-foot .link-btn { font-size: 16px; }
.origin { margin: 0; }
.retouch { display: flex; flex-direction: column; gap: 8px; }
.retouch .textarea { font-size: 13px; }
.retouch-run { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }

.preview { display: flex; flex-direction: column; gap: 14px; }
.preview-head { display: flex; justify-content: space-between; align-items: center; }
.feed { display: flex; gap: 16px; padding: 20px; background: var(--bg-soft); border-radius: 4px; flex-wrap: wrap; }
.item { width: 200px; display: flex; flex-direction: column; gap: 8px; }
.feed.big .item { width: 300px; }
.frame { position: relative; aspect-ratio: 16 / 9; overflow: hidden; }
.v-title { font-size: 13px; font-weight: 600; line-height: 1.35; }
.channel { font-size: 12px; color: var(--faint); }
.other .frame { background: var(--line); }
.other .line { height: 10px; background: var(--hatch-a); }
.other .line:last-child { background: #E9E9E6; }
</style>
