/** Ce que la barre du haut et la vue d'ensemble affichent de chaque étape. */
import { locale, t } from "../i18n";
import { PHASES, STEPS, type Phase, type Step } from "./steps";
import type { Project, StepState } from "./types";

/** Pastille d'une étape : [fond, bordure]. */
export const DOT: Record<StepState, [string, string]> = {
  skip: ["#fff", "1px dashed var(--dash)"],
  done: ["var(--ink)", "1px solid var(--ink)"],
  cur: ["#fff", "3px solid var(--red)"],
  todo: ["#fff", "1px solid var(--dash)"],
};

/** Petit libellé à droite de chaque étape. */
export function stepSub(p: Project, id: string): string {
  switch (id) {
    case "titre": {
      const n = p.titles.filter((x) => x.pick).length;
      return n ? t("nav.sub.titlesKept", n) : "";
    }
    case "vignette": {
      const n = p.thumbs.filter((x) => x.pick).length;
      return n ? t("nav.sub.thumbsKept", n) : "";
    }
    case "script": return p.runtime.script_words ? t("nav.sub.words", p.runtime.script_words) : "";
    case "roast": return p.runtime.roast_score != null ? `${p.runtime.roast_score.toLocaleString(locale())}/10` : "";
    case "tournage": return p.runtime.plans.total ? t("nav.sub.shots", { done: p.runtime.plans.done, total: p.runtime.plans.total }) : "";
    case "derush": return p.rushes.length ? t("nav.sub.rushes", p.rushes.length) : "";
    case "transcript": return p.source ? (p.source.kind === "import" ? t("nav.sub.imported") : t("nav.sub.roughCut")) : "";
    case "selection": return p.runtime.shorts.count ? t("nav.sub.shorts", p.runtime.shorts.count) : "";
    case "smontage": return p.runtime.shorts.montages ? `${p.runtime.shorts.montages}/${p.runtime.shorts.count}` : "";
    default: return "";
  }
}

export interface StepItem extends Step { state: StepState; sub: string; dot: [string, string] }
export interface StepGroup { g: Phase; label: string; items: StepItem[] }

/** Les étapes du projet, par phase. */
export function stepGroups(p: Project): StepGroup[] {
  const phases = [...new Set(STEPS.map((s) => s.g))];
  return phases.map((g) => ({
    g,
    label: PHASES[g],
    items: STEPS.filter((s) => s.g === g).map((s) => {
      const state = p.status[s.id] ?? "todo";
      return { ...s, state, sub: stepSub(p, s.id), dot: DOT[state] };
    }),
  }));
}
