<script setup lang="ts">
/**
 * Étape Script : le texte mis en page avec ses plans ; à droite le sommaire, les médias à glisser sur le texte, le plan choisi et l'assistant ; les sources ; les notes.
 */
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import { usePref } from "../../lib/composables";
import { contentText, loadChannelLanguage } from "../../lib/content";
import { mmss } from "../../lib/format";
import { toast } from "../../lib/toast";
import { act, failed, refresh, running, store, update } from "../store";
import { type SaveState, useDoc } from "./script/doc";
import type { Plan, ProposedPlan } from "../types";
import { colorOf, findPassage, newPlan, orderPlans, sectionsOf, timing as timingOf, typeLabel } from "./script/plans";
import { letterOf, newSetup, setupColor, setupOfOrdered } from "./script/setups";
import { toMarkdown, useScript, type Block } from "./script/useScript";
import ConfirmX from "../../components/ConfirmX.vue";
import MediaPanel from "./script/MediaPanel.vue";
import PlanPanel from "./script/PlanPanel.vue";
import ScriptAssistant from "./script/ScriptAssistant.vue";
import ScriptEditor from "./script/ScriptEditor.vue";

const { t } = useI18n();
const project = computed(() => store.project!);
const route = useRoute();
const tab = ref<"script" | "recherche" | "notes">("script");
// la colonne de droite : sommaire, médias à glisser sur le texte, plan choisi, assistant
const side = usePref<"sommaire" | "medias" | "plan" | "assistant">("script.side", "sommaire");

// le serveur recompte les mots du script (barre du haut) à chaque enregistrement
const script = useScript(() => refresh().catch(() => {}));
const notes = useDoc("notes.md");

const blocks = computed(() => script.blocks.value ?? []);
const md = computed(() => toMarkdown(blocks.value));
const writing = computed(() => running("script"));
const writeError = computed(() => failed("script"));
/** « Je l'écris moi-même » : l'éditeur s'ouvre sur une page blanche, sans passer par Daryl. */
const selfWrite = ref(false);
const empty = computed(() => script.blocks.value !== null && !md.value.trim() && !project.value.runtime.has_script
  && !selfWrite.value);
const angle = computed(() => {
  const p = project.value;
  return p.angle_sel != null ? p.angles[p.angle_sel] ?? null : null;
});

// Claude a fini d'écrire : on relit le script (le serveur recale les blocs sur script.md)
watch(writing, (now, before) => {
  if (before && !now) script.load();
});

// --- texte -----------------------------------------------------------------------------

const editor = ref<InstanceType<typeof ScriptEditor>>();
const cursor = ref<string | null>(null);
const quote = ref<string | null>(null);

const timing = computed(() => timingOf(blocks.value));
const secs = computed(() => sectionsOf(blocks.value));

/** La durée estimée de chaque section : jusqu'au début de la suivante (ou la fin du script). */
const secDur = computed(() => {
  const { times, words } = timing.value;
  const end = (words / 150) * 60;
  return Object.fromEntries(secs.value.map((s, i) => {
    const next = secs.value[i + 1];
    return [s.id, (next ? times[next.id] : end) - times[s.id]];
  }));
});

/** Une durée écrite comme telle (« 3 min 25 », « 45 s ») pour ne pas la confondre avec un repère. */
function duration(secs: number): string {
  const t = Math.round(secs), m = Math.floor(t / 60), s = t % 60;
  return m ? `${m} min${s ? ` ${String(s).padStart(2, "0")}` : ""}` : `${s} s`;
}

/** La section où se trouve le curseur. */
const secSel = computed(() => {
  const at = blocks.value.findIndex((b) => b.id === cursor.value);
  return at < 0 ? null : secs.value.filter((s) => s.index <= at).at(-1)?.id ?? null;
});

function onChange(value: Block[]): void {
  script.set(value);
}

// --- plans -----------------------------------------------------------------------------

