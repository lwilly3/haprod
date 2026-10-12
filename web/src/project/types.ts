/** Ce que renvoie /api/projects/{id} (project.json + runtime). */

export type StepState = "todo" | "cur" | "done" | "skip";

export interface Brief { idea: string; dir: string; dur: string; notes: string; links: string[] }

export interface Angle { t: string; p: string; why?: string; v?: number; note?: string }

/**
 * Un titre proposé par Claude (`ai`), ou ajouté à la main ; `pick` : retenu pour l'A/B test, `top` : conseillé
 * par Claude.
 */
export interface Title { t: string; pattern: string; why: string; ai?: boolean; top?: boolean; pick?: boolean }

/**
 * Une variante de vignette. `title` : le titre (retenu à l'étape Titre) qu'elle accompagne dans l'A/B test ;
 * `text` : le texte que le modèle écrit dans l'image (vide : aucun) ; `portraits` et `styles` : images de la
 * bibliothèque (« portraits/x.jpg », « vignettes/y.png ») envoyées au modèle ; `image` : l'image générée
 * retenue (fichier de vignettes/), sinon la plus récente.
 */
export interface Thumb {
  v: string; text: string;
  id?: string; title?: string; prompt?: string; portraits?: string[]; styles?: string[]; image?: string | null;
  /** retenue pour l'A/B test YouTube (3 au plus) */
  pick?: boolean;
}

/** Une composition de vignette proposée par Claude (skill youtube-thumbnail). */
export interface ThumbIdea { name: string; scene: string; text: string; colors: string; hook: string }

/** Une image générée pour une variante (fichier de vignettes/) ; une retouche a son image d'origine et sa consigne. */
export interface ThumbImage { file: string; model: string; source?: string; edit?: string }

/** Une ligne du tableau des sources ; `by` : ajoutée par Claude. */
export interface ResearchSource { t: string; u: string; n: string; by?: "claude" }

export interface Shot { id: string; sec: string; q: string; type: string; frame: string; note: string; on: boolean }

/** Un fichier associé à un plan du script. */
export interface PlanMedia { url: string; name: string; kind: string; duration: number | null }

/**
 * Un plan du script (script.json) : il couvre le passage `q`, du bloc `block` (null : il a disparu)
 * au bloc `end` (null : le même) ; `on` : tourné / trouvé ; `by` : venu d'une ligne [VISUEL] de Claude ;
 * `setup` : le setup où il se tourne ("" : celui de sa section, pour un face caméra).
 */
export interface Plan {
  id: string; block: string | null; end: string | null; q: string; type: string; frame: string; setup?: string;
  note: string; media: PlanMedia[]; on: boolean; by?: "claude";
}

/** Une configuration de tournage (cadre, lieu, lumière), A, B, C… dans l'ordre. */
export interface Setup { id: string; name: string; note: string }

export interface Rush {
  id: string; name: string; path: string; size: number; time: string; shot_at?: string | null;
  duration?: number | null; width?: number; height?: number; fps?: number; audio?: boolean;
  transcript: string | null;
}

export interface Source {
  kind: "import" | "derush"; path: string; name: string; pending: boolean;
  duration: number | null; width: number | null; height: number | null;
  drift: boolean; derived: boolean; transcript: string | null;
}

export interface JobView {
  id: string; kind: string; status: string; progress: number; error: string | null;
  finished: boolean; activity: string | null;
  /** job des angles : "generate" ou "iterate" (et l'angle retravaillé) */
  mode?: string | null; index?: number | null;
}

export interface Runtime {
  jobs: Record<string, JobView | null>;
  importing: { name: string; pct: number; target: "rushes" | "source"; error: string | null }[];
  rush_transcripts: Record<string, { status: string; progress: number; error: string | null }>;
  source_transcript: JobView | null;
  docs: Record<string, number>;
  has_script: boolean;
  script_words: number;
  /** les plans du script, et ceux qui sont faits */
  plans: { total: number; done: number };
  /** la note du dernier roast terminé */
  roast_score: number | null;
  /** le dernier export .mp4 du dérush correspond-il encore à sa timeline (`render_timeline`) ? */
  render_current: boolean;
  render_timeline: string | null;
  /** capturing : les sources que le job de captures doit encore traiter (la première est en cours) */
  assets: { downloads: AssetDownload[]; capturing: string[] };
  /** les modèles d'image de fal.ai ; `ready` : la clé FAL_KEY est définie */
  thumbs: { models: { id: string; label: string }[]; ready: boolean };
  /** la dernière sélection de shorts sur le transcript de la vidéo source, et ses shorts en montage */
  shorts: { selection: string | null; count: number; montages: number };
  now: number;
}

