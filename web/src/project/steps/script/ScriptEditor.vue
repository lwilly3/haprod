<script setup lang="ts">
/**
 * L'éditeur du script : le texte mis en page (titres, citations, liens, gras), un bloc par
 * paragraphe avec son id, et dans la marge le temps estimé où l'on en est.
 * Chaque bloc reste du Markdown : un bloc qu'on ne touche pas garde son Markdown d'origine.
 *
 * Les plans couvrent un passage (un mot, une phrase, plusieurs paragraphes) : il est surligné de
 * la couleur du type, un trait dans la marge en montre l'étendue, et sous le bloc où il finit la
 * page en affiche un résumé (slot `plans`). On en crée avec la bulle « + Plan » d'une sélection,
 * le « + » de la marge (tout le paragraphe) ou en déposant un média sur le texte.
 * Les passages suivent les retouches ; l'éditeur renvoie leur texte à jour (`anchors`).
 * Dans la marge droite des titres de section, le setup de tournage de la section (`setups`), à choisir
 * dans un menu (ou à créer).
 */
import type { JSONContent } from "@tiptap/core";
import { Markdown } from "@tiptap/markdown";
import StarterKit from "@tiptap/starter-kit";
import { EditorContent, useEditor } from "@tiptap/vue-3";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowReactive, watch } from "vue";
import { useI18n } from "vue-i18n";
import Thumb from "../../../components/Thumb.vue";
import { mmss } from "../../../lib/format";
import type { Plan, PlanMedia } from "../../types";
import { type Anchor, BlockId, Cues, endsByBlock, flatten, newBlockId, Plans, plansKey, Preview, previewKey, topBlock } from "./extensions";
import { colorOf, MEDIA_MIME, newPlan, typeOfMedia } from "./plans";
import type { Block } from "./useScript";

const props = defineProps<{
  blocks: Block[];
  /** change quand les blocs viennent du serveur : l'éditeur repart d'eux */
  version: number;
  readonly: boolean;
  /** temps estimé (s) au début de chaque bloc */
  times: Record<string, number>;
  plans: Plan[];
  /** le plan ouvert dans l'onglet Plan */
  active: string | null;
  /** le setup de chaque section (id du titre ; null : aucun) */
  setups?: Record<string, SetupLook | null>;
  /** les setups qu'on peut choisir */
  setupOptions?: (SetupLook & { id: string })[];
  /** sans le surlignage des passages ni les résumés des plans sous le texte (pour l'écrire tranquille) */
  plain?: boolean;
}>();
const emit = defineEmits<{
  change: [blocks: Block[]];
  /** passage sélectionné (texte), à joindre à la prochaine question */
  quote: [text: string];
  /** le bloc où se trouve le curseur */
  cursor: [id: string | null];
  /** un plan créé dans le texte (bulle, « + », média déposé) */
  addPlan: [plan: Plan];
  /** un plan à modifier (média déposé sur son passage) */
  update: [id: string, changes: Partial<Plan>];
  /** le passage des plans a changé avec le texte */
  anchors: [changes: { id: string; changes: Partial<Plan> }[]];
  /** un plan désigné dans le texte ; `open` : l'afficher dans l'onglet Plan */
  select: [id: string, open: boolean];
  /** le setup d'une section : un id, "" pour aucun, "new" pour en créer un */
  setup: [section: string, id: string];
}>();
interface SetupLook { letter: string; color: string; name: string }
const { t } = useI18n();
defineSlots<{ plans(props: { block: string; ids: string[] }): unknown }>();

// les emplacements des résumés, un par bloc, gardés d'un rendu à l'autre
const hosts = shallowReactive(new Map<string, HTMLElement>());

function host(id: string): HTMLElement {
  let el = hosts.get(id);
  if (!el) {
    el = document.createElement("div");
    el.className = "plans-host";
    el.contentEditable = "false";
    hosts.set(id, el);
  }
  return el;
}

