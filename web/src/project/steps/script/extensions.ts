/** Extensions TipTap de l'éditeur du script : l'id des blocs, et les indications [VISUEL…] en retrait. */
import { Extension } from "@tiptap/core";
import type { Node as PMNode } from "@tiptap/pm/model";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

/** Les nœuds de premier niveau qui font un bloc du script. */
export const BLOCK_TYPES = ["paragraph", "heading", "blockquote", "bulletList", "orderedList", "codeBlock", "horizontalRule"];

export const newBlockId = (): string => "b" + crypto.randomUUID().replace(/-/g, "").slice(0, 8);

/**
 * Chaque bloc de premier niveau porte un id (attribut `id`, `data-block` dans le DOM). Un bloc
 * coupé en deux (Entrée) garde son id dans la première moitié ; la seconde, comme tout bloc
 * nouveau ou dupliqué (coller), en reçoit un neuf.
 */
export const BlockId = Extension.create({
  name: "blockId",

  addGlobalAttributes() {
    return [{
      types: BLOCK_TYPES,
      attributes: {
        id: {
          default: null,
          keepOnSplit: false,
          parseHTML: (el: HTMLElement) => el.getAttribute("data-block"),
          renderHTML: (attrs: Record<string, unknown>) => (attrs.id ? { "data-block": attrs.id } : {}),
        },
      },
    }];
  },

  addProseMirrorPlugins() {
    return [new Plugin({
      key: new PluginKey("blockId"),
      appendTransaction(transactions, _old, state) {
        if (!transactions.some((t) => t.docChanged)) return null;
        const tr = state.tr;
        const seen = new Set<string>();
        state.doc.forEach((node, offset) => {
          if (!BLOCK_TYPES.includes(node.type.name)) return;
          let id = node.attrs.id as string | null;
          if (!id || seen.has(id)) {
            id = newBlockId();
            tr.setNodeMarkup(offset, undefined, { ...node.attrs, id });
          }
          seen.add(id);
        });
        return tr.docChanged ? tr.setMeta("addToHistory", false) : null;
      },
    })];
  },
});

function cues(doc: PMNode): DecorationSet {
  const found: Decoration[] = [];
  doc.forEach((node, offset) => {
    if (node.type.name === "paragraph" && node.textContent.trimStart().startsWith("[")) {
      found.push(Decoration.node(offset, offset + node.nodeSize, { class: "cue" }));
    }
  });
  return DecorationSet.create(doc, found);
}

/** Les lignes [VISUEL : …], [À VÉRIFIER]… ne sont pas dites : on les affiche en retrait. */
export const Cues = Extension.create({
  name: "cues",
  addProseMirrorPlugins() {
    return [new Plugin({
      key: new PluginKey("cues"),
      state: {
        init: (_, state) => cues(state.doc),
        apply: (tr, set) => (tr.docChanged ? cues(tr.doc) : set),
      },
      props: { decorations(state) { return this.getState(state); } },
    })];
  },
});

/** Le passage d'un plan dans le document. */
export interface Anchor { from: number; to: number }

export interface PlansState {
  /** id du plan -> son passage, suivi au fil des modifications */
  ranges: Map<string, Anchor>;
  /** id du plan -> sa couleur (celle de son type) */
  colors: Map<string, string>;
  active: string | null;
  set: DecorationSet;
}

type PlansMeta = Partial<Pick<PlansState, "ranges" | "colors" | "active">>;

export const plansKey = new PluginKey<PlansState>("plans");

/** Le bloc de premier niveau qui contient la position `pos` : [id, début, nœud]. */
export function topBlock(doc: PMNode, pos: number): [string | null, number, PMNode] | null {
  let found: [string | null, number, PMNode] | null = null;
  doc.forEach((node, offset) => {
    if (!found && pos >= offset && pos <= offset + node.nodeSize) found = [(node.attrs.id as string | null) ?? null, offset, node];
  });
  return found;
}

/** Les plans dont le passage finit dans chaque bloc : c'est sous ce bloc qu'on les résume. */
export function endsByBlock(doc: PMNode, ranges: Map<string, Anchor>): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const [id, r] of ranges) {
    if (r.to <= r.from) continue;
    const id_ = topBlock(doc, r.to - 1)?.[0];
    if (id_) out.set(id_, [...(out.get(id_) ?? []), id]);
  }
  return out;
}

