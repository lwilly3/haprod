/**
 * La bibliothèque des transitions (backend projects/transitions.py) : les transitions `xfade` de ffmpeg.
 * La galerie montre leur démo rendue par ffmpeg (exacte) ; l'aperçu du montage les imite en CSS,
 * image par image, avec les mêmes formules (approchées pour les effets que le CSS ne sait pas faire).
 */
import type { CSSProperties } from "vue";
import { t } from "../i18n";
import { api } from "./api";

/** Une transition dans la timeline : {fx, dur}, null pour une coupe franche. */
export interface Fx { fx: string; dur: number }
export interface FxCatalog { items: { fx: string; group: string }[]; groups: string[]; dur: [number, number]; default_dur: number }

let catalog: Promise<FxCatalog> | null = null;
export function loadTransitions(): Promise<FxCatalog> {
  catalog ??= api<FxCatalog>("/api/projects/library/transitions").catch((e) => { catalog = null; throw e; });
  return catalog;
}
export const demoUrl = (fx: string) => `/api/projects/library/transitions/${fx}.mp4`;
export const fxName = (fx: string) => t(`transitions.fx.${fx}`);
export const fxLabel = (x: Fx | null | undefined) => (x ? `${fxName(x.fx)} · ${x.dur.toFixed(1).replace(".", ",")} s` : t("transitions.cut"));

// --- l'aperçu en CSS -------------------------------------------------------------------------

/**
 * L'état d'une transition à l'avancement q (0 → 1), à la façon de xfade(A, B) : `a` le plan qui s'en va,
 * `b` celui qui arrive, `veil` un aplat (noir, blanc) entre les deux. `mode` : "enter" (A est ce qui est
 * dessous : seul B est dessiné), "exit" (B est ce qui est dessous : seul A est dessiné), "pair" (les deux).
 */
export interface FxFrame { a: CSSProperties; b: CSSProperties; veil?: CSSProperties }
type Mode = "enter" | "exit" | "pair";

const pc = (x: number) => `${(x * 100).toFixed(3)}%`;
const clamp = (x: number) => Math.max(0, Math.min(1, x));
/** clip-path du rectangle rogné de (haut, droite, bas, gauche), en fraction */
const inset = (tp: number, r: number, bt: number, l: number) => `inset(${pc(tp)} ${pc(r)} ${pc(bt)} ${pc(l)})`;
/** tout l'écran sauf ce rectangle */
const outside = (tp: number, r: number, bt: number, l: number) =>
  `polygon(evenodd, 0 0, 100% 0, 100% 100%, 0 100%, 0 0, ${pc(l)} ${pc(tp)}, ${pc(1 - r)} ${pc(tp)}, ${pc(1 - r)} ${pc(1 - bt)}, ${pc(l)} ${pc(1 - bt)}, ${pc(l)} ${pc(tp)})`;
const mask = (image: string): CSSProperties => ({ maskImage: image, WebkitMaskImage: image } as CSSProperties);
/** dégradé de masque : transparent jusqu'à `from`, opaque dès `to` (dans le sens `dir`) */
const ramp = (dir: string, from: number, to: number, invert = false) =>
  mask(`linear-gradient(${dir}, ${invert ? "black" : "transparent"} ${pc(from)}, ${invert ? "transparent" : "black"} ${pc(to)})`);
const smooth = (x: number) => { const k = clamp(x); return k * k * (3 - 2 * k); };
/** un masque échantillonné : l'opacité w(x) pour x de 0 à 1 le long du dégradé */
const stops = (w: (x: number) => number, n = 16) =>
  Array.from({ length: n + 1 }, (_, i) => `rgba(0,0,0,${w(i / n).toFixed(3)}) ${pc(i / n)}`).join(", ");
const move = (x: number, y: number): CSSProperties => ({ transform: `translate(${pc(x)}, ${pc(y)})` });

/** sens des glissements : d'où arrive le nouveau plan (en fraction d'écran) */
const DIRS: Record<string, [number, number]> = { left: [1, 0], right: [-1, 0], up: [0, 1], down: [0, -1] };
/** balayages nets : la zone du nouveau plan (inset) à l'avancement q */
const WIPES: Record<string, (q: number) => [number, number, number, number]> = {
  left: (q) => [0, 0, 0, 1 - q], right: (q) => [0, 1 - q, 0, 0], up: (q) => [1 - q, 0, 0, 0], down: (q) => [0, 0, 1 - q, 0],
};
/** les approchées : lamelles et vent deviennent des balayages, pixels et grain des fondus */
const LIKE: Record<string, string> = {
  hlslice: "wipeleft", hrslice: "wiperight", vuslice: "wipeup", vdslice: "wipedown",
  hlwind: "wipeleft", hrwind: "wiperight", vuwind: "wipeup", vdwind: "wipedown",
  dissolve: "fade", distance: "fade", pixelize: "hblur",
};
export const approximate = (fx: string) => fx in LIKE;

