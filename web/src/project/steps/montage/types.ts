/** Le montage de la vidéo longue (backend projects/montage.py). Temps de la timeline en secondes. */
import { t } from "../../../i18n";
import type { Fx } from "../../../lib/transitions";

/**
 * transition : avec le clip précédent (null : coupe franche) ; src : absent pour la vidéo source, sinon un autre
 * média inséré dans l'A-roll (un extrait, une archive), qui passe avec son propre son ; gain_db : son volume
 * (absent : 0 dB)
 */
export interface ArollClip { id: string; src?: string; in: number; out: number; transition: Fx | null; gain_db?: number }
/**
 * Le style d'un zoom (backend montage.ZOOM_STYLES) : smooth monte et descend en ZOOM_RAMP (adouci), cut saute
 * d'un coup (aparté face cam), slow pousse lentement sur toute sa durée puis revient d'un coup.
 */
export type ZoomStyle = "smooth" | "cut" | "slow";
export const ZOOM_STYLES: ZoomStyle[] = ["smooth", "cut", "slow"];
export interface Zoom { id: string; at: number; dur: number; scale: number; x: number; y: number; style?: ZoomStyle }
const ZOOM_RAMP = 0.4;
/** Où en est un zoom à l'instant `t`, de 0 à 1 (backend montage.zoom_amount, et le rendu). */
export function zoomAmount(z: { at: number; dur: number; style?: ZoomStyle }, t: number): number {
  const a = z.at, b = z.at + z.dur;
  if (t < a || t >= b) return 0;
  const style = z.style ?? "smooth";
  const ramp = Math.min(ZOOM_RAMP, z.dur / 3);
  const [rise, fall] = style === "cut" ? [0, 0] : style === "slow" ? [z.dur, 0] : [ramp, ramp];
  const k = Math.min(1, rise ? (t - a) / rise : 1, fall ? (b - t) / fall : 1);
  // smooth : adouci (smoothstep) ; slow : vitesse constante, comme une poussée de caméra
  return style === "slow" ? k : k * k * (3 - 2 * k);
}
/** enter / exit : la transition depuis et vers ce qui est dessous (absente : coupe franche) */
export interface Broll { id: string; src: string; at: number; in: number; out: number; enter?: Fx | null; exit?: Fx | null }
export interface Motion { id: string; at: number; dur: number; title: string; kind: string; idea: string; enter?: Fx | null; exit?: Fx | null }
/** `motion` : le motion dont le son fait le sound design ; il le suit quand on le déplace */
export interface Sound { id: string; src: string; at: number; in: number; out: number; gain_db: number; role: "sfx" | "music"; motion?: string }
/**
 * Un texte écrit à la main, à l'écran (corriger un mot mal audible) : x, y le centre du texte (fraction de l'image),
 * size la hauteur de la police (fraction de la hauteur de l'image), angle en degrés.
 */
export interface TextNote { id: string; at: number; dur: number; text: string; x: number; y: number; size: number; color: string; angle: number }
export interface Marker { id: string; t: number; text: string; kind: "chapter" | "note"; by: "user" | "ai"; done: boolean }

export interface Timeline {
  aroll: ArollClip[]; zooms: Zoom[]; broll: Broll[]; motion: Motion[]; audio: Sound[]; texts: TextNote[]; markers: Marker[];
}
export type Track = keyof Timeline;

export interface MotionState { html: string | null; render: string; progress: number; error: string | null }

export interface MontageMessage {
  role: "user" | "ai"; text: string; at: number; tools?: string[]; changed?: boolean;
  selection?: Selection | null;
  /** l'image où le client a mis en pause pour en parler (temps de la timeline) */
  frame?: number | null;
  /** sa capture telle qu'il la voyait (chemin relatif au projet) */
  image?: string | null;
}

/** L'image en pause dont le client parle : son temps dans la timeline, et la capture de l'aperçu (data URL JPEG). */
export interface Shot { t: number; image: string | null }

/** Une transition de la timeline : celle d'un clip de l'A-roll avec le précédent, l'entrée ou la sortie d'un plan. */
export type FxEnd = "transition" | "enter" | "exit";
/**
 * Ce que le client a sélectionné dans la timeline : un élément (ou l'une de ses transitions, `fx`), ou une plage
 * de temps.
 */
export type Selection = { item: { track: Track; id: string; fx?: FxEnd } } | { range: [number, number] };