const plans = computed(() => script.plans.value);
const ordered = computed(() => orderPlans(blocks.value, plans.value));
const num = computed(() => Object.fromEntries(ordered.value.map((o) => [o.plan.id, o.num])));
const byId = computed(() => Object.fromEntries(ordered.value.map((o) => [o.plan.id, o])));
/** Combien de plans utilisent chaque fichier (affiché dans le panneau Médias). */
const used = computed(() => {
  const out: Record<string, number> = {};
  for (const p of plans.value) for (const m of p.media) out[m.url] = (out[m.url] ?? 0) + 1;
  return out;
});

/** Le plan ouvert dans l'onglet Plan (et mis en avant dans le texte). */
const active = ref<string | null>(null);

function select(id: string | null, open = true): void {
  active.value = id;
  if (id && open) side.value = "plan";
}

function addPlan(plan: Plan): void {
  script.setPlans([...plans.value, plan]);
  select(plan.id);
}

function updatePlan(id: string, changes: Partial<Plan>, delay = 0): void {
  script.updatePlan(id, changes, delay);
}

function removePlan(id: string): void {
  script.removePlan(id);
  if (active.value === id) active.value = null;
}

/** Le texte a bougé : les passages des plans suivent (enregistrés avec un peu de retard). */
function onAnchors(changes: { id: string; changes: Partial<Plan> }[]): void {
  const by = new Map(changes.map((c) => [c.id, c.changes]));
  script.setPlans(plans.value.map((p) => (by.has(p.id) ? { ...p, ...by.get(p.id) } : p)), 800);
}

function locateProposal(p: ProposedPlan): { block: string; q: string } | null {
  const at = findPassage(blocks.value, p.passage);
  if (!at) toast(t("script.toasts.passageNotFound"), true);
  return at;
}

/** Un plan proposé par l'assistant, posé sur le passage qu'il illustre. */
function acceptProposal(p: ProposedPlan): boolean {
  const at = locateProposal(p);
  if (!at) return false;
  script.setPlans([...plans.value, newPlan(at.block, { id: p.id, type: p.type, note: p.note, media: p.media, q: at.q })]);
  return true;
}

/** Amène à l'écran le passage d'un plan proposé, surligné un moment (le plan lui-même s'il est accepté). */
function showProposal(p: ProposedPlan): void {
  if (byId.value[p.id]) {
    select(p.id, false);
    editor.value?.showPlan(p.id);
    return;
  }
  const at = locateProposal(p);
  if (at) editor.value?.preview(at.block, at.q, colorOf(p.type));
}

function reanchor(id: string): void {
  if (!editor.value?.reanchor(id)) toast(t("script.toasts.selectFirst"));
}

// /p/…/script?b=<bloc> (depuis Tournage) : on se place sur ce bloc
watch(() => [script.version.value, route.query.b] as const, async ([, b]) => {
  if (typeof b !== "string") return;
  await nextTick();
  editor.value?.goTo(b);
});

// le titre ajouté est dans la langue de la chaîne, comme le reste du script
loadChannelLanguage();

function addSection(): void {
  const label = contentText("part");
  const n = secs.value.filter((s) => s.label.startsWith(label)).length + 1;
  editor.value?.append(`## ${label} ${n} — ${contentText("newPart")}`);
}

/** Claude relit le script : ce qui est en cours de frappe doit être enregistré avant. */
async function beforeSend(): Promise<void> {
  editor.value?.flush();
  await script.save();
}

async function copy(text: string, message: string): Promise<void> {
  await navigator.clipboard.writeText(text);
  toast(message);
}

function download(): void {
  const name = project.value.title.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/\W+/g, "-")
    .replace(/^-|-$/g, "").toLowerCase() || "script";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([md.value], { type: "text/markdown;charset=utf-8" }));
  a.download = `${name}.md`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function replacePassage(passage: string, text: string): void {
  if (writing.value) {
    toast(t("script.toasts.darylWriting"), true);
    return;
  }
  if (!editor.value?.replace(passage, text)) {
    toast(t("script.toasts.passageGone"));
    return;
  }
  script.save();
  toast(t("script.toasts.replaced"));
}

