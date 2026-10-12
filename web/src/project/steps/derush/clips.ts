/**
 * Une timeline du dérush : une liste de bouts lus dans l'ordre, de rushes ({rush, in, out}) ou d'autres
 * timelines imbriquées ({tl, in, out}). Opérations sans état : chacune rend une nouvelle liste.
 * Les temps « t » sont ceux de la timeline.
 */
import type { DerushClip, DerushTimeline, TimelineClip } from "../../types";

/** Ce que les opérations demandent d'un bout. */
type Span = { id: string; in: number; out: number; rush?: string };

/** En dessous, un bout n'est pas gardé. */
const MIN = 0.04;
const r3 = (n: number) => Math.round(n * 1000) / 1000;

export const clipLen = (c: Span) => c.out - c.in;
export const newId = () => `c${Math.random().toString(36).slice(2, 10)}`;

/** Début de chaque bout sur la timeline. */
export function offsets(clips: Span[]): number[] {
  let a = 0;
  return clips.map((c) => { const o = a; a += clipLen(c); return o; });
}

/** Le bout sous `t` et l'instant correspondant dans son rush. */
export function clipAt<T extends Span>(clips: T[], t: number) {
  const o = offsets(clips);
  for (let i = clips.length - 1; i >= 0; i--) {
    if (o[i] <= t) return { i, c: clips[i], at: clips[i].in + Math.min(t - o[i], clipLen(clips[i])) };
  }
  return null;
}

/** L'instant `t` d'un rush sur la timeline : dans le bout qui le contient, sinon au début du bout suivant de ce rush. */
export function timeOf(clips: Span[], rush: string, t: number): number | null {
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
export function splitAt<T extends Span>(clips: T[], t: number): T[] {
  const o = offsets(clips);
  const i = clips.findIndex((c, k) => o[k] + MIN < t && t < o[k] + clipLen(c) - MIN);
  if (i < 0) return clips;
  const c = clips[i], at = r3(c.in + t - o[i]);
  return [...clips.slice(0, i), { ...c, out: at }, { ...c, id: newId(), in: at }, ...clips.slice(i + 1)];
}

/** Retire la plage [a, b] de la timeline (les bouts touchés sont recoupés). */
export function removeRange<T extends Span>(clips: T[], a: number, b: number): T[] {
  const o = offsets(clips), out: T[] = [];
  clips.forEach((c, k) => {
    const s = o[k], e = s + clipLen(c);
    if (e <= a || s >= b) { out.push(c); return; }
    if (a > s + MIN) out.push({ ...c, out: r3(c.in + a - s) });
    if (b < e - MIN) out.push({ ...c, id: a > s + MIN ? newId() : c.id, in: r3(c.in + b - s) });
  });
  return out;
}

/** Retire des plages d'un rush ([début, fin] en secondes du rush) de tous les bouts de ce rush. */
export function removeRushRanges<T extends Span>(clips: T[], rush: string, ranges: [number, number][]): T[] {
  const sorted = [...ranges].sort((x, y) => x[0] - y[0]);
  return clips.flatMap((c) => {
    if (c.rush !== rush) return [c];
    const parts: T[] = [];
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

export function remove<T extends Span>(clips: T[], ids: string[]): T[] {
  return clips.filter((c) => !ids.includes(c.id));
}

/** Déplace des bouts juste avant le bout `before` (à la fin s'il est nul). */
export function move<T extends Span>(clips: T[], ids: string[], before: string | null): T[] {
  const moving = clips.filter((c) => ids.includes(c.id)), rest = clips.filter((c) => !ids.includes(c.id));
  const at = before ? rest.findIndex((c) => c.id === before) : -1;
  return at < 0 ? [...rest, ...moving] : [...rest.slice(0, at), ...moving, ...rest.slice(at)];
}

/** Déplace le début (`in`) ou la fin (`out`) d'un bout dans son rush. */
export function trim<T extends Span>(clips: T[], id: string, side: "in" | "out", value: number, duration: number): T[] {
  return clips.map((c) => {
    if (c.id !== id) return c;
    return side === "in"
      ? { ...c, in: r3(Math.max(0, Math.min(value, c.out - MIN))) }
      : { ...c, out: r3(Math.min(duration, Math.max(value, c.in + MIN))) };
  });
}

/** Insère des bouts juste avant le bout `before` (à la fin s'il est nul). */
export function insert<T extends Span>(clips: T[], added: T[], before: string | null): T[] {
  const at = before ? clips.findIndex((c) => c.id === before) : -1;
  return at < 0 ? [...clips, ...added] : [...clips.slice(0, at), ...added, ...clips.slice(at)];
}

/**
 * Les bouts de rushes que lit une timeline, ses timelines imbriquées dépliées sur leur plage [in, out].
 * Chaque bout déplié garde l'id du bout imbriqué dont il vient (la sélection et le transcript le suivent).
 * `own` : les bouts d'une timeline tels qu'on les édite.
 */
export function flatten(own: (id: string) => TimelineClip[], id: string, seen: string[] = []): DerushClip[] {
  const out: DerushClip[] = [];
  for (const c of own(id)) {
    if (c.rush) { out.push(c as DerushClip); continue; }
    if (!c.tl || c.tl === id || seen.includes(c.tl)) continue;
    let cursor = 0;
    for (const sub of flatten(own, c.tl, [...seen, id])) {
      const len = clipLen(sub), a = Math.max(c.in, cursor), b = Math.min(c.out, cursor + len);
      if (b - a > 0.001) out.push({ id: c.id, rush: sub.rush, in: r3(sub.in + a - cursor), out: r3(sub.in + b - cursor) });
      cursor += len;
    }
  }
  return out;
}

/** La timeline `id` contient-elle `target`, même de loin ? (l'y imbriquer ferait une boucle) */
export function contains(timelines: DerushTimeline[], id: string, target: string, seen: string[] = []): boolean {
  if (id === target) return true;
  const tl = timelines.find((k) => k.id === id);
  return (tl?.clips ?? []).some((c) => !!c.tl && !seen.includes(c.tl) && contains(timelines, c.tl, target, [...seen, id]));
}

/** La sélection : des bouts, ou une plage de la timeline. */
export type Selection = { clips: string[] } | { range: [number, number] } | null;