export interface MontageView {
  timeline: Timeline;
  /** l'empreinte de cette version, renvoyée avec une retouche */
  rev: string;
  source: { url: string; name: string; duration: number; width: number; height: number; fps: number } | null;
  analysis: {
    peaks: string | null; peaks_rate: number; pending: boolean;
    filmstrip: { url: string; step: number; cols: number; height: number; width: number } | null;
  };
  media: Record<string, { name: string; duration: number | null; url: string }>;
  motions: Record<string, MotionState>;
  can_undo: boolean;
  export: { rel: string; name: string; exists: boolean };
  /** les demandes faites à Daryl, dans l'ordre : chacune a sa conversation ; plusieurs sont traitées à la fois */
  tasks: MontageTask[];
  /** Daryl traite une demande */
  busy: boolean;
  /** l'utilisation de l'abonnement Claude, la dernière connue */
  usage: Record<string, number> | null;
}

/** Une demande à Daryl et sa conversation : en file, en cours, puis finie. */
export interface MontageTask {
  id: string; status: "queued" | "running" | "done" | "error" | "cancelled";
  messages: MontageMessage[]; activity: string | null; error: string | null;
}

export type BeatType = "motion" | "zoom" | "broll" | "transition";
export const BEAT_TYPES: BeatType[] = ["motion", "zoom", "broll", "transition"];
/** Un beat du storyboard (backend projects/storyboard.py) : ce qu'on montre, et quand. */
export interface Beat {
  id: string; type: BeatType; at: number; dur: number; anchor: string; until: string; says: string; show: string;
  kind: string; place: string; motion: { enter: string; hold: string; exit: string }; sfx: string;
  ref: string | null; why: string; on: boolean;
  /** l'animation du kit qui sert de base (« exemple-arbre.html »), "" pour du sur mesure */
  anim?: string;
  /** script : un plan d'animation du script (plan = son id) ; daryl : ajouté par Daryl ; user : posé à la main */
  origin?: "script" | "daryl" | "user"; plan?: string | null;
  /** zoom : grossissement et décalage du centre (fraction de l'image) */
  zoom?: { scale: number; x: number; y: number; style?: ZoomStyle };
  /** broll : le média (vide : à trouver), la recherche toute prête, et pour une vidéo la seconde où le plan commence */
  src?: string; search?: string; start?: number;
  /** motion : les images et vidéos à intégrer à l'animation (facultatives) */
  images?: string[];
  /** motion et broll : les transitions d'entrée et de sortie au montage */
  enter?: Fx | null; exit?: Fx | null;
}
const IMAGE = /\.(png|jpe?g|webp|gif|svg)$/i;
export const isImage = (src?: string) => !!src && IMAGE.test(src);
/** Les images et vidéos d'un motion (`src` : l'ancienne forme, une seule image). */
export const beatImages = (b: Beat): string[] => b.images ?? (b.type === "motion" && isImage(b.src) ? [b.src!] : []);
/** L'image montrée sur la slide d'un beat : celle d'un B-roll, la première d'un motion. */
export const slideImage = (b: Beat): string | undefined => b.type === "motion" ? beatImages(b).find(isImage) : isImage(b.src) ? b.src : undefined;
/** Le beat passe par une animation écrite par Daryl ; sinon (zoom, B-roll vidéo) il est posé tel quel. */
export const needsAnim = (b: Beat) => b.type === "motion" || b.type === "transition" || (b.type === "broll" && isImage(b.src));
/** La couleur de chaque type de beat (bande de rythme, cartes, timeline). */
export const TYPE_COLOR: Record<BeatType, string> = { motion: "#7C5CE0", zoom: "#D9971E", broll: "#2A9D8F", transition: "#3B7DD8" };