// --- versions (V1, V2…) ----------------------------------------------------------------

const drafts = computed(() => script.drafts.value);
const draft = computed(() => drafts.value.find((d) => d.active) ?? null);

/** Avant de changer de version, ce qui est en cours de frappe rejoint la version actuelle. */
function switchDraft(id: string): void {
  editor.value?.flush();
  active.value = null;
  script.activateDraft(id);
}

function forkDraft(): void {
  editor.value?.flush();
  script.forkDraft();
}

function renameDraft(): void {
  if (!draft.value) return;
  const name = prompt(t("script.drafts.renamePrompt"), draft.value.name)?.trim();
  if (name && name !== draft.value.name) script.renameDraft(draft.value.id, name);
}

function deleteDraft(): void {
  if (!draft.value) return;
  active.value = null;
  script.deleteDraft(draft.value.id);
}

function writeScript(): void {
  act("/script/write");
}

function rewrite(): void {
  if (confirm(t("script.rewriteConfirm"))) writeScript();
}

const stats = computed(() => [
  [t("script.stats.words"), String(timing.value.words)],
  [t("script.stats.duration"), mmss((timing.value.words / 150) * 60)],
  [t("script.stats.sections"), String(secs.value.length)],
]);

const saveLabel = (s: SaveState) => t(`script.save.${s}`);

// --- setups de tournage ----------------------------------------------------------------------

const setups = computed(() => script.setups.value);
const sections = computed(() => script.sections.value);
const setupAt = computed(() => new Map(setups.value.map((s, i) => [s.id, i])));

/** Lettre et couleur d'un setup ; null : aucun (ou disparu). */
function setupLook(id: string): { letter: string; color: string; name: string } | null {
  const at = setupAt.value.get(id);
  return at == null ? null : { letter: letterOf(at), color: setupColor(at), name: setups.value[at].name };
}

/** Pour la marge de l'éditeur : le setup de chaque section, et ceux qu'on peut choisir. */
const sectionLooks = computed(() => Object.fromEntries(secs.value.map((s) => [s.id, setupLook(sections.value[s.id] ?? "")])));
const setupOptions = computed(() => setups.value.map((s) => ({ id: s.id, ...setupLook(s.id)! })));

/** Un nouveau setup, ajouté à la fin de la liste ; renvoie son id. */
function addSetup(): string {
  const setup = newSetup();
  script.setSetups([...setups.value, setup]);
  return setup.id;
}

/** Le setup d'une section, choisi dans la marge ("" : aucun, "new" : un nouveau). */
function setSectionSetup(section: string, id: string): void {
  if (id === "new") id = addSetup();
  const out = { ...sections.value };
  if (id) out[section] = id;
  else delete out[section];
  script.setSetups(setups.value, out);
}

/** Un nouveau setup créé depuis le panneau d'un plan, qui s'y tourne. */
function newSetupFor(plan: string): void {
  updatePlan(plan, { setup: addSetup() });
}

// --- recherche -------------------------------------------------------------------------

const srcInput = ref("");

function addSource(): void {
  const v = srcInput.value.trim();
  if (!v) return;
  const isUrl = /^https?:\/\//.test(v);
  const t = isUrl ? v.replace(/^https?:\/\/(www\.)?/, "").split("/")[0] : v;
  update({ research: [{ t, u: isUrl ? v : "", n: "" }, ...project.value.research] });
  srcInput.value = "";
}

function removeSource(i: number): void {
  update({ research: project.value.research.filter((_, j) => j !== i) });
}

function setNote(i: number, n: string): void {
  update({ research: project.value.research.map((s, j) => (j === i ? { ...s, n } : s)) }, 500);
}
</script>