const current = ref<string | null>(null);
const dropOn = ref<string | null>(null);
/** les plans à résumer sous chaque bloc */
const ends = ref<[string, string[]][]>([]);

const editor = useEditor({
  extensions: [StarterKit.configure({ link: { openOnClick: false } }), Markdown, BlockId, Cues, Plans(host), Preview],
  editable: !props.readonly,
  onUpdate: schedule,
  onTransaction: ({ editor: e }) => {
    const st = plansKey.getState(e.state);
    if (st) ends.value = [...endsByBlock(e.state.doc, st.ranges)];
    requestAnimationFrame(measure);
  },
  onSelectionUpdate: ({ editor: e }) => {
    const { from, to, $from } = e.state.selection;
    current.value = $from.depth > 0 ? ($from.node(1).attrs.id as string | null) : null;
    emit("cursor", current.value);
    if (to > from) {
      const text = slice(from, to);
      if (text) emit("quote", text);
    }
    placeBubble();
  },
  onBlur: () => setTimeout(() => (bubble.value = null), 150),
  editorProps: {
    handleClick: (_view, pos) => {
      const id = covering(pos)[0];
      if (id) emit("select", id, false);
      return false;
    },
    handleDrop: (view, event) => {
      const raw = event.dataTransfer?.getData(MEDIA_MIME);
      if (!raw) return false;
      dropOn.value = null;
      const at = view.posAtCoords({ left: event.clientX, top: event.clientY });
      if (at) dropMedia(at.pos, JSON.parse(raw) as PlanMedia);
      return true;
    },
  },
});

const state = () => plansKey.getState(editor.value!.state)!;

// --- blocs <-> document ---------------------------------------------------------------

/** Markdown d'origine des blocs chargés, pour ne pas réécrire ceux qu'on n'a pas touchés. */
const originals = new Map<string, { key: string; md: string }>();
const keyOf = (n: JSONContent) => JSON.stringify({ ...n, attrs: { ...n.attrs, id: null } });

function load(): void {
  const e = editor.value;
  if (!e?.markdown) return;
  const content: JSONContent[] = [];
  const single = new Set<string>();
  for (const b of props.blocks) {
    const nodes = e.markdown.parse(b.md).content ?? [];
    nodes.forEach((n, i) => content.push({ ...n, attrs: { ...n.attrs, id: i === 0 ? b.id : null } }));
    if (nodes.length === 1) single.add(b.id);
  }
  // hors historique : sinon Ctrl+Z annule le chargement et l'enregistrement automatique envoie un script vide
  e.chain()
    .setMeta("addToHistory", false)
    .setContent({ type: "doc", content: content.length ? content : [{ type: "paragraph" }] }, { emitUpdate: false })
    .run();
  originals.clear();
  const md = new Map(props.blocks.map((b) => [b.id, b.md]));
  for (const n of e.getJSON().content ?? []) {
    const id = n.attrs?.id as string | undefined;
    if (id && single.has(id)) originals.set(id, { key: keyOf(n), md: md.get(id)! });
  }
  syncPlans(true);
  measure();
}

function collect(): Block[] {
  const e = editor.value!;
  return (e.getJSON().content ?? []).map((n) => {
    const id = (n.attrs?.id as string | null) ?? newBlockId();
    const o = originals.get(id);
    const md = o && o.key === keyOf(n) ? o.md : e.markdown!.serialize({ type: "doc", content: [n] }).replace(/\n+$/, "");
    return { id, md };
  }).filter((b) => b.md.trim());
}

// les blocs repartent vers la page après une courte pause dans la frappe
let pending: ReturnType<typeof setTimeout> | undefined;

function schedule(): void {
  clearTimeout(pending);
  pending = setTimeout(flush, 250);
}