function wipe(region: [number, number, number, number]): FxFrame {
  const [tp, r, bt, l] = region;
  return { b: { clipPath: inset(tp, r, bt, l) }, a: { clipPath: outside(tp, r, bt, l) } };
}

/** passage par une couleur : A s'efface dans l'aplat, puis B en sort ; en sortie l'aplat s'efface sur ce qui est dessous */
function dip(color: string, q: number, mode: Mode): FxFrame {
  const first = q < 0.5;
  return {
    a: { opacity: first ? 1 : 0 }, b: { opacity: first ? 0 : 2 * q - 1 },
    veil: { background: color, opacity: first ? 2 * q : mode === "exit" ? 2 - 2 * q : 1 },
  };
}

/** passage au noir par une forme (iris, cadre) qui se ferme puis s'ouvre */
function crop(q: number, round: boolean): FxFrame {
  const r = Math.abs(1 - 2 * q);
  const hole = round
    ? mask(`radial-gradient(circle farthest-corner at 50% 50%, black ${pc(r)}, transparent ${pc(r)})`)
    : { clipPath: inset((1 - r) / 2, (1 - r) / 2, (1 - r) / 2, (1 - r) / 2) };
  const veil = round
    ? { background: "#000", ...mask(`radial-gradient(circle farthest-corner at 50% 50%, transparent ${pc(r)}, black ${pc(r)})`) }
    : { background: "#000", clipPath: outside((1 - r) / 2, (1 - r) / 2, (1 - r) / 2, (1 - r) / 2) };
  return q < 0.5 ? { a: hole, b: { opacity: 0 }, veil } : { a: { opacity: 0 }, b: hole, veil };
}

/** les transitions douces mélangent A et B : à deux, A reste entier sous B */
const SOFT = new Set(["fade", "fadegrays", "hblur", "zoomin", "smoothleft", "smoothright", "smoothup", "smoothdown",
  "diagtl", "diagtr", "diagbl", "diagbr", "circleopen", "circleclose", "vertopen", "vertclose", "horzopen", "horzclose"]);

function frame(fx: string, q: number, mode: Mode): FxFrame {
  fx = LIKE[fx] ?? fx;
  const mix = (extra: (side: "a" | "b") => CSSProperties = () => ({})): FxFrame =>
    ({ a: { opacity: 1 - q, ...extra("a") }, b: { opacity: q, ...extra("b") } });
  if (fx === "fade") return mix();
  if (fx === "fadegrays") return mix((s) => ({ filter: `grayscale(${clamp(s === "a" ? 2 * q : 2 - 2 * q)})` }));
  if (fx === "hblur") return mix(() => ({ filter: `blur(${(Math.sin(Math.PI * q) * 1.2).toFixed(3)}vw)` }));
  if (fx === "zoomin") return mix((s) => (s === "a" ? { transform: `scale(${1 + 1.5 * clamp(2 * q)})` } : {}));
  if (fx === "fadeblack") return dip("#000", q, mode);
  if (fx === "fadewhite") return dip("#fff", q, mode);
  if (fx === "circlecrop") return crop(q, true);
  if (fx === "rectcrop") return crop(q, false);
  const m = /^(wipe|slide|cover|reveal|smooth)(left|right|up|down)$/.exec(fx);
  if (m) {
    const [, kind, side] = m;
    const [dx, dy] = DIRS[side];
    if (kind === "wipe") return wipe(WIPES[side](q));
    if (kind === "slide") return { a: move(-dx * q, -dy * q), b: move(dx * (1 - q), dy * (1 - q)) };
    // le plan qui glisse cache ce qu'il recouvre (en sortie : il emporte la vue sur ce qui est dessous)
    if (kind === "cover") return { a: wipe(WIPES[side](q)).a, b: move(dx * (1 - q), dy * (1 - q)) };
    if (kind === "reveal") return { a: move(-dx * q, -dy * q), b: wipe(WIPES[side](q)).b };
    const dir = ({ left: "to right", right: "to left", up: "to bottom", down: "to top" } as Record<string, string>)[side];
    return { b: ramp(dir, 1 - 2 * q, 2 - 2 * q), a: ramp(dir, 1 - 2 * q, 2 - 2 * q, true) };
  }
  const corner = /^(diag|wipe)(tl|tr|bl|br)$/.exec(fx);
  if (corner) {
    const [, kind, c] = corner;
    if (kind === "diag") {
      // le nouveau plan arrive du coin opposé
      const dir = ({ tl: "to bottom right", tr: "to bottom left", bl: "to top right", br: "to top left" } as Record<string, string>)[c];
      return { b: ramp(dir, 1 - 2 * q, 2 - 2 * q), a: ramp(dir, 1 - 2 * q, 2 - 2 * q, true) };
    }
    // l'ancien plan se replie vers son coin
    const top = c[0] === "t", left = c[1] === "l";
    const r: [number, number, number, number] = [top ? 0 : q, left ? q : 0, top ? q : 0, left ? 0 : q];
    return { a: { clipPath: inset(...r) }, b: { clipPath: outside(...r) } };
  }
  if (fx === "radial") {
    const deg = q * 360;
    return {
      b: mask(`conic-gradient(from 0deg at 50% 50%, black ${Math.max(0, deg - 8)}deg, transparent ${deg + 8}deg)`),
      a: mask(`conic-gradient(from 0deg at 50% 50%, transparent ${Math.max(0, deg - 8)}deg, black ${deg + 8}deg)`),
    };
  }
  if (fx === "circleopen" || fx === "circleclose") {
    // part de B à la distance r du centre (1 = le coin), comme xfade
    const open = fx === "circleopen";
    const w = (r: number) => (open ? 1 - smooth(r + 1.5 - 3 * q) : smooth(r - 1.5 + 3 * q));
    return { b: mask(`radial-gradient(circle farthest-corner at 50% 50%, ${stops(w)})`),
      a: mask(`radial-gradient(circle farthest-corner at 50% 50%, ${stops((r) => 1 - w(r))})`) };
  }
  const band = /^(vert|horz)(open|close)$/.exec(fx);
  if (band) {
    // part de B à la distance d de l'axe central (1 = le bord)
    const dir = band[1] === "vert" ? "to right" : "to bottom";
    const w = band[2] === "open" ? (d: number) => smooth(2 * q - d) : (d: number) => 1 - smooth(2 - 2 * q - d);
    const across = (f: (d: number) => number) => (x: number) => f(Math.abs(2 * x - 1));
    return { b: mask(`linear-gradient(${dir}, ${stops(across(w))})`), a: mask(`linear-gradient(${dir}, ${stops(across((d) => 1 - w(d)))})`) };
  }
  if (fx === "squeezeh") {
    const top = q / 2;
    return { a: { transform: `scaleY(${1 - q})` },
      b: mask(`linear-gradient(to bottom, black ${pc(top)}, transparent ${pc(top)}, transparent ${pc(1 - top)}, black ${pc(1 - top)})`) };
  }
  return mix();
}