<template>
  <div class="root">
    <div class="tabs page-tabs">
      <button :class="{ on: tab === 'script' }" @click="tab = 'script'">{{ t("script.tabs.script") }}</button>
      <button :class="{ on: tab === 'recherche' }" @click="tab = 'recherche'">
        {{ t("script.tabs.research") }}<span class="n">{{ project.research.length }}</span>
      </button>
      <button :class="{ on: tab === 'notes' }" @click="tab = 'notes'">{{ t("script.tabs.notes") }}</button>
    </div>

    <!-- Script -->
    <template v-if="tab === 'script'">
      <div v-if="empty && !writing" class="empty-state">
        <div class="dashed-box">
          <p>{{ t("script.empty.intro") }}</p>
          <p v-if="angle" class="angle">{{ t("chat.quoted", { q: angle.t }) }}</p>
          <p v-else>{{ t("script.empty.pickAngle") }}</p>
          <div class="actions">
            <button class="btn lg" @click="selfWrite = true">{{ t("script.empty.self") }}</button>
            <button class="btn dark lg" :disabled="!angle" @click="writeScript">{{ t("script.empty.write") }}</button>
          </div>
          <p v-if="writeError" class="error">{{ writeError }}</p>
        </div>
      </div>

      <div v-else class="script-layout">

        <div class="center">
          <div class="toolbar">
            <span v-if="writing" class="mono writing">
              {{ t("script.writing") }}<template v-if="project.runtime.jobs.script?.activity"> · {{ project.runtime.jobs.script.activity }}</template>
            </span>
            <span v-else class="eyebrow hint">{{ t("script.hint") }}</span>
            <div v-if="draft" class="drafts">
              <select class="select" :value="draft.id" :disabled="writing" :title="t('script.drafts.switchTitle')"
                @change="switchDraft(($event.target as HTMLSelectElement).value)">
                <option v-for="d in drafts" :key="d.id" :value="d.id">
                  {{ t("script.drafts.option", { name: d.name, words: d.words }) }}</option>
              </select>
              <button class="btn sm" :disabled="writing" :title="t('script.drafts.forkTitle')" @click="forkDraft">
                {{ t("script.drafts.fork") }}</button>
              <button class="btn sm" :title="t('script.drafts.renameTitle')" @click="renameDraft">{{ t("script.drafts.rename") }}</button>
              <ConfirmX v-if="drafts.length > 1 && !writing" :title="t('script.drafts.deleteTitle')" @confirm="deleteDraft" />
            </div>
            <button class="btn sm" @click="editor?.selectAll()">{{ t("script.selectAll") }}</button>
            <button class="btn sm" @click="copy(md, t('script.scriptCopied'))">{{ t("script.copyMarkdown") }}</button>
            <button class="btn sm" @click="download">{{ t("script.exportMd") }}</button>
          </div>
          <p v-if="writeError && !writing" class="error">{{ writeError }}</p>
          <div class="sheet-scroll">
            <div class="sheet">
              <ScriptEditor
                v-if="script.blocks.value" ref="editor" :blocks="blocks" :version="script.version.value"
                :readonly="writing" :times="timing.times" :plans="plans" :active="active" :setups="sectionLooks" :setup-options="setupOptions"
                :plain="side !== 'plan'"
                @setup="setSectionSetup" @change="onChange" @quote="quote = $event" @cursor="cursor = $event"
                @add-plan="addPlan" @update="updatePlan" @anchors="onAnchors" @select="select"
              >
                <template #plans="{ ids }">
                  <button v-for="id in ids" :key="id" class="plan-sum" :class="{ active: id === active, on: byId[id]?.plan.on }"
                    @click="select(id)">
                    <span class="swatch" :style="{ background: colorOf(byId[id]?.plan.type ?? '') }" />
                    <span class="mono n">{{ byId[id]?.num }}</span>
                    <span class="t">{{ typeLabel(byId[id]?.plan.type ?? "") }}</span>
                    <span v-if="byId[id] && setupLook(setupOfOrdered(byId[id], sections))" class="setup-tag mono"
                      :style="{ color: setupLook(setupOfOrdered(byId[id], sections))!.color }">
                      {{ setupLook(setupOfOrdered(byId[id], sections))!.letter }}</span>
                    <span v-if="byId[id]?.plan.note" class="note">· {{ byId[id]?.plan.note }}</span>
                    <span v-for="m in byId[id]?.plan.media ?? []" :key="m.url" class="file mono">@{{ m.name }}</span>
                  </button>
                </template>
              </ScriptEditor>
            </div>
          </div>
        </div>

        <div class="side">
          <div class="side-tabs">
            <button :class="{ on: side === 'sommaire' }" @click="side = 'sommaire'">{{ t("script.side.toc") }}</button>
            <button :class="{ on: side === 'medias' }" @click="side = 'medias'">{{ t("script.side.media") }}</button>
            <button :class="{ on: side === 'plan' }" @click="side = 'plan'">
              {{ t("script.side.plans") }}<span v-if="plans.length" class="n mono">{{ plans.length }}</span>
            </button>
            <button :class="{ on: side === 'assistant' }" @click="side = 'assistant'">
              {{ t("common.assistant") }}<span v-if="quote && side !== 'assistant'" class="dot" :title="t('script.side.quoteSelected')" />
            </button>
          </div>
          <ScriptAssistant v-show="side === 'assistant'" :quote="quote" :before-send="beforeSend"
            :plans="plans" :accept="acceptProposal" @show="showProposal" @clear-quote="quote = null" @replace="replacePassage" />
          <PlanPanel v-if="side === 'plan'" :ordered="ordered" :active="active" :used="used" :setups="setups" :sections="sections" @new-setup="newSetupFor"
            @select="select($event, false)" @update="updatePlan" @remove="removePlan" @reanchor="reanchor"
            @show="editor?.showPlan($event)" />
          <nav v-else-if="side !== 'assistant'" class="toc">
            <template v-if="side === 'sommaire'">
              <button v-for="(s, i) in secs" :key="s.id" class="sec" :class="{ on: s.id === secSel }" @click="editor?.goTo(s.id)">
                <span class="label">
                  <span>
                    <span v-if="setupLook(sections[s.id] ?? '')" class="sec-setup" :style="{ background: setupLook(sections[s.id] ?? '')!.color }">
                      {{ setupLook(sections[s.id] ?? '')!.letter }}</span>{{ s.title ? s.label : t("script.sectionN", { n: i + 1 }) }}
                  </span><span :title="t('script.sectionTimeTitle')">{{ mmss(timing.times[s.id]) }} · <span class="dur">{{ duration(secDur[s.id]) }}</span></span>
                </span>
                <span class="title">{{ s.title || s.label }}</span>
              </button>
              <button class="btn dashed add" :disabled="writing" @click="addSection">{{ t("script.addSection") }}</button>
              <div class="stats">
                <div v-for="[k, v] in stats" :key="k" class="stat"><span>{{ k }}</span><span class="mono">{{ v }}</span></div>
              </div>
              <div class="angle-box">
                <span class="k">{{ t("script.chosenAngle") }}</span>
                <span class="v">{{ angle?.t ?? "—" }}</span>
              </div>
              <span class="saved mono">{{ saveLabel(script.state.value) }}</span>
              <button v-if="md.trim() && !writing" class="link-btn rewrite" @click="rewrite">{{ t("script.rewriteLink") }}</button>
            </template>
            <MediaPanel v-else :used="used" />
          </nav>
        </div>
      </div>
    </template>

    <!-- Recherche -->
    <div v-else-if="tab === 'recherche'" class="research">
      <div class="add-src">
        <input v-model="srcInput" class="input" :placeholder="t('script.research.placeholder')" @keydown.enter="addSource">
        <button class="btn dark md" @click="addSource">{{ t("common.add") }}</button>
      </div>
      <div class="sources">
        <div v-for="(s, i) in project.research" :key="`${i}-${s.u}-${s.t}`" class="source">
          <div class="src-head">
            <span class="t">{{ s.t }}<span v-if="s.by === 'claude'" class="by mono" :title="t('script.research.byTitle')">{{ t("common.assistant") }}</span></span>
            <a v-if="s.u" :href="s.u" target="_blank" rel="noopener" class="u mono">{{ s.u }}</a>
            <ConfirmX :label="t('script.research.removeConfirm')" :title="t('script.research.removeTitle')" @confirm="removeSource(i)" />
          </div>
          <textarea :value="s.n" rows="2" :placeholder="t('script.research.notePlaceholder')"
            @input="setNote(i, ($event.target as HTMLTextAreaElement).value)" />
        </div>
      </div>
    </div>

    <!-- Notes -->
    <div v-else class="notes">
      <div class="toolbar">
        <span class="eyebrow hint">{{ t("script.notes.hint") }}</span>
        <button class="btn sm" @click="copy(notes.content.value ?? '', t('script.notesCopied'))">{{ t("script.copyMarkdown") }}</button>
      </div>
      <textarea class="md-editor notes-md" :value="notes.content.value ?? ''" spellcheck="false"
        @input="notes.set(($event.target as HTMLTextAreaElement).value)" />
      <span class="saved mono">{{ saveLabel(notes.state.value) }}</span>
    </div>
  </div>