/** Une vidéo prévisualisée à l'étape Assets ; `yt` : id YouTube (lecteur intégré), null ailleurs. */
export interface AssetVideo {
  id: string; url: string; title: string; uploader: string | null; duration: number | null;
  thumbnail: string | null; heights: number[]; yt: string | null;
}

/** Un téléchargement lancé depuis l'étape Assets (job du module youtube) ; sans start/end : la vidéo entière. */
export interface AssetDownload {
  id: string; video: string; dest: string; status: string; progress: number; error: string | null;
  finished: boolean; mode: "video" | "audio" | "thumbnail"; start: number | null; end: number | null;
  name: string | null; transcribe: boolean;
}

export interface Assets {
  videos: AssetVideo[];
  /** sources à capturer (url -> coché) */
  capture: Record<string, boolean>;
  /** captures faites (url -> fichier du projet, ou erreur) */
  captures: Record<string, { rel: string | null; error: string | null; manual?: boolean }>;
}

/** Une image proposée par Claude ; `added` : où elle a été rangée (« Projet · Images »). */
export interface ImageResult {
  id: string; title: string; url: string; page: string; variant: string; license: string;
  file: string; query: string; added: string | null;
}

export interface ImagesState {
  messages: { role: "user" | "ai"; text: string; count?: number }[];
  results: ImageResult[]; busy: boolean; error: string | null; activity: string | null;
}

export type Visibility = "private" | "unlisted" | "public" | "scheduled";

/** Titre, description et tags d'une vidéo ; vidéo longue : la vignette A et le test A/B (variantes B et C). */
export interface VideoMeta {
  title: string; desc: string; tags: string[];
  thumb?: string | null; ab_on?: boolean; ab?: { thumb: string | null; title: string }[];
}

/** Ce que l'interface écrit pour Description et Upload (par vidéo : "long" ou l'id d'un short). */
export interface PublishData {
  videos?: Record<string, Partial<VideoMeta>>;
  pub?: Record<string, { vis: Visibility; sched: string }>;
}

export interface Project {
  id: string; title: string; mode: "idea" | "video";
  created_at: number; updated_at: number; opened_at: number;
  status: Record<string, StepState>;
  brief: Brief;
  angles: Angle[]; angle_sel: number | null; angle_round: number;
  titles: Title[]; titles_round: number; titles_advice: string;
  thumbs: Thumb[]; thumb_sel: number | null;
  /** les images générées, par variante (écrit par le serveur seulement) */
  thumb_images?: Record<string, ThumbImage[]>;
  /** les dernières compositions proposées, pour la variante `thumb` (écrit par le serveur seulement) */
  thumb_ideas?: { thumb: string; items: ThumbIdea[]; message: string };
  research: ResearchSource[];
  shots: Shot[];
  rushes: Rush[]; rush_sort: "Script" | "Heure" | "Manuel";
  derush: { cuts: Record<string, "cut" | "keep">; splits?: Record<string, number[]>; timelines: DerushTimeline[]; main: string };
  source: Source | null;
  assets: Assets;
  jobs: Record<string, string>;
  copies: string[];
  publish?: PublishData;
  runtime: Runtime;
}

export interface ProjectSummary {
  id: string; title: string; mode: "idea" | "video"; status: Record<string, StepState>;
  brief: Brief; created_at: number; updated_at: number; opened_at: number; angle: string | null;
  /** la vignette de la première variante qui en a une (chemin relatif au projet) */
  thumb: string | null;
  /** octets occupés par le dossier du projet */
  size: number;
}

/** Place occupée par un projet, par catégorie (GET /storage). */
export interface ProjectStorage {
  total: number;
  /** octets libres sur le disque des projets */
  free: number;
  categories: { key: "rushes" | "source" | "derush" | "renders" | "media" | "other"; bytes: number }[];
}

/** Ce qui se modifie directement (PATCH). */
export type ProjectPatch = Partial<Pick<Project,
  "title" | "status" | "brief" | "angle_sel" | "titles" | "thumbs" | "thumb_sel" | "research" | "shots" | "rush_sort" | "publish">> &
  { cuts?: Record<string, "cut" | "keep">; splits?: Record<string, number[]>; timelines?: DerushTimeline[]; rush_order?: string[]; capture?: Record<string, boolean>; opened_at?: number };

/** Un bout de rush lu par la timeline du dérush : la plage [in, out] du rush, en secondes. */
export interface DerushClip { id: string; rush: string; in: number; out: number }

