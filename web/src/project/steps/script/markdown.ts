/**
 * Lecture du script Markdown, partagée par les étapes Script et Tournage.
 * Les sections sont les titres `## Libellé — Titre`, numérotées s0, s1… dans l'ordre :
 * c'est le même découpage que le backend (projects/derush.py), auquel les plans se réfèrent.
 */

export interface Section {
  id: string;
  label: string;
  title: string;
  /** texte sous le titre, jusqu'à la section suivante */
  text: string;
  /** position du `##` dans le Markdown */
  offset: number;
}

const HEADING = /^##\s+(.*)$/gm;

export function sections(md: string): Section[] {
  const heads = [...md.matchAll(HEADING)];
  return heads.map((m, i) => {
    const head = m[1].trim();
    const sep = head.indexOf(" — ");
    const start = m.index + m[0].length;
    const end = i + 1 < heads.length ? heads[i + 1].index : md.length;
    return {
      id: `s${i}`,
      label: sep >= 0 ? head.slice(0, sep).trim() : head,
      title: sep >= 0 ? head.slice(sep + 3).trim() : "",
      text: md.slice(start, end).trim(),
      offset: m.index,
    };
  });
}

/** Les phrases dites d'une section : sans indications [VISUEL…], citations ni balises. */
export function splitSentences(text: string): string[] {
  return text
    .split(/\n+/)
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith("[") && !l.startsWith("#") && l !== "---")
    .map((l) => l.replace(/^>\s*/, "").replace(/^[-*]\s+/, "").replace(/\*\*/g, "").trim())
    .filter(Boolean)
    .flatMap((l) => l.split(/(?<=[.!?…])\s+/))
    .filter(Boolean);
}

/** Nombre de mots dits (même règle que runtime.script_words côté serveur). */
export function wordCount(md: string): number {
  return md
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith("[") && !l.startsWith("#") && l !== "---")
    .map((l) => l.replace(/^>\s*/, "").replace(/^[-*]\s+/, "").replace(/[*_`]/g, ""))
    .join(" ")
    .split(/\s+/)
    .filter(Boolean).length;
}
