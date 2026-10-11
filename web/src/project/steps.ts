import { t } from "../i18n";
import type { ProjectSummary, StepState } from "./types";

export type Phase = "pre" | "tour" | "post" | "long" | "short" | "pack";

export interface Step { id: string; readonly label: string; g: Phase; ready: boolean }

/** Le libellé est traduit à chaque lecture : il suit la langue de l'interface. */
const step = (id: string, g: Phase, ready: boolean): Step => ({ id, g, ready, get label() { return t(`steps.${id}`); } });

/** Toutes les étapes du process ; `ready` : déjà portée dans l'interface (les autres sont masquées). */
export const ALL_STEPS: Step[] = [
  step("angle", "pre", true),
  step("titre", "pre", true),
  step("vignette", "pre", true),
  step("script", "pre", true),
  step("roast", "pre", true),
  step("tournage", "tour", true),
  step("derush", "post", true),
  step("transcript", "post", true),
  step("storyboard", "long", true),
  step("montage", "long", true),
  step("motion", "long", false),
  step("son", "long", false),
  step("selection", "short", true),
  step("smontage", "short", true),
  step("soustitres", "short", false),
  step("rendu", "pack", true),
  step("description", "pack", true),
  step("upload", "pack", true),
];

export const STEPS = ALL_STEPS.filter((s) => s.ready);

const phase = (g: Phase) => t(`steps.phases.${g}`);
export const PHASES: Readonly<Record<Phase, string>> = {
  get pre() { return phase("pre"); }, get tour() { return phase("tour"); }, get post() { return phase("post"); },
  get long() { return phase("long"); }, get short() { return phase("short"); }, get pack() { return phase("pack"); },
};

export function stepById(id: string): Step | undefined {
  return STEPS.find((s) => s.id === id);
}

type WithStatus = Pick<ProjectSummary, "status">;

const state = (p: WithStatus, id: string): StepState => p.status[id] ?? "todo";

/** « Script · Tournage », ou « Publiée ». */
export function stage(p: WithStatus): string {
  const cur = STEPS.filter((s) => state(p, s.id) === "cur").map((s) => s.label);
  if (cur.length) return cur.join(" · ");
  return ALL_STEPS.every((s) => state(p, s.id) === "done") ? t("steps.published") : "—";
}

/** L'étape où reprendre le projet. */
export function firstCur(p: WithStatus): string {
  return (STEPS.find((s) => state(p, s.id) === "cur") ?? STEPS.find((s) => state(p, s.id) === "todo") ?? STEPS[0]).id;
}

export function doneCount(p: WithStatus): number {
  return STEPS.filter((s) => ["done", "skip"].includes(state(p, s.id))).length;
}

/** Couleurs de la barre d'avancement d'un projet, une case par étape. */
export function bars(p: WithStatus): string[] {
  return STEPS.map((s) => {
    const st = state(p, s.id);
    return st === "done" ? "var(--ink)" : st === "cur" ? "var(--red)" : st === "skip" ? "var(--line-strong)" : "var(--hatch-a)";
  });
}

export const DURATIONS = ["< 5 min", "5–10 min", "10–20 min", "20–40 min", "40 min +"] as const;