/** Envoie tout de suite les blocs en attente (avant d'enregistrer), et les passages des plans à jour. */
function flush(): void {
  if (pending === undefined) return;
  clearTimeout(pending);
  pending = undefined;
  if (!editor.value) return;
  emit("change", collect());
  sendAnchors();
}

watch([editor, () => props.version], ([e]) => e && load(), { immediate: true });
watch(() => props.readonly, (r) => editor.value?.setEditable(!r));
onBeforeUnmount(() => {
  clearTimeout(previewTimer);
  flush();
});

// --- passages des plans ------------------------------------------------------------------

function blockPos(id: string): number | null {
  let found: number | null = null;
  editor.value?.state.doc.forEach((n, offset) => {
    if (found == null && n.attrs.id === id) found = offset;
  });
  return found;
}

const blockAt = (pos: number) => topBlock(editor.value!.state.doc, pos)?.[0] ?? null;

/** Tout le contenu des blocs `from` à `to`. */
function wholeBlocks(from: string, to: string | null): Anchor | null {
  const doc = editor.value!.state.doc;
  const start = blockPos(from);
  if (start == null) return null;
  const endStart = (to ? blockPos(to) : null) ?? start;
  return { from: start + 1, to: endStart + doc.child(doc.resolve(endStart).index(0)).nodeSize - 1 };
}

/** Le passage d'un plan : son texte, cherché à partir de son bloc ; à défaut, ses blocs entiers. */
function locate(plan: Plan, flat: { text: string; pos: number[] }): Anchor | null {
  if (!plan.block) return null;
  const whole = wholeBlocks(plan.block, plan.end);
  if (!whole) return null;
  if (plan.q) {
    const start = flat.pos.findIndex((p) => p >= whole.from);
    const k = start < 0 ? -1 : flat.text.indexOf(plan.q, start);
    // au-delà de ses blocs, ce n'est plus son passage
    if (k >= 0 && flat.pos[k] < whole.to + 2) return { from: flat.pos[k], to: flat.pos[k + plan.q.length - 1] + 1 };
  }
  return whole;
}

/**
 * Passe les plans au surlignage. `full` (chargement) : tous les passages sont recherchés ;
 * sinon on garde ceux qu'on suit déjà (ils ont suivi les retouches) et on cherche les nouveaux.
 */
function syncPlans(full = false): void {
  const e = editor.value;
  if (!e) return;
  const known = full ? new Map<string, Anchor>() : state().ranges;
  const flat = flatten(e.state.doc);
  const ranges = new Map<string, Anchor>();
  for (const p of props.plans) {
    const r = known.get(p.id) ?? locate(p, flat);
    if (r && p.block) ranges.set(p.id, r);
  }
  const colors = new Map(props.plans.map((p) => [p.id, colorOf(p.type)]));
  e.view.dispatch(e.state.tr.setMeta(plansKey, { ranges, colors, active: props.active }).setMeta("addToHistory", false));
  if (full) sendAnchors();
}

watch(() => props.plans, () => syncPlans());
watch(() => props.active, (active) => {
  const e = editor.value;
  if (e) e.view.dispatch(e.state.tr.setMeta(plansKey, { active }).setMeta("addToHistory", false));
});

/** Ce que couvre chaque passage maintenant (texte, blocs) : renvoyé à la page s'il a changé. */
function anchorOf(r: Anchor): Pick<Plan, "block" | "end" | "q"> {
  const block = blockAt(r.from), end = r.to > r.from ? blockAt(r.to - 1) : block;
  return { block, end: end && end !== block ? end : null, q: r.to > r.from ? slice(r.from, r.to) : "" };
}

function sendAnchors(only?: string): void {
  if (!editor.value) return;
  const changed: { id: string; changes: Partial<Plan> }[] = [];
  for (const [id, r] of state().ranges) {
    if (only && id !== only) continue;
    const plan = props.plans.find((p) => p.id === id);
    if (!plan) continue;
    const now = anchorOf(r);
    // un passage effacé : le plan reste sur son bloc
    if (!now.block) continue;
    if (now.block !== plan.block || now.end !== (plan.end ?? null) || now.q !== plan.q) changed.push({ id, changes: now });
  }
  if (changed.length) emit("anchors", changed);
}