/** Une vidéo ou une image qu'un B-roll peut montrer. */
export interface Visual { src: string; name: string; kind: "video" | "image"; where: string; description: string; url: string }
export interface BeatWarning { kind: "anchor" | "late" | "overlap" | "busy" | "cover" | "density" | "hidden"; beat: string | null; t: number; text: string; delta?: number }
export interface StoryboardView {
  job: { status: string; finished: boolean; progress: number; error: string | null; activity: string | null } | null;
  board: {
    density: string; note: string; message: string; created: number; beats: Beat[];
    unresolved: { anchor: string; show: string; t: number; origin?: "script" | "daryl" }[];
  } | null;
  checks: {
    warnings: BeatWarning[];
    density: { count: number; target: [number, number]; every: number | null; longest_gap: number };
    /** les beats gardés, par type */
    counts: Record<BeatType, number>;
  } | null;
  densities: string[]; default_density: string; types: BeatType[]; kinds: string[]; places: string[];
  visuals: Visual[];
  /** "" (aucun son), puis le src de chaque son de la bibliothèque et du projet */
  sfx: string[]; sfx_help: Record<string, string>;
  /** les animations du kit, que Daryl propose comme base d'un beat */
  anims: KitAnimation[];
  /** les beats faits : {id du beat: id de ce qu'il a posé (motion écrit, zoom, B-roll)} */
  composed: Record<string, string>;
  /** le chat avec Daryl sur le storyboard */
  chat: StoryboardChat;
  /** la création de l'animation des beats qui en ont une en cours, en file ou ratée */
  anim_jobs: Record<string, AnimState>;
  /** les recherches d'images des beats, tant qu'elles sont dans la file */
  image_jobs: Record<string, ImageJob>;
  /** les mots de la timeline [début, fin], où s'aimantent les beats posés à la main ; un beat commence `lead` s
   * avant son premier mot et finit `tail` s après le dernier */
  words: [number, number][]; lead: number; tail: number;
}
/** La recherche d'images d'un beat (backend assets.beat_searches) : `found`, les images proposées à sa dernière demande. */
export interface ImageJob { status: "queued" | "running" | "done" | "error" | "cancelled"; activity: string | null; error: string | null; query: string; found: number }
export interface AnimState { status: "queued" | "running" | "error" | "cancelled"; activity: string | null; error: string | null }
export interface StoryboardMessage {
  role: "user" | "ai"; text: string;
  /** user : le moment de la timeline, le beat dont on parle, l'image jointe */
  at?: number | null; beat?: string | null; frame?: boolean;
  /** ai : ce que Daryl a changé (ids de beats ; missing : ancres introuvables) */
  changes?: { added: string[]; updated: string[]; removed: string[]; missing: string[] };
}
export interface StoryboardChat { messages: StoryboardMessage[]; busy: boolean; activity: string | null; error: string | null }
export interface KitAnimation {
  name: string; id: string; title: string; description: string; format: "youtube" | "short"; hero: number | null; url: string;
}

/** Un média utilisable : du projet (assets/…) ou de la bibliothèque (library/…). */
export interface AvailableMedia {
  src: string; name: string; category: "rush" | "broll" | "musique" | "sfx"; where: string; kind: string;
  duration: number | null; url: string;
  /** ce que montre ou fait un fichier de la bibliothèque */
  description?: string;
  /** le volume auquel la bibliothèque veut ce son (dB) ; absent : le défaut du studio */
  gain_db?: number;
}
/** Un onglet de la popup des médias : tous, ou une catégorie. */
export type MediaTab = "all" | AvailableMedia["category"];

/** Libellé d'une piste, dans la langue de l'interface (à appeler au rendu). */
export const trackLabel = (track: Track): string => t(`editing.tracks.${track}`);

/** Position de chaque clip de l'A-roll sur la timeline. */
export function clipStarts(tl: Timeline): number[] {
  let a = 0;
  return tl.aroll.map((c) => { const s = a; a += c.out - c.in; return s; });
}

export function totalOf(tl: Timeline): number {
  return tl.aroll.reduce((n, c) => n + c.out - c.in, 0);
}

/** Début et fin d'un élément sur la timeline. */
export function spanOf(tl: Timeline, track: Track, id: string): [number, number] | null {
  if (track === "aroll") {
    const starts = clipStarts(tl), i = tl.aroll.findIndex((c) => c.id === id);
    return i < 0 ? null : [starts[i], starts[i] + tl.aroll[i].out - tl.aroll[i].in];
  }
  if (track === "markers") {
    const m = tl.markers.find((x) => x.id === id);
    return m ? [m.t, m.t] : null;
  }
  const item = (tl[track] as { id: string; at: number }[]).find((x) => x.id === id) as (Zoom | Broll | Motion | Sound | TextNote) | undefined;
  if (!item) return null;
  return [item.at, item.at + ("dur" in item ? item.dur : item.out - item.in)];
}