export function fxFrame(fx: string, q: number, mode: Mode): FxFrame {
  const f = frame(fx, clamp(q), mode);
  // à deux, une transition douce pose B sur A entier
  if (mode === "pair" && SOFT.has(LIKE[fx] ?? fx)) f.a = {};
  return f;
}

// --- les plans d'une piste à l'instant t -----------------------------------------------------

export interface Span { id: string; at: number; len: number; enter?: Fx | null; exit?: Fx | null }
/**
 * Un plan visible à l'instant t : son style, son aplat (sous lui, au-dessus quand il sort : `over`), et son temps
 * propre (s depuis son `at`, négatif avant).
 */
export interface Layer { id: string; local: number; style: CSSProperties; veil?: CSSProperties; over?: boolean }

/**
 * Comme le rendu (render.overlay_groups) : un plan collé au précédent (à 0,05 s près) et qui a une entrée
 * s'enchaîne avec lui, centré sur la coupe ; sinon l'entrée et la sortie se jouent dans le plan, depuis et
 * vers ce qui est dessous. Rend les plans visibles à t, du dessous au dessus.
 */
export function layersAt(items: Span[], t: number): Layer[] {
  const s = [...items].sort((x, y) => x.at - y.at);
  const joins = s.map((x, i) => {
    const prev = s[i - 1];
    if (!prev || !x.enter || Math.abs(x.at - (prev.at + prev.len)) > 0.05) return null;
    return { fx: x.enter.fx, dur: Math.min(x.enter.dur, x.len, prev.len) };
  });
  const out: Layer[] = [];
  s.forEach((x, i) => {
    const before = joins[i], after = joins[i + 1];
    const start = before ? x.at - before.dur / 2 : x.at;
    const end = x.at + x.len + (after ? after.dur / 2 : 0);
    if (t < start || t >= end) return;
    const layer: Layer = { id: x.id, local: t - x.at, style: {} };
    const enter = !before && x.enter ? Math.min(x.enter.dur, x.len / 2) : 0;
    const exit = !after && x.exit ? Math.min(x.exit.dur, x.len / 2) : 0;
    if (before && t < x.at + before.dur / 2) {
      const f = fxFrame(before.fx, (t - start) / before.dur, "pair");
      Object.assign(layer, { style: f.b, veil: f.veil });
    } else if (after && t >= x.at + x.len - after.dur / 2) {
      layer.style = fxFrame(after.fx, (t - (x.at + x.len - after.dur / 2)) / after.dur, "pair").a;
    } else if (enter && t < x.at + enter) {
      const f = fxFrame(x.enter!.fx, (t - x.at) / enter, "enter");
      Object.assign(layer, { style: f.b, veil: f.veil });
    } else if (exit && t >= end - exit) {
      const f = fxFrame(x.exit!.fx, (t - (end - exit)) / exit, "exit");
      Object.assign(layer, { style: f.a, veil: f.veil, over: true });
    }
    out.push(layer);
  });
  return out;
}
