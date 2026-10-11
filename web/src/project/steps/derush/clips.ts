/**
 * La timeline du dérush : une liste de bouts de rushes ({rush, in, out}) lus dans l'ordre.
 * Opérations sans état : chacune rend une nouvelle liste. Les temps « t » sont ceux de la timeline.
 */
import type { DerushClip } from "../../types";

/** En dessous, un bout n'est pas gardé. */
const MIN = 0.04;
const r3 = (n: number) => Math.round(n * 1000) / 1000;

export const clipLen = (c: DerushClip) => c.out - c.in;
export const newId = () => `c${Math.random().toString(36).slice(2, 10)}`;

/** Début de chaque bout sur la timeline. */
export function offsets(clips: DerushClip[]): number[] {
  let a = 0;
  return clips.map((c) => { const o = a; a += clipLen(c); return o; });
}

/** Le bout sous `t` et l'instant correspondant dans son rush. */
export function clipAt(clips: DerushClip[], t: number) {
  const o = offsets(clips);
  for (let i = clips.length - 1; i >= 0; i--) {
    if (o[i] <= t) return { i, c: clips[i], at: clips[i].in + Math.min(t - o[i], clipLen(clips[i])) };
  }
  return null;
}

/** L'instant `t` d'un rush sur la timeline : dans le bout qui le contient, sinon au début du bout suivant de ce rush. */
export function timeOf(clips: DerushClip[], rush: string, t: number): number | null {
  const o = offsets(clips);
  let next: number | null = null, gap = Infinity;
  clips.forEach((c, k) => {
    if (c.rush !== rush) return;
    if (c.in <= t && t < c.out) { next = o[k] + t - c.in; gap = -1; }
    else if (c.in > t && c.in - t < gap) { next = o[k]; gap = c.in - t; }
  });
  return next;
}

/** Coupe le bout sous `t` en deux. */
export function splitAt(clips: DerushClip[], t: number): DerushClip[] {
  const o = offsets(clips);
  const i = clips.findIndex((c, k) => o[k] + MIN < t && t < o[k] + clipLen(c) - MIN);
  if (i < 0) return clips;
  const c = clips[i], at = r3(c.in + t - o[i]);
  return [...clips.slice(0, i), { ...c, out: at }, { ...c, id: newId(), in: at }, ...clips.slice(i + 1)];
}

/** Retire la plage [a, b] de la timeline (les bouts touchés sont recoupés). */
export function removeRange(clips: DerushClip[], a: number, b: number): DerushClip[] {
  const o = offsets(clips), out: DerushClip[] = [];
  clips.forEach((c, k) => {
    const s = o[k], e = s + clipLen(c);
    if (e <= a || s >= b) { out.push(c); return; }
    if (a > s + MIN) out.push({ ...c, out: r3(c.in + a - s) });
    if (b < e - MIN) out.push({ ...c, id: a > s + MIN ? newId() : c.id, in: r3(c.in + b - s) });
  });
  return out;
}

/** Retire des plages d'un rush ([début, fin] en secondes du rush) de tous les bouts de ce rush. */
export function removeRushRanges(clips: DerushClip[], rush: string, ranges: [number, number][]): DerushClip[] {
  const sorted = [...ranges].sort((x, y) => x[0] - y[0]);
  return clips.flatMap((c) => {
    if (c.rush !== rush) return [c];
    const parts: DerushClip[] = [];
    let from = c.in;
    for (const [a, b] of sorted) {
      if (b <= from || a >= c.out) continue;
      if (a - from > MIN) parts.push({ ...c, id: parts.length ? newId() : c.id, in: r3(from), out: r3(a) });
      from = Math.max(from, b);
    }
    if (c.out - from > MIN) parts.push({ ...c, id: parts.length ? newId() : c.id, in: r3(from), out: c.out });
    return parts;
  });
}

export function remove(clips: DerushClip[], ids: string[]): DerushClip[] {
  return clips.filter((c) => !ids.includes(c.id));
}

/** Déplace des bouts juste avant le bout `before` (à la fin s'il est nul). */
export function move(clips: DerushClip[], ids: string[], before: string | null): DerushClip[] {
  const moving = clips.filter((c) => ids.includes(c.id)), rest = clips.filter((c) => !ids.includes(c.id));
  const at = before ? rest.findIndex((c) => c.id === before) : -1;
  return at < 0 ? [...rest, ...moving] : [...rest.slice(0, at), ...moving, ...rest.slice(at)];
}

/** Déplace le début (`in`) ou la fin (`out`) d'un bout dans son rush. */
export function trim(clips: DerushClip[], id: string, side: "in" | "out", value: number, duration: number): DerushClip[] {
  return clips.map((c) => {
    if (c.id !== id) return c;
    return side === "in"
      ? { ...c, in: r3(Math.max(0, Math.min(value, c.out - MIN))) }
      : { ...c, out: r3(Math.min(duration, Math.max(value, c.in + MIN))) };
  });
}

/** La sélection : des bouts, ou une plage de la timeline. */
export type Selection = { clips: string[] } | { range: [number, number] } | null;