/** Les plans dont le passage contient `pos`, du plus court au plus long. */
function covering(pos: number): string[] {
  if (!editor.value) return [];
  return [...state().ranges].filter(([, r]) => r.from <= pos && pos <= r.to)
    .sort(([, a], [, b]) => a.to - a.from - (b.to - b.from)).map(([id]) => id);
}

/** Un nouveau plan sur un passage : suivi tout de suite, et ouvert dans l'onglet Plan. */
function create(r: Anchor, changes: Partial<Plan> = {}): void {
  const e = editor.value!;
  const plan = newPlan(null, { ...anchorOf(r), ...changes });
  const ranges = new Map(state().ranges).set(plan.id, r);
  const colors = new Map(state().colors).set(plan.id, colorOf(plan.type));
  e.view.dispatch(e.state.tr.setMeta(plansKey, { ranges, colors, active: plan.id }).setMeta("addToHistory", false));
  emit("addPlan", plan);
  bubble.value = null;
}

/** Bulle « + Plan » : la sélection. */
function planOnSelection(): void {
  const { from, to } = editor.value!.state.selection;
  if (to > from) create({ from, to });
}

/** « + » de la marge : tout le paragraphe. */
function planOnBlock(id: string): void {
  const r = wholeBlocks(id, null);
  if (r) create(r);
}

/** Un média déposé complète le plus court des plans du passage qui n'a pas de fichier ; sinon il fait un plan du paragraphe. */
function dropMedia(pos: number, media: PlanMedia): void {
  const target = covering(pos).find((id) => !props.plans.find((p) => p.id === id)?.media.length);
  if (target) {
    emit("update", target, { media: [media] });
    emit("select", target, false);
    return;
  }
  const id = blockAt(pos);
  const r = id ? wholeBlocks(id, null) : null;
  if (r) create(r, { type: typeOfMedia(media), media: [media] });
}

/** Le plan couvre désormais la sélection ; false s'il n'y a rien de sélectionné. */
function reanchor(id: string): boolean {
  const e = editor.value!;
  const { from, to } = e.state.selection;
  if (to <= from) return false;
  const ranges = new Map(state().ranges).set(id, { from, to });
  e.view.dispatch(e.state.tr.setMeta(plansKey, { ranges }).setMeta("addToHistory", false));
  emit("anchors", [{ id, changes: anchorOf({ from, to }) }]);
  return true;
}

/** Amène le passage d'un plan à l'écran. */
function showPlan(id: string): void {
  const e = editor.value, r = e && state().ranges.get(id);
  if (!e || !r) return;
  const dom = e.view.domAtPos(r.from).node;
  (dom.nodeType === 1 ? dom as HTMLElement : dom.parentElement)?.scrollIntoView({ behavior: "smooth", block: "center" });
}

let previewTimer: ReturnType<typeof setTimeout> | undefined;

/** Surligne un moment le passage `q` du bloc `block` (tout le bloc si `q` est vide) et l'amène à l'écran. */
function preview(block: string, q: string, color: string): boolean {
  const e = editor.value;
  if (!e) return false;
  const r = locate({ block, end: null, q } as Plan, flatten(e.state.doc));
  if (!r) return false;
  clearTimeout(previewTimer);
  e.view.dispatch(e.state.tr.setMeta(previewKey, { ...r, color }).setMeta("addToHistory", false));
  const dom = e.view.domAtPos(r.from).node;
  (dom.nodeType === 1 ? dom as HTMLElement : dom.parentElement)?.scrollIntoView({ behavior: "smooth", block: "center" });
  previewTimer = setTimeout(() => {
    editor.value?.view.dispatch(editor.value.state.tr.setMeta(previewKey, null).setMeta("addToHistory", false));
  }, 4000);
  return true;
}

