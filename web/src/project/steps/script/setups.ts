/** Les setups de tournage : leur lettre, leur couleur, et le texte qu'on dit dans chacun (pour le prompteur). */
import type { Plan, Setup } from "../../types";
import { wordCount } from "./markdown";
import { FILMED, type OrderedPlan, plain } from "./plans";
import type { Block } from "./useScript";

const COLORS = ["#3B5BDB", "#2F9E44", "#E8590C", "#AE3EC9", "#0C8599", "#C2255C", "#5C940D", "#862E9C"];

export const letterOf = (index: number): string => String.fromCharCode(65 + (index % 26));
export const setupColor = (index: number): string => COLORS[index % COLORS.length];

export function newSetup(): Setup {
  return { id: "s" + crypto.randomUUID().replace(/-/g, "").slice(0, 8), name: "", note: "" };
}

/** Le setup d'un plan : le sien, sinon celui de sa section pour un face caméra ("" : aucun). */
export function setupOf(plan: Plan, section: string | null, sections: Record<string, string>): string {
  if (plan.setup) return plan.setup;
  return plan.type === "Face caméra" && section ? sections[section] ?? "" : "";
}

/** Un morceau du texte dit, et le setup où on le dit. */
export interface Spoken { block: string; text: string; setup: string }

const lower = (t: string) => t.replace(/[’‘]/g, "'").replace(/[“”«»]/g, '"').toLowerCase();

/**
 * Le texte dit, morceau par morceau dans l'ordre du script : chaque paragraphe se dit dans le setup
 * de sa section, sauf les passages couverts par un face caméra qui a son propre setup.
 */
export function spoken(blocks: Block[], plans: Plan[], sections: Record<string, string>): Spoken[] {
  const at = new Map(blocks.map((b, i) => [b.id, i]));
  // pour chaque bloc, les passages dits ailleurs : [texte ("" : tout le bloc), setup]
  const overrides = new Map<string, [string, string][]>();
  for (const p of plans) {
    if (p.type !== "Face caméra" || !p.setup || p.block == null) continue;
    const start = at.get(p.block), end = p.end != null ? at.get(p.end) ?? start : start;
    if (start == null || end == null) continue;
    const pieces = p.q ? p.q.split(/\n\s*\n/) : [];
    for (let i = start; i <= end; i++) {
      const piece = !p.q ? "" : start === end ? p.q : i === start ? pieces[0] : i === end ? pieces.at(-1)! : "";
      const list = overrides.get(blocks[i].id) ?? [];
      list.push([piece, p.setup]);
      overrides.set(blocks[i].id, list);
    }
  }

  const out: Spoken[] = [];
  let current = "";
  for (const b of blocks) {
    if (b.md.startsWith("#")) {
      if (/^##\s/.test(b.md)) current = sections[b.id] ?? "";
      continue;
    }
    const text = plain(b.md);
    if (!text) continue;
    // les passages repérés dans le texte, du début à la fin ; introuvable : tout le bloc
    const cuts: { from: number; to: number; setup: string }[] = [];
    for (const [piece, setup] of overrides.get(b.id) ?? []) {
      const from = piece ? lower(text).indexOf(lower(plain(piece))) : -1;
      cuts.push(from >= 0 ? { from, to: from + plain(piece).length, setup } : { from: 0, to: text.length, setup });
    }
    cuts.sort((x, y) => x.from - y.from);
    let pos = 0;
    const push = (t: string, setup: string) => {
      t = t.trim();
      if (!t) return;
      const last = out.at(-1);
      if (last && last.block === b.id && last.setup === setup) last.text += " " + t;
      else out.push({ block: b.id, text: t, setup });
    };
    for (const c of cuts) {
      if (c.to <= pos) continue;
      push(text.slice(pos, Math.max(pos, c.from)), current);
      push(text.slice(Math.max(pos, c.from), c.to), c.setup);
      pos = c.to;
    }
    push(text.slice(pos), current);
  }
  return out;
}

/** Le texte d'un setup, prêt à coller dans le prompteur : un paragraphe par bloc. */
export function setupText(parts: Spoken[], setup: string): string {
  return parts.filter((s) => s.setup === setup).map((s) => s.text).join("\n\n");
}

/** La durée estimée du texte d'un setup, en secondes (~150 mots par minute). */
export function setupSeconds(parts: Spoken[], setup: string): number {
  return (parts.filter((s) => s.setup === setup).reduce((n, s) => n + wordCount(s.text), 0) / 150) * 60;
}

export interface SetupStat { plans: number; seconds: number }

/** Par setup ("" : aucun) : le nombre de plans filmés et la durée du texte à y dire. */
export function setupStats(setups: Setup[], ordered: OrderedPlan[], parts: Spoken[],
  sections: Record<string, string>): Record<string, SetupStat> {
  const filmed = ordered.filter((o) => FILMED.includes(o.plan.type));
  return Object.fromEntries(["", ...setups.map((s) => s.id)].map((id) => [id, {
    plans: filmed.filter((o) => setupOfOrdered(o, sections) === id).length,
    seconds: setupSeconds(parts, id),
  }]));
}

/** Le setup d'un plan placé dans le texte (sa section vient de orderPlans). */
export const setupOfOrdered = (o: OrderedPlan, sections: Record<string, string>): string =>
  setupOf(o.plan, o.plan.block ? o.section?.id ?? null : null, sections);
