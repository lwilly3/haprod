/**
 * Les opérations de montage sur la timeline (modifient la timeline passée).
 * L'A-roll est la piste principale : couper ou raccourcir un clip décale tout ce qui suit
 * (ripple), et les éléments posés au-dessus suivent leur passage, comme dans Resolve.
 */
import { clipStarts, newId, totalOf, type AvailableMedia, type Broll, type Sound, type Timeline, type Track } from "./types";

const MIN = 0.1;

/**
 * Décale de `delta` tout ce qui commence à partir de `from` (ancienne position). Un delta négatif
 * retire le passage [from + delta, from[ : ce qui y commençait disparaît.
 */
export function ripple(tl: Timeline, from: number, delta: number): void {
  if (!delta) return;
  const keep = (at: number) => delta >= 0 || at < from + delta || at >= from;
  const shift = (at: number) => (at >= from ? round(at + delta) : at);
  for (const track of ["zooms", "broll", "motion", "audio", "texts"] as const) {
    const list = tl[track] as { at: number }[];
    (tl[track] as { at: number }[]) = list.filter((x) => keep(x.at)).map((x) => ({ ...x, at: shift(x.at) }));
  }
  tl.markers = tl.markers.filter((m) => keep(m.t)).map((m) => ({ ...m, t: shift(m.t) }));
}

/** Coupe l'A-roll à l'instant `t` de la timeline ; rend l'id du nouveau clip (ou null). */
export function bladeAroll(tl: Timeline, t: number): string | null {
  const starts = clipStarts(tl);
  const i = tl.aroll.findIndex((c, k) => t > starts[k] + MIN && t < starts[k] + c.out - c.in - MIN);
  if (i < 0) return null;
  const c = tl.aroll[i], at = c.in + (t - starts[i]);
  const id = newId(tl, "a");
  // la seconde moitié garde le média et le volume du clip coupé
  tl.aroll.splice(i, 1, { ...c, out: round(at) }, { ...c, id, in: round(at), transition: null });
  return id;
}

/**
 * Insère dans l'A-roll, à l'instant `t`, un clip d'un autre média (`in` / `out` : temps dans ce média) : coupe à t
 * (ou sur la coupe toute proche), puis décale tout ce qui suit de la durée du clip. Un B-roll, un son ou un zoom à
 * cheval sur t est coupé en deux : sa suite reprend après le clip. Rend l'id du clip et l'endroit où il commence.
 */
export function insertAroll(tl: Timeline, t: number, clip: { src: string; in: number; out: number }): { id: string; at: number } {
  let starts = clipStarts(tl);
  const total = totalOf(tl);
  let i = starts.findIndex((s) => Math.abs(s - t) <= MIN);
  if (i < 0 && t >= total - MIN) i = tl.aroll.length;
  if (i < 0) {
    bladeAroll(tl, t);
    starts = clipStarts(tl);
    i = starts.findIndex((s) => Math.abs(s - t) <= 0.01);
    if (i < 0) i = tl.aroll.length;
  }
  const at = i < tl.aroll.length ? starts[i] : totalOf(tl);
  const len = round(clip.out - clip.in);
  for (const track of ["zooms", "broll", "audio"] as const) {
    const ids = (tl[track] as { id: string }[]).map((x) => x.id);
    for (const id of ids) bladeItem(tl, track, id, at);
  }
  ripple(tl, at, len);
  // la transition éventuelle était avec l'ancien voisin : le clip inséré arrive et repart en coupe franche
  if (tl.aroll[i]) tl.aroll[i].transition = null;
  const id = newId(tl, "a");
  tl.aroll.splice(i, 0, { id, src: clip.src, in: round(clip.in), out: round(clip.out), transition: null });
  return { id, at };
}

/** Ajoute un média au-dessus de l'A-roll à l'instant `at` : un B-roll (muet), une musique ou un son. */
export function addMedia(tl: Timeline, m: AvailableMedia, at: number): { track: "broll" | "audio"; id: string } {
  const total = totalOf(tl);
  const visual = m.category === "broll" || m.category === "rush";
  const len = Math.min(m.duration ?? 4, visual ? 4 : m.category === "musique" ? Math.max(5, total - at) : 3);
  if (visual) {
    const id = newId(tl, "b");
    tl.broll.push({ id, src: m.src, at: round(at), in: 0, out: round(len) });
    return { track: "broll", id };
  }
  const id = newId(tl, "s");
  tl.audio.push({ id, src: m.src, at: round(at), in: 0, out: round(len), gain_db: m.gain_db ?? (m.category === "musique" ? -22 : -10),
    role: m.category === "musique" ? "music" : "sfx" });
  return { track: "audio", id };
}