/** Un bout d'une timeline tel qu'on l'édite : un rush (`rush`) ou une autre timeline imbriquée (`tl`), sur [in, out]. */
export interface TimelineClip { id: string; rush?: string; tl?: string; in: number; out: number }

/**
 * Une timeline du dérush ; `name` vide : nom par défaut. `clips` null : la globale découle encore des rushes
 * (voir backend runtime.own_clips).
 */
export interface DerushTimeline { id: string; name: string; clips: TimelineClip[] | null }

/** Un mot du transcript d'un rush : [début, fin, texte], en secondes du rush. */
export type DerushWord = [number, number, string];

/** Un morceau du dérush (voir backend projects/derush.py) ; `src` est la clé du morceau d'origine quand l'utilisateur l'a recoupé. */
export interface DerushSeg {
  key: string; src: string; rush: string; start: number; end: number;
  type: "speech" | "retake" | "sil"; text: string; words: DerushWord[]; sec: string | null; line: number;
  state: "keep" | "cut";
}

export interface DerushAnalysis {
  ready: boolean;
  transcripts: { rush: string; status: string; progress: number; error?: string | null }[];
  segs: DerushSeg[];
  sections: { id: string; label: string; title: string }[];
  clips: DerushClip[];
}

/** Une coupe proposée par le dérush automatique, en secondes du rush (voir backend projects/autoderush.py). */
export interface AutoCut {
  id: string; rush: string; start: number; end: number;
  kind: "silence" | "stutter" | "retake" | "false_start" | "meta" | "other";
  text: string; reason: string;
}

/** Ce que le dérush automatique demande de regarder : une prise restée, un contenu perdu, une coupe introuvable. */
export interface AutoWarning { kind: "repeat" | "lost" | "unresolved"; rush: string | null; t: number; text: string; reason?: string }

export interface AutoDerush {
  status: string; finished: boolean; progress: number; error: string | null; activity: string | null; note: string;
  result: {
    items: AutoCut[]; warnings: AutoWarning[]; message: string; note: string;
    stats: { total: number; removed: number; repaired: number; silent: string[] };
  } | null;
}

export interface SourceTranscript {
  id: string; status: string; progress: number; error: string | null;
  language: string | null; duration: number | null;
  lines: { start: number; end: number; text: string }[];
  outputs: string[];
}

/** Un angle proposé par Claude dans la discussion de l'étape Angle. */
export interface ProposedAngle { title: string; promise: string; why: string }
/** Un plan proposé par l'assistant du script : `passage` est le texte qu'il illustre ; accepté, il devient le plan `id`. */
export interface ProposedPlan { id: string; type: string; passage: string; note: string; why: string; media: PlanMedia[] }
export interface ChatMessage {
  role: "user" | "ai"; text: string; quote: string | null; angles?: ProposedAngle[]; plans?: ProposedPlan[];
}
export interface ChatThread { id: string; title: string; created_at: number }
/** Une discussion (`thread` null : nouvelle discussion pas encore commencée) et la liste de celles du sujet. */
export interface ChatState {
  thread: string | null; threads: ChatThread[];
  messages: ChatMessage[]; busy: boolean; error: string | null; activity: string | null;
}

/** Une remarque d'un roast, ancrée sur un bloc du script (`block` vide : introuvable) ; `quote` : le passage visé. */
export interface RoastFinding {
  id: string; block: string; quote: string; severity: "bloquant" | "important" | "detail";
  category: string; problem: string; fix: string;
}

/** Ce que rend un roast (voir backend projects/roast.py) ; les `block` sont des ids de bloc du script. */
export interface RoastResult {
  verdict: { score: number; decision: "tourne" | "retouche" | "reecris"; headline: string };
  criteria: { key: string; score: number; why: string; block: string }[];
  sections: { block: string; role: string; score: number; payoff: boolean; too_long: boolean; verdict: string }[];
  interest: { block: string; score: number }[];
  /** `close` vide : jamais refermée */
  loops: { question: string; open: string; close: string }[];
  promises: { source: "angle" | "titre" | "vignette"; promise: string; block: string; note: string }[];
  findings: RoastFinding[];
}

/** Un roast : le script tel qu'il était (`blocks`), le résultat, et ce que l'auteur a fait des remarques. */
export interface RoastRun {
  id: string; status: string; error: string | null; finished: boolean; activity: string | null;
  created_at: number; finished_at: number | null; cold: boolean; note: string;
  blocks: { id: string; md: string }[];
  result: RoastResult | null;
  marks: Record<string, "done" | "ignored">;
}

export interface RoastList { runs: RoastRun[]; criteria: Record<string, string>; categories: Record<string, string> }