</template>

<style scoped>
.root { height: 100%; display: flex; flex-direction: column; }
.page-tabs { padding: 14px 32px 0; }
.error { margin: 0; font-size: 13px; color: var(--red-ink); }

.empty-state { padding: 48px 32px; display: flex; justify-content: center; }
.empty-state .dashed-box { max-width: 560px; display: flex; flex-direction: column; align-items: center; gap: 14px; padding: 36px 32px; }
.empty-state p { margin: 0; }
.empty-state .angle { color: var(--ink); font-weight: 600; }
.empty-state .actions { display: flex; flex-wrap: wrap; justify-content: center; gap: 10px; }

.script-layout { flex: 1; min-height: 0; display: flex; gap: 20px; padding: 16px 24px 20px; }

/* sommaire */
.toc { display: flex; flex-direction: column; gap: 2px; flex: 1; min-height: 0; overflow-y: auto; padding-right: 4px; }
.side-tabs { display: flex; gap: 16px; padding: 4px 2px 0; border-bottom: 1px solid var(--line); flex-shrink: 0; }
.side-tabs button {
  border: none; background: none; padding: 0 0 4px; font-family: var(--mono); font-size: 10.5px; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--faint); cursor: pointer; border-bottom: 2px solid transparent;
}
.side-tabs button.on { color: var(--ink); border-bottom-color: var(--ink); }
.side-tabs .dot { display: inline-block; width: 6px; height: 6px; margin-left: 5px; border-radius: 3px; background: var(--red); vertical-align: 1px; }
.side-tabs .n { margin-left: 5px; font-size: 10px; color: var(--off); }