/** Ajoute un texte à l'instant `at` : 3 s, en bas de l'image, légèrement penché. Rend son id. */
export function addText(tl: Timeline, at: number): string {
  const id = newId(tl, "t");
  tl.texts.push({ id, at: round(at), dur: round(Math.max(0.5, Math.min(3, totalOf(tl) - at))), text: "",
    x: 0.5, y: 0.8, size: 0.075, color: "#FFFFFF", angle: -4 });
  return id;
}

/** Une vidéo, qu'on peut insérer dans l'A-roll (pas un son ni une image). */
export const isVideo = (m: AvailableMedia) => (m.category === "broll" || m.category === "rush") && /\.(mp4|mov|m4v|mkv|webm|avi|mts)$/i.test(m.src);

/** Le type MIME d'un média glissé depuis l'inspecteur vers la timeline. */
export const MEDIA_DRAG = "application/x-montage-media";

/** Coupe un élément posé (B-roll, son, zoom, texte) à l'instant `t`. */
export function bladeItem(tl: Timeline, track: Track, id: string, t: number): string | null {
  if (track === "aroll") return bladeAroll(tl, t);
  if (track === "broll" || track === "audio") {
    const list = tl[track] as (Broll | Sound)[];
    const i = list.findIndex((x) => x.id === id);
    const x = list[i];
    if (!x || t <= x.at + MIN || t >= x.at + x.out - x.in - MIN) return null;
    const cut = x.in + (t - x.at), nid = newId(tl, track === "broll" ? "b" : "s");
    list.splice(i, 1, { ...x, out: round(cut) }, { ...x, id: nid, at: round(t), in: round(cut) });
    return nid;
  }
  if (track === "zooms" || track === "texts") {
    const list = tl[track] as { id: string; at: number; dur: number }[];
    const i = list.findIndex((x) => x.id === id), z = list[i];
    if (!z || t <= z.at + MIN || t >= z.at + z.dur - MIN) return null;
    const nid = newId(tl, track === "zooms" ? "z" : "t");
    list.splice(i, 1, { ...z, dur: round(t - z.at) }, { ...z, id: nid, at: round(t), dur: round(z.at + z.dur - t) });
    return nid;
  }
  return null;
}

/** Supprime un élément ; un clip de l'A-roll est retiré avec raccord (ripple). */
export function remove(tl: Timeline, track: Track, id: string): void {
  if (track === "aroll") {
    const starts = clipStarts(tl), i = tl.aroll.findIndex((c) => c.id === id);
    if (i < 0 || tl.aroll.length < 2) return;
    const c = tl.aroll[i], len = c.out - c.in;
    tl.aroll.splice(i, 1);
    ripple(tl, starts[i] + len, -len);
    return;
  }
  (tl[track] as { id: string }[]) = (tl[track] as { id: string }[]).filter((x) => x.id !== id);
  // les sons d'un motion partent avec lui
  if (track === "motion") tl.audio = tl.audio.filter((s) => s.motion !== id);
}

/** Change les bornes d'un clip de l'A-roll (dans son média : `limit`, sa durée), avec ripple. */
export function trimAroll(tl: Timeline, id: string, edge: "in" | "out", value: number, limit: number): void {
  const starts = clipStarts(tl), i = tl.aroll.findIndex((c) => c.id === id);
  const c = tl.aroll[i];
  if (!c) return;
  const before = c.out - c.in;
  if (edge === "in") c.in = round(Math.max(0, Math.min(value, c.out - MIN)));
  else c.out = round(Math.min(limit || Infinity, Math.max(value, c.in + MIN)));
  ripple(tl, starts[i] + before, c.out - c.in - before);
}

export const round = (n: number) => Math.round(n * 1000) / 1000;

/** L'instant `n` images plus loin (ou plus tôt) que `t`, calé sur une image de la source. */
export const frameStep = (t: number, n: number, fps: number) => round((Math.round(t * fps) + n) / fps);
