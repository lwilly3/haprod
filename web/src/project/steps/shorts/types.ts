/** Les shorts (backend modules/shorts) et leur montage (backend modules/animations, projets créés depuis un short). */
import { t } from "../../../i18n";

// --- Sélection

export type Format = "vertical" | "original";

/** Un extrait : les lignes `from`…`to` du transcript figé à la sélection, `start`/`end` dans la vidéo source. */
export interface Clip { from: number; to: number; start: number; end: number; role: string; text: string }
/** Le montage ffmpeg du short (vidéo sans sous-titres). */
export interface ShortRender { id: string; status: string; progress: number; error: string | null; url: string | null }
export interface Short {
  id: string; title: string; hook: string; clips: Clip[]; duration: number; errors: string[];
  render: ShortRender | null;
  /** le montage (projet animations) déjà ouvert pour ce short */
  project: string | null;
}
export interface SelectionMessage { role: "user" | "assistant"; text: string; fixes?: number }
export interface Settings { max_duration: number; count: number; context: string; format: Format }

export interface SelectionSummary {
  id: string; name: string; transcript_job: string; status: string; error: string | null;
  created_at: number; count: number;
}
export interface Selection extends SelectionSummary {
  settings: Settings; messages: SelectionMessage[]; shorts: Short[]; activity: string | null; model: string | null;
}

export const MAX_DURATIONS = [60, 90, 180] as const;
export const FORMATS = ["vertical", "original"] as const satisfies readonly Format[];
const SELECTION_STATUSES = new Set(["queued", "running", "thinking", "writing", "fixing"]);
/** Libellé d'un état de la sélection (à appeler au rendu) ; un état inconnu reste tel quel. */
export const selectionStatus = (status: string): string => (SELECTION_STATUSES.has(status) ? t(`clips.status.${status}`) : status);

const FINISHED = new Set(["done", "error", "cancelled"]);
export const isActive = (status?: string | null) => !!status && !FINISHED.has(status);

// --- Montage

export interface Slide {
  id: string; start: number; end: number; title: string; kind: string;
  idea: string; why: string; discarded: boolean;
  /** la composition HyperFrames, une fois écrite par Claude */
  url: string | null;
}

export interface MontageMessage {
  role: "user" | "assistant"; text: string; at: number; slide?: string | null;
  tools?: string[]; duration?: number; changed?: number;
}

export type CaptionStyle = "pop" | "box" | "clean";
export type CaptionPosition = "haut" | "milieu" | "bas";
export interface Captions { url: string; style: CaptionStyle; position: CaptionPosition }
/** captions.json : les groupes de mots affichés ensemble */
export interface CaptionGroup { words: { text: string; start: number; end: number; key: boolean }[]; emoji: string }

export interface MontageRender {
  id: string; status: string; progress: number; error: string | null; stage: string | null; url: string | null;
}

export interface MediaPart { url: string; start: number; duration: number }

/** Un projet animations créé depuis un short. */
export interface Montage {
  id: string; name: string; status: string; error: string | null;
  messages: MontageMessage[]; slides: Slide[]; settings: { format: "youtube" | "short" };
  can_undo: boolean; media: MediaPart[]; activity: string | null; usage: Record<string, number> | null;
  captions: Captions | null; render: MontageRender | null;
}

/** Ids envoyés au backend ; libellés dans shortEditing.captionStyles / captionPositions. */
export const CAPTION_STYLES = ["pop", "box", "clean"] as const satisfies readonly CaptionStyle[];
export const CAPTION_POSITIONS = ["haut", "milieu", "bas"] as const satisfies readonly CaptionPosition[];
/** Taille de la composition : celle de la vidéo finale. */
export const SIZES = { youtube: [1920, 1080], short: [1080, 1920] } as const;