/* résumé des plans sous le texte */
.plan-sum {
  display: flex; align-items: baseline; gap: 6px; padding: 1px 6px; border: none; border-radius: 4px; background: transparent;
  font: inherit; font-size: 12.5px; line-height: 1.5; color: var(--faint); text-align: left; cursor: pointer; min-width: 0;
}
.plan-sum:hover, .plan-sum.active { background: var(--bg-soft); color: var(--muted); }
.plan-sum.on { opacity: 0.55; }
.plan-sum .swatch { width: 7px; height: 7px; border-radius: 2px; flex-shrink: 0; align-self: center; }
.plan-sum .n { font-size: 10.5px; color: var(--off); }
.plan-sum .t { font-weight: 500; color: var(--muted); white-space: nowrap; }
.plan-sum .setup-tag { font-size: 10.5px; font-weight: 600; }
.plan-sum .note { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.plan-sum .file { font-size: 11px; white-space: nowrap; }
.sec {
  display: flex; flex-direction: column; gap: 1px; padding: 7px 10px; border-radius: 4px; cursor: pointer;
  border: none; background: transparent; text-align: left;
}
.sec:hover, .sec.on { background: var(--bg-soft); }
.sec .label { display: flex; justify-content: space-between; gap: 8px; font-family: var(--mono); font-size: 10.5px; color: var(--faint); }
.sec .dur { color: var(--muted); }
.sec .title { font-size: 13.5px; font-weight: 450; }
.sec.on .title { font-weight: 600; }
.add { margin-top: 6px; }
.sec-setup {
  display: inline-block; width: 14px; height: 14px; margin-right: 6px; border-radius: 3px; color: #fff;
  font-size: 9.5px; line-height: 14px; text-align: center; vertical-align: 1px;
}
.stats { display: flex; flex-direction: column; margin-top: 20px; border-top: 1px solid var(--line); }
.stat { display: flex; justify-content: space-between; padding: 7px 2px; border-bottom: 1px solid var(--line-soft); font-size: 12.5px; }
.stat span:first-child { color: var(--muted); }
.stat .mono { font-size: 12px; }
.angle-box { display: flex; flex-direction: column; gap: 4px; padding: 10px 2px 0; }
.angle-box .k { font-size: 11.5px; color: var(--faint); }
.angle-box .v { font-size: 12.5px; font-weight: 600; line-height: 1.4; }
.saved { font-size: 10.5px; color: var(--faint); padding: 10px 2px 0; }
.rewrite { align-self: flex-start; margin: 10px 2px 0; font-size: 12px; }

/* la page du script */
.center { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 8px; }
.toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.toolbar .btn.sm { height: 30px; }
.drafts { display: flex; align-items: center; gap: 6px; padding-right: 8px; border-right: 1px solid var(--line); }
.drafts .select { height: 30px; font-size: 12.5px; }
.hint { flex: 1 1 200px; min-width: 0; }
.writing { flex: 1 1 200px; min-width: 0; font-size: 12px; color: var(--red-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sheet-scroll { flex: 1; min-height: 0; overflow-y: auto; background: var(--bg-softer); border: 1px solid var(--line); border-radius: 6px; }
.sheet { max-width: 900px; min-height: 100%; margin: 0 auto; background: #fff; border-left: 1px solid var(--line-soft); border-right: 1px solid var(--line-soft); }

/* assistant */
.side { flex: 0 0 340px; min-width: 0; display: flex; flex-direction: column; gap: 12px; min-height: 0; }
.side :deep(.assistant) { flex: 1; max-width: none; height: auto; min-height: 0; }

/* recherche */
.research { padding: 24px 32px 40px; display: flex; flex-direction: column; gap: 16px; max-width: 820px; }
.add-src { display: flex; gap: 8px; }
.add-src .input { flex: 1; }
.add-src .btn { height: 38px; }
.sources { display: flex; flex-direction: column; }
.source { display: flex; flex-direction: column; gap: 6px; padding: 14px 0; border-top: 1px solid var(--line-soft); }
.src-head { display: flex; gap: 12px; align-items: baseline; min-width: 0; }
.src-head .t { font-size: 14.5px; font-weight: 600; flex: 1; }
.src-head .by { margin-left: 8px; padding: 1px 5px; border-radius: 3px; background: var(--line-soft); font-size: 10.5px; font-weight: 400; color: var(--muted); }
.src-head .u { font-size: 11.5px; color: var(--faint); max-width: 45%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.source textarea { border: none; padding: 0; font-size: 13.5px; line-height: 1.55; color: var(--ink-3); resize: vertical; background: transparent; }

/* notes */
.notes { padding: 20px 32px 32px; display: flex; flex-direction: column; gap: 8px; max-width: 820px; }
.notes .hint { flex: 1; }
.md-editor {
  min-height: 420px; height: calc(100vh - 290px); border: 1px solid var(--line); border-radius: 4px; resize: vertical;
  padding: 20px 24px; font-family: var(--mono); font-size: 14px; line-height: 1.75; color: var(--ink); background: #fff;
}
.app .md-editor:focus { outline: none; border-color: #B9B9B4; }
</style>
