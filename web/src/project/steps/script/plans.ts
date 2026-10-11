/** Les plans du script : types, ordre, et ce qu'on glisse dessus depuis le panneau Médias. */
import { t } from "../../../i18n";
import type { Plan, PlanMedia } from "../../types";
import { wordCount } from "./markdown";
import type { Block } from "./useScript";

/** Mêmes types que le serveur (script.PLAN_TYPES). */
export const PLAN_TYPES = ["Face caméra", "B-roll", "Écran", "Image", "Animation", "Texte à l'écran", "Son", "Insert",
  "Plan de coupe"] as const;
/** Ce qui se filme : on y précise le cadrage, et c'est la liste de l'étape Tournage. */
export const FILMED = ["Face caméra", "B-roll", "Insert", "Plan de coupe"];
export const FRAMES = ["Large", "Moyen", "Serré", "Très serré"];

// les types et cadrages sont des valeurs enregistrées : on ne traduit que leur affichage
const TYPE_KEYS: Record<string, string> = {
  "Face caméra": "faceCam", "B-roll": "broll", "Écran": "screen", "Image": "image", "Animation": "animation",
  "Texte à l'écran": "onscreenText", "Son": "sound", "Insert": "insert", "Plan de coupe": "cutaway",
};
const FRAME_KEYS: Record<string, string> = { "Large": "wide", "Moyen": "medium", "Serré": "close", "Très serré": "extremeClose" };
export const typeLabel = (type: string): string => (TYPE_KEYS[type] ? t(`script.planTypes.${TYPE_KEYS[type]}`) : type);
export const frameLabel = (frame: string): string => (FRAME_KEYS[frame] ? t(`script.frames.${FRAME_KEYS[frame]}`) : frame);

/** Une couleur par type : le surlignage du passage, le trait dans la marge. */
export const TYPE_COLORS: Record<string, string> = {
  "Face caméra": "#E5484D", "B-roll": "#3E8ED0", "Écran": "#8E6BD8", "Image": "#2BA471", "Animation": "#E0912F",
  "Texte à l'écran": "#B8A01A", "Son": "#12A3A3", "Insert": "#D85C9E", "Plan de coupe": "#7D7E7A",
};
export const colorOf = (type: string): string => TYPE_COLORS[type] ?? "#7D7E7A";

/** Le type MIME d'un média glissé depuis le panneau Médias. */
export const MEDIA_MIME = "application/x-studio-media";

export function newPlan(block: string | null, changes: Partial<Plan> = {}): Plan {
  return {
    id: "p" + crypto.randomUUID().replace(/-/g, "").slice(0, 8),
    block, end: null, q: "", type: "B-roll", frame: "", setup: "", note: "", media: [], on: false, ...changes,
  };
}

/** Le type d'un plan créé en déposant un fichier. */
export function typeOfMedia(m: PlanMedia): string {
  return m.kind === "Audio" ? "Son" : m.kind === "Images" ? "Image" : "B-roll";
}

export interface Section { id: string; index: number; label: string; title: string }

/** Les sections : les titres `## Libellé — Titre`. */
export function sectionsOf(blocks: Block[]): Section[] {
  return blocks.flatMap((b, index) => {
    const m = /^##\s+(.*)$/.exec(b.md);
    if (!m) return [];
    const head = m[1].trim(), sep = head.indexOf(" — ");
    return [{
      id: b.id, index,
      label: sep >= 0 ? head.slice(0, sep).trim() : head,
      title: sep >= 0 ? head.slice(sep + 3).trim() : "",
    }];
  });
}

/** Le temps estimé au début de chaque bloc (~150 mots par minute), et le nombre de mots. */
export function timing(blocks: Block[]): { times: Record<string, number>; words: number } {
  const times: Record<string, number> = {};
  let words = 0;
  for (const b of blocks) {
    times[b.id] = (words / 150) * 60;
    words += wordCount(b.md);
  }
  return { times, words };
}

/** Le texte d'un bloc sans Markdown, pour le citer. */
export function plain(md: string): string {
  return md.replace(/\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/[*_`>#]/g, "").replace(/\s+/g, " ").trim();
}

/** Les guillemets et apostrophes courbes comptent comme droits : Claude ne recopie pas toujours les mêmes. */
const loose = (t: string) => t.replace(/[’‘]/g, "'").replace(/[“”«»]/g, '"').toLowerCase();

/**
 * Où se trouve un passage cité par Claude : le paragraphe qui le contient, et le passage tel qu'il
 * est écrit (`q`) ; sans correspondance exacte, le paragraphe qui en contient le début (`q` vide :
 * tout le paragraphe). null s'il est introuvable.
 */
export function findPassage(blocks: Block[], passage: string): { block: string; q: string } | null {
  const needle = loose(plain(passage));
  const texts = blocks.filter((b) => !b.md.startsWith("#")).map((b) => ({ id: b.id, text: plain(b.md) }));
  for (const b of texts) {
    const at = loose(b.text).indexOf(needle);
    // (même longueur une fois normalisé : on reprend le texte du script)
    if (at >= 0) return { block: b.id, q: needle.length < b.text.length ? b.text.slice(at, at + needle.length) : "" };
  }
  const start = needle.slice(0, 40);
  const found = start.length >= 15 ? texts.find((b) => loose(b.text).includes(start)) : undefined;
  return found ? { block: found.id, q: "" } : null;
}

export interface OrderedPlan { plan: Plan; num: string; section: Section | null; blockIndex: number }

/** Les plans dans l'ordre du texte (les détachés à la fin), numérotés 01, 02… */
export function orderPlans(blocks: Block[], plans: Plan[]): OrderedPlan[] {
  const at = new Map(blocks.map((b, i) => [b.id, i]));
  const secs = sectionsOf(blocks);
  return plans
    .map((plan, i) => ({ plan, i, blockIndex: plan.block != null ? at.get(plan.block) ?? Infinity : Infinity }))
    .sort((a, b) => a.blockIndex - b.blockIndex || a.i - b.i)
    .map((o, n) => ({
      plan: o.plan, blockIndex: o.blockIndex, num: String(n + 1).padStart(2, "0"),
      section: secs.filter((s) => s.index <= o.blockIndex).at(-1) ?? null,
    }));
}