// --- passages cités ----------------------------------------------------------------------

function slice(from: number, to: number): string {
  const { text, pos } = flatten(editor.value!.state.doc);
  const start = pos.findIndex((p) => p >= from);
  let end = pos.length - 1;
  while (end >= 0 && pos[end] >= to) end--;
  return start < 0 || end < start ? "" : text.slice(start, end + 1).trim();
}

/** Remplace un passage cité par le Markdown de Claude ; false s'il n'est plus dans le texte. */
function replace(passage: string, md: string): boolean {
  const e = editor.value;
  if (!e) return false;
  const { text, pos } = flatten(e.state.doc);
  const k = text.indexOf(passage.trim());
  if (k < 0) return false;
  const from = pos[k], to = pos[k + passage.trim().length - 1] + 1;
  e.chain().focus().insertContentAt({ from, to }, md.trim(), { contentType: "markdown" }).run();
  flush();
  return true;
}

/** Place le curseur au début d'un bloc et l'amène en haut de la page. */
function goTo(id: string): void {
  const e = editor.value, p = blockPos(id);
  if (!e || p == null) return;
  e.commands.focus();
  e.commands.setTextSelection(p + 1);
  (e.view.nodeDOM(p) as HTMLElement | null)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

/** Ajoute du Markdown à la fin du texte et y place le curseur. */
async function append(md: string): Promise<void> {
  const e = editor.value;
  if (!e) return;
  e.chain().focus().insertContentAt(e.state.doc.content.size, md, { contentType: "markdown" }).run();
  flush();
  await nextTick();
  const last = e.state.doc.lastChild?.attrs.id as string | undefined;
  if (last) goTo(last);
}

function selectAll(): void {
  editor.value?.chain().focus().selectAll().run();
}

defineExpose({ goTo, replace, append, flush, selectAll, reanchor, showPlan, preview });

// --- marge : temps estimé, « + », traits des plans ; bulle de la sélection -----------------

const page = ref<HTMLElement>();
const height = ref(0);
const marks = ref<{ id: string; top: number; head: boolean }[]>([]);
const bars = ref<{ id: string; top: number; height: number; lane: number; color: string; media: PlanMedia | null }[]>([]);
const hovered = ref<string | null>(null);
const bubble = ref<{ top: number; left: number } | null>(null);
const LANE = 7;

function measure(): void {
  const e = editor.value;
  const root = e?.view.dom as HTMLElement | undefined;
  if (!e || !root || !page.value) return;
  // pas offsetTop : .tiptap est positionné
  const box = page.value.getBoundingClientRect();
  height.value = box.height;
  marks.value = [...root.children].flatMap((el) => {
    const id = (el as HTMLElement).dataset.block;
    return id ? [{ id, top: el.getBoundingClientRect().top - box.top, head: /^H[1-3]$/.test(el.tagName) }] : [];
  });
  // un trait par plan, sur toute la hauteur de son passage ; ceux qui se chevauchent prennent une autre piste
  const size = e.state.doc.content.size;
  const spans = [...state().ranges].filter(([, r]) => r.to > r.from && r.to <= size)
    .map(([id, r]) => ({ id, top: e.view.coordsAtPos(r.from, 1).top - box.top, bottom: e.view.coordsAtPos(r.to, -1).bottom - box.top }))
    .sort((a, b) => a.top - b.top);
  const lanes: number[] = [];
  bars.value = spans.map((s) => {
    let lane = lanes.findIndex((bottom) => bottom < s.top - 2);
    if (lane < 0) lane = lanes.length;
    lanes[lane] = s.bottom;
    const plan = props.plans.find((p) => p.id === s.id);
    return { id: s.id, top: s.top, height: Math.max(8, s.bottom - s.top), lane, color: colorOf(plan?.type ?? ""), media: plan?.media[0] ?? null };
  });
}

/** La section dont le menu des setups est ouvert. */
const setupMenu = ref<string | null>(null);

function pickSetup(section: string, id: string): void {
  setupMenu.value = null;
  emit("setup", section, id);
}

/** Une bande par section qui a un setup, du titre à la section suivante. */
const bands = computed(() => {
  const heads = marks.value.filter((m) => props.setups && m.id in props.setups);
  return heads.flatMap((m, i) => {
    const s = props.setups![m.id];
    const bottom = heads[i + 1]?.top ?? height.value - 100;
    return s ? [{ id: m.id, top: m.top, height: Math.max(0, bottom - m.top - 42), color: s.color }] : [];
  });
});

function placeBubble(): void {
  const e = editor.value;
  if (!e || !page.value || props.readonly) return;
  const { from, to } = e.state.selection;
  if (to <= from || !e.isFocused) {
    bubble.value = null;
    return;
  }
  const box = page.value.getBoundingClientRect();
  const end = e.view.coordsAtPos(to, -1);
  bubble.value = { top: end.bottom - box.top + 6, left: Math.min(end.left - box.left, box.width - 110) };
}

function onMove(e: MouseEvent): void {
  const el = (e.target as HTMLElement).closest<HTMLElement>(".tiptap > [data-block]");
  if (el) hovered.value = el.dataset.block ?? null;
}

function onDragOver(e: DragEvent): void {
  if (!e.dataTransfer?.types.includes(MEDIA_MIME)) return;
  e.preventDefault();
  const at = editor.value?.view.posAtCoords({ left: e.clientX, top: e.clientY });
  dropOn.value = at ? blockAt(at.pos) : null;
}

let observer: ResizeObserver | undefined;
// un clic ailleurs ferme le menu des setups
const closeMenu = (e: MouseEvent) => {
  if (!(e.target as HTMLElement).closest(".setup-rail")) setupMenu.value = null;
};
onMounted(() => {
  observer = new ResizeObserver(() => measure());
  if (page.value) observer.observe(page.value);
  document.addEventListener("mousedown", closeMenu);
});
onBeforeUnmount(() => {
  observer?.disconnect();
  document.removeEventListener("mousedown", closeMenu);
});
</script>

<template>
  <div ref="page" class="page" :class="{ readonly, plain }" @mousemove="onMove" @mouseleave="hovered = null"
    @dragover="onDragOver" @dragleave.self="dropOn = null">
    <div class="gutter">
      <template v-for="m in marks" :key="m.id">
        <span v-if="(m.head || m.id === current) && times[m.id] != null" class="time mono" :class="{ head: m.head }"
          :style="{ top: `${m.top}px` }">{{ mmss(times[m.id]) }}</span>
        <button v-if="!readonly && !m.head && (m.id === hovered || m.id === current)" class="add" :style="{ top: `${m.top}px` }"
          :title="t('script.editor.addTitle')" @mousedown.prevent @click="planOnBlock(m.id)">+</button>
        <span v-if="m.id === dropOn" class="drop" :style="{ top: `${m.top}px` }">{{ t("script.editor.drop") }}</span>
      </template>
      <template v-for="b in bars" :key="b.id">
        <button class="bar" :class="{ active: b.id === active }" :title="t('script.editor.seePlan')"
          :style="{ top: `${b.top}px`, height: `${b.height}px`, right: `${10 + b.lane * LANE}px`, background: b.color }"
          @click="emit('select', b.id, true)" />
        <button v-if="b.media" class="gthumb" :style="{ top: `${b.top}px` }"
          :title="b.media.name" @click="emit('select', b.id, true)">
          <Thumb :src="b.media.url" :kind="b.media.kind" :name="b.media.name" />
        </button>
      </template>
    </div>
    <div v-if="setups" class="setup-rail">
      <span v-for="b in bands" :key="'band-' + b.id" class="band" :style="{ top: `${b.top}px`, height: `${b.height}px`, background: b.color }" />
      <template v-for="m in marks" :key="'setup-' + m.id">
        <template v-if="m.id in setups">
          <button class="setup mono" :class="{ none: !setups[m.id] }" :style="{ top: `${m.top}px`, background: setups[m.id]?.color }"
            :title="setups[m.id] ? t('script.editor.sectionShotIn', { setup: `${setups[m.id]!.letter}${setups[m.id]!.name ? ' · ' + setups[m.id]!.name : ''}` }) : t('script.editor.pickSetup')"
            @click="setupMenu = setupMenu === m.id ? null : m.id">{{ setups[m.id]?.letter ?? t("script.editor.setup") }}</button>
          <div v-if="setupMenu === m.id" class="setup-menu" :style="{ top: `${m.top + 32}px` }">
            <button v-for="o in setupOptions ?? []" :key="o.id" :class="{ on: setups[m.id]?.letter === o.letter }" @click="pickSetup(m.id, o.id)">
              <span class="dot mono" :style="{ background: o.color }">{{ o.letter }}</span>{{ o.name || t("script.editor.setupN", { letter: o.letter }) }}
            </button>
            <button @click="pickSetup(m.id, 'new')"><span class="dot new">+</span>{{ t("script.editor.newSetup") }}</button>
            <button v-if="setups[m.id]" @click="pickSetup(m.id, '')"><span class="dot new">×</span>{{ t("script.editor.none") }}</button>
          </div>
        </template>
      </template>
    </div>
    <EditorContent :editor="editor" class="content" />
    <button v-if="bubble" class="bubble" :style="{ top: `${bubble.top}px`, left: `${bubble.left}px` }"
      @mousedown.prevent @click="planOnSelection">{{ t("script.editor.addPlan") }}</button>
    <template v-for="[block, ids] in ends" :key="block">
      <Teleport v-if="hosts.get(block)" :to="hosts.get(block)" defer>
        <slot name="plans" :block="block" :ids="ids" />
      </Teleport>
    </template>
  </div>
</template>

<style scoped>
.page { position: relative; padding: 40px 64px 120px 184px; }
.gutter { position: absolute; top: 0; left: 0; width: 172px; }
.time { position: absolute; right: 70px; padding-top: 4px; font-size: 10.5px; color: var(--off); }
.time.head { padding-top: 10px; color: var(--faint); }
.add {
  position: absolute; right: 40px; margin-top: 2px; width: 22px; height: 22px; border-radius: 4px;
  border: 1px solid var(--line-strong); background: #fff; color: var(--muted); font-size: 14px; line-height: 1;
  cursor: pointer; padding: 0;
}
.add:hover { border-color: var(--ink); color: var(--ink); }
.drop { position: absolute; right: 36px; padding-top: 4px; font-size: 11px; color: var(--red-ink); white-space: nowrap; }
.bar { position: absolute; width: 3px; padding: 0; border: none; border-radius: 2px; opacity: 0.55; cursor: pointer; }
.bar:hover, .bar.active { opacity: 1; width: 4px; }
.setup-rail { position: absolute; top: 0; right: 0; width: 60px; }
.band { position: absolute; right: 27px; margin-top: 34px; width: 3px; border-radius: 2px; opacity: 0.35; pointer-events: none; }
.setup {
  position: absolute; right: 8px; margin-top: 6px; min-width: 22px; height: 22px; padding: 0 5px; border-radius: 4px;
  border: none; color: #fff; font-size: 11px; cursor: pointer; z-index: 2;
}
.setup.none { right: 4px; background: #fff; border: 1px dashed var(--dash); color: var(--muted-2); font-size: 10.5px; }
.setup.none:hover { border-color: var(--ink); color: var(--ink); }
.setup:not(.none):hover { filter: brightness(1.1); }
.setup-menu {
  position: absolute; right: 4px; z-index: 6; width: 200px; padding: 4px; background: #fff; border: 1px solid var(--line-strong);
  border-radius: 6px; box-shadow: 0 6px 18px rgba(0, 0, 0, .12); display: flex; flex-direction: column;
}
.setup-menu button {
  display: flex; align-items: center; gap: 8px; padding: 6px 8px; border: none; border-radius: 4px; background: none;
  font-size: 13px; color: var(--ink-2); text-align: left; cursor: pointer;
}
.setup-menu button:hover, .setup-menu button.on { background: var(--bg-soft); }
.setup-menu .dot {
  width: 18px; height: 18px; border-radius: 4px; color: #fff; font-size: 10.5px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
}
.setup-menu .dot.new { background: none; border: 1px dashed var(--dash); color: var(--muted-2); }
.gthumb { position: absolute; right: 106px; padding: 0; border: none; background: none; cursor: pointer; }
.gthumb :deep(.thumb) { width: 60px; height: 34px; border-radius: 3px; }
.bubble {
  position: absolute; z-index: 5; height: 26px; padding: 0 10px; border: none; border-radius: 13px;
  background: var(--ink); color: #fff; font-size: 12px; cursor: pointer; box-shadow: 0 4px 12px rgba(0, 0, 0, .18);
}
.readonly .content { opacity: 0.6; }

.content :deep(.tiptap) { outline: none; font-size: 15.5px; line-height: 1.7; color: var(--ink-2); }
.content :deep(.tiptap > *) { margin: 0 0 14px; }
.content :deep(.tiptap h1) { font-size: 24px; font-weight: 650; letter-spacing: -0.015em; margin: 0 0 18px; }
.content :deep(.tiptap h2) { font-size: 19px; font-weight: 650; color: var(--ink); margin: 34px 0 12px; }
.content :deep(.tiptap h2::before) { content: "# "; color: var(--off); font-weight: 500; }
.content :deep(.tiptap h3) { font-size: 16px; font-weight: 650; margin: 22px 0 8px; }
.content :deep(.tiptap blockquote) { border-left: 2px solid var(--line-strong); padding-left: 16px; color: var(--ink-3); font-style: italic; }
.content :deep(.tiptap blockquote > *) { margin: 0; }
.content :deep(.tiptap a) { color: inherit; text-decoration: underline; text-decoration-color: var(--dash); text-underline-offset: 3px; }
.content :deep(.tiptap ul), .content :deep(.tiptap ol) { padding-left: 22px; }
.content :deep(.tiptap li > p) { margin: 0 0 4px; }
.content :deep(.tiptap hr) { border: none; border-top: 1px solid var(--line); margin: 24px 0; }
.content :deep(.tiptap code) { font-family: var(--mono); font-size: 0.9em; background: var(--bg-soft); padding: 1px 4px; border-radius: 3px; }
.content :deep(.tiptap p.cue) { font-family: var(--mono); font-size: 12.5px; line-height: 1.55; color: var(--faint); }
.content :deep(.tiptap .planned) { border-radius: 2px; box-decoration-break: clone; -webkit-box-decoration-break: clone; }
.content :deep(.tiptap .planned.active) { box-shadow: 0 2px 0 var(--plan); }
.content :deep(.tiptap .previewed) {
  border-radius: 2px; box-decoration-break: clone; -webkit-box-decoration-break: clone;
  outline: 2px dashed var(--plan); outline-offset: 1px; animation: previewed 4s ease-out;
}
@keyframes previewed { 0%, 15% { background-color: color-mix(in srgb, var(--plan) 30%, transparent); } }
.content :deep(.tiptap .plans-host) { display: flex; flex-direction: column; gap: 1px; margin: -10px 0 14px; }
.plain .content :deep(.tiptap .planned) { background-color: transparent !important; box-shadow: none; }
.plain .content :deep(.tiptap .plans-host) { display: none; }
</style>
