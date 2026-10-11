/** Ce que partagent les morceaux de l'écran Roasting : libellés et couleurs des notes. */
import { locale, t } from "../../../i18n";

const DECISIONS = ["tourne", "retouche", "reecris"];
const SEVERITIES = ["bloquant", "important", "detail"];
const SOURCES = ["angle", "titre", "vignette"];

/** Les libellés des ids du serveur (un id inconnu s'affiche tel quel). */
export const decisionLabel = (k: string): string => (DECISIONS.includes(k) ? t(`roast.decisions.${k}`) : k);
export const severityLabel = (k: string): string => (SEVERITIES.includes(k) ? t(`roast.severities.${k}`) : k);
export const sourceLabel = (k: string): string => (SOURCES.includes(k) ? t(`roast.sources.${k}`) : k);

/** Rouge sous 5, orange jusqu'à 7, vert au-delà. */
export function scoreColor(score: number): string {
  return score < 5 ? "var(--red)" : score < 7 ? "#E0912F" : "#2BA471";
}

/** 6,5 */
export const fmt = (score: number): string => score.toLocaleString(locale(), { maximumFractionDigits: 1 });

/** +1,5 / −0,5 / = */
export function delta(now: number, before: number | undefined): string | null {
  if (before == null) return null;
  const d = Math.round((now - before) * 10) / 10;
  return d > 0 ? `+${fmt(d)}` : d < 0 ? `−${fmt(-d)}` : "=";
}