/**
 * Les passages des plans : surlignés de la couleur de leur type (plus fort pour le plan actif),
 * et sous le bloc où chacun finit, un emplacement non éditable (`host(id)`) où la page résume
 * les plans. Les passages suivent les modifications du texte ; on les remplace avec
 * `tr.setMeta(plansKey, { ranges, colors, active })` (chaque champ facultatif).
 */
export function Plans(host: (block: string) => HTMLElement) {
  function build(doc: PMNode, st: Omit<PlansState, "set">): DecorationSet {
    const found: Decoration[] = [];
    for (const [id, r] of st.ranges) {
      if (r.to <= r.from || r.to > doc.content.size) continue;
      const c = st.colors.get(id) ?? "#7D7E7A";
      const on = id === st.active;
      found.push(Decoration.inline(r.from, r.to, {
        class: on ? "planned active" : "planned",
        style: `background-color: ${c}${on ? "40" : "1f"}; --plan: ${c}`,
      }));
    }
    const ends = endsByBlock(doc, st.ranges);
    doc.forEach((node, offset) => {
      const id = node.attrs.id as string | null;
      if (id && ends.has(id)) {
        found.push(Decoration.widget(offset + node.nodeSize, () => host(id), {
          key: `plans-${id}`, side: -1, ignoreSelection: true, stopEvent: () => true,
        }));
      }
    });
    return DecorationSet.create(doc, found);
  }

  return Extension.create({
    name: "plans",
    addProseMirrorPlugins() {
      return [new Plugin<PlansState>({
        key: plansKey,
        state: {
          init: (_, state) => {
            const st = { ranges: new Map<string, Anchor>(), colors: new Map<string, string>(), active: null };
            return { ...st, set: build(state.doc, st) };
          },
          apply: (tr, value) => {
            const meta = tr.getMeta(plansKey) as PlansMeta | undefined;
            let ranges = value.ranges;
            if (tr.docChanged) {
              // un passage ne s'étend pas à ce qu'on tape juste avant ou juste après lui
              ranges = new Map([...ranges].map(([id, r]) => [id, { from: tr.mapping.map(r.from, 1), to: tr.mapping.map(r.to, -1) }]));
            }
            const st = {
              ranges: meta?.ranges ?? ranges,
              colors: meta?.colors ?? value.colors,
              active: meta && "active" in meta ? meta.active ?? null : value.active,
            };
            if (!tr.docChanged && !meta) return value;
            return { ...st, set: build(tr.doc, st) };
          },
        },
        props: { decorations(state) { return this.getState(state)?.set; } },
      })];
    },
  });
}

export const previewKey = new PluginKey<DecorationSet>("preview");

/**
 * Un passage montré sans être un plan (celui d'un plan proposé par l'assistant) :
 * `tr.setMeta(previewKey, { from, to, color })` le surligne, `tr.setMeta(previewKey, null)` l'efface.
 */
export const Preview = Extension.create({
  name: "preview",
  addProseMirrorPlugins() {
    return [new Plugin<DecorationSet>({
      key: previewKey,
      state: {
        init: () => DecorationSet.empty,
        apply: (tr, set) => {
          const meta = tr.getMeta(previewKey) as (Anchor & { color: string }) | null | undefined;
          if (meta === undefined) return set.map(tr.mapping, tr.doc);
          if (!meta || meta.to <= meta.from) return DecorationSet.empty;
          return DecorationSet.create(tr.doc, [Decoration.inline(meta.from, meta.to, {
            class: "previewed", style: `--plan: ${meta.color}`,
          })]);
        },
      },
      props: { decorations(state) { return this.getState(state); } },
    })];
  },
});

/**
 * Le texte du document tel qu'on le montre à Claude (blocs séparés par une ligne vide), avec
 * pour chaque caractère sa position dans le document : de quoi retrouver un passage cité.
 */
export function flatten(doc: PMNode): { text: string; pos: number[] } {
  // (sur un autre nœud que le document, les positions sont relatives au début de son contenu)
  let text = "";
  const pos: number[] = [];
  let first = true;
  doc.descendants((node, p) => {
    if (node.isTextblock) {
      if (!first) {
        text += "\n\n";
        pos.push(p, p);
      }
      first = false;
    } else if (node.isText) {
      text += node.text!;
      for (let i = 0; i < node.text!.length; i++) pos.push(p + i);
    } else if (node.type.name === "hardBreak") {
      text += "\n";
      pos.push(p);
    }
    return true;
  });
  return { text, pos };
}