/** Le plan (B-roll, motion) commence là où finit le précédent de sa piste : son entrée s'enchaîne avec lui. */
export function prevJoined(tl: Timeline, track: "broll" | "motion", id: string): string | null {
  const span = spanOf(tl, track, id);
  if (!span) return null;
  const prev = (tl[track] as { id: string }[]).find((x) => x.id !== id && Math.abs((spanOf(tl, track, x.id)?.[1] ?? -1) - span[0]) <= 0.05);
  return prev?.id ?? null;
}

/**
 * Où se joue une transition sur la timeline, comme au rendu : centrée sur la coupe entre deux clips de l'A-roll
 * ou entre deux plans collés, sinon dans les premières / dernières secondes du plan. null : pas de transition, ou
 * une sortie remplacée par l'enchaînement avec le plan suivant.
 */
export function fxSpan(tl: Timeline, track: Track, id: string, fx: FxEnd): [number, number] | null {
  if (track === "aroll") {
    const i = tl.aroll.findIndex((c) => c.id === id), tr = tl.aroll[i]?.transition;
    if (i < 1 || !tr) return null;
    const cut = clipStarts(tl)[i], half = Math.min(tr.dur, fxMax(tl, track, id, fx)) / 2;
    return [cut - half, cut + half];
  }
  if (track !== "broll" && track !== "motion") return null;
  const span = spanOf(tl, track, id), it = (tl[track] as (Broll | Motion)[]).find((x) => x.id === id);
  const tr = it?.[fx === "exit" ? "exit" : "enter"];
  if (!span || !it || !tr || fx === "transition") return null;
  const len = span[1] - span[0];
  if (fx === "enter") {
    const prev = prevJoined(tl, track, id);
    const prevSpan = prev ? spanOf(tl, track, prev) : null;
    if (prevSpan) {
      const d = Math.min(tr.dur, len, prevSpan[1] - prevSpan[0]);
      return [span[0] - d / 2, span[0] + d / 2];
    }
    return [span[0], span[0] + Math.min(tr.dur, len / 2)];
  }
  // la sortie ne joue pas si le plan suivant s'enchaîne avec celui-ci
  const next = (tl[track] as (Broll | Motion)[]).find((x) => x.enter && x.id !== id && prevJoined(tl, track, x.id) === id);
  return next ? null : [span[1] - Math.min(tr.dur, len / 2), span[1]];
}

/**
 * La plus longue durée qu'une transition peut jouer, comme au rendu : entre deux clips de l'A-roll, la moitié de
 * chacun (un côté sans assez de marge tient son image de bord) ; entre deux plans collés, le plus court des
 * deux ; une entrée ou une sortie, la moitié du plan.
 */
export function fxMax(tl: Timeline, track: Track, id: string, fx: FxEnd): number {
  if (track === "aroll") {
    const i = tl.aroll.findIndex((c) => c.id === id), prev = tl.aroll[i - 1], cur = tl.aroll[i];
    if (!prev || !cur) return 0;
    return 2 * Math.min((prev.out - prev.in) / 2, (cur.out - cur.in) / 2);
  }
  const span = spanOf(tl, track, id);
  if (!span) return 0;
  const len = span[1] - span[0];
  const prev = fx === "enter" && (track === "broll" || track === "motion") ? prevJoined(tl, track, id) : null;
  const prevSpan = prev ? spanOf(tl, track, prev) : null;
  return prevSpan ? Math.min(len, prevSpan[1] - prevSpan[0]) : len / 2;
}

export function newId(tl: Timeline, prefix: string): string {
  const used = new Set(Object.values(tl).flat().map((x: { id: string }) => x.id));
  let n = 1;
  while (used.has(`${prefix}${n}`)) n++;
  return `${prefix}${n}`;
}

export const clone = (tl: Timeline): Timeline => JSON.parse(JSON.stringify(tl));

/** L'écriture manuscrite des textes, la même qu'au rendu (render.TEXT_FONT) ; son contour, en fraction de la taille. */
export const TEXT_FONT = '"Ink Free", "Segoe Print", cursive';
export const TEXT_BORDER = 0.07;
/** Le fondu d'un texte à l'entrée et à la sortie (s), comme au rendu. */
export const TEXT_FADE = 0.15;

/** 01:23.4 */
export function tcd(sec: number): string {
  const d = Math.max(0, Math.round(sec * 10));
  const m = Math.floor(d / 600), s = (d % 600) / 10;
  return `${String(m).padStart(2, "0")}:${s.toFixed(1).padStart(4, "0")}`;
}
