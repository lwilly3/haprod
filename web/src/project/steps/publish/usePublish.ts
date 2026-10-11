/**
 * Les vidéos à publier (la longue, les shorts de la sélection), communes aux étapes Description et
 * Upload : le serveur donne les valeurs par défaut, l'envoi et le rendu ; ce qui est saisi ici va dans
 * project.publish et l'emporte aussitôt, sans attendre la relecture.
 */
import { computed, ref, type Ref } from "vue";
import { api, post } from "../../../lib/api";
import { usePolling, usePref } from "../../../lib/composables";
import { t } from "../../../i18n";
import { toast } from "../../../lib/toast";
import { refresh, update } from "../../store";
import type { Project, PublishData, VideoMeta, Visibility } from "../../types";

export const MAX_TITLE = 100;
export const MAX_DESC = 5000;
export const MAX_VARIANTS = 3;

/** Les visibilités et la clé de leur libellé (à traduire au rendu). */
export const VISIBILITY: [Visibility, string][] = [
  ["private", "upload.vis.private"], ["unlisted", "upload.vis.unlisted"], ["public", "upload.vis.public"], ["scheduled", "upload.vis.scheduled"],
];

// les vérifications arrivent du serveur avec un libellé français qui sert aussi d'identifiant
const CHECK_LABELS: Record<string, string> = {
  "Vignette": "upload.checks.thumbnail", "Titre": "upload.checks.title", "Description": "upload.checks.description",
  "Chapitres": "upload.checks.chapters", "Test A/B": "upload.checks.ab", "Rendu": "upload.checks.render",
};
/** Le libellé affiché d'une vérification. */
export const checkLabel = (k: string) => (CHECK_LABELS[k] ? t(CHECK_LABELS[k]) : k);

export interface Check { k: string; ok: boolean; fix: string; meta?: boolean }
export interface Upload {
  status: string; progress: number; error: string | null; video_id: string | null; warning: string | null; url: string | null;
}
export interface Video {
  id: string; kind: "long" | "short"; name: string; format: string; duration: number;
  meta: VideoMeta; chapters?: { t: string; label: string }[]; passage?: string;
  file: string | null; checks: Check[]; pub: { vis: Visibility; sched: string }; upload: Upload | null;
}
export interface Account { client: boolean; connected: boolean; channel: { id: string; title: string; thumbnail: string | null } | null }
interface View { videos: Video[]; account: Account; long_title: string }

export const uploading = (u: Upload | null) => !!u && !["done", "error", "cancelled"].includes(u.status);

/** L'image retenue d'une variante de vignette (sinon la plus récente). */
export function thumbUrl(p: Project, tid: string | null | undefined): string | null {
  const t = p.thumbs.find((x) => x.id === tid);
  if (!t?.id) return null;
  const file = t.image ?? p.thumb_images?.[t.id]?.at(-1)?.file;
  return file ? `/api/projects/${p.id}/files/vignettes/${encodeURIComponent(file)}` : null;
}

export const titleOk = (t: string) => !!t.trim() && t.length <= MAX_TITLE;

export function usePublish(project: Ref<Project>) {
  const pid = project.value.id;
  const selection = usePref<string | null>(`shorts.selection.${pid}`, null);
  const data = ref<View | null>(null);

  async function load(): Promise<void> {
    data.value = await api<View>(`/api/projects/${pid}/publish${selection.value ? `?selection=${selection.value}` : ""}`);
  }
  usePolling(async () => {
    await load();
    return data.value?.videos.some((v) => uploading(v.upload)) ? 1000 : 5000;
  });

  const saved = (): PublishData => project.value.publish ?? {};

  /** Les métadonnées saisies ici passent devant celles du serveur, et les vérifications suivent. */
  const videos = computed<Video[]>(() => (data.value?.videos ?? []).map((v) => {
    const meta = { ...v.meta, ...(saved().videos?.[v.id] ?? {}) } as VideoMeta;
    const pub = { ...v.pub, ...(saved().pub?.[v.id] ?? {}) };
    const variants = [{ thumb: meta.thumb ?? null, title: meta.title }, ...(meta.ab ?? [])];
    const checks = v.checks.map((c): Check => {
      if (!c.meta) return c;
      switch (c.k) {
        case "Titre": return { ...c, ok: titleOk(meta.title) };
        case "Description": return { ...c, ok: !!meta.desc.trim() };
        case "Chapitres": return { ...c, ok: meta.desc.includes("00:00") };
        case "Test A/B": return { ...c, ok: variants.length >= 2 && variants.every((a) => titleOk(a.title) && !!thumbUrl(project.value, a.thumb)) };
        default: return c;
      }
    });
    // le test A/B activé ou désactivé ici : sa vérification apparaît ou disparaît
    if (v.kind === "long" && meta.ab_on && !checks.some((c) => c.k === "Test A/B")) {
      const ok = variants.length >= 2 && variants.every((a) => titleOk(a.title) && !!thumbUrl(project.value, a.thumb));
      checks.splice(checks.length - 1, 0, { k: "Test A/B", ok, fix: "description", meta: true });
    }
    return { ...v, meta, pub, checks: meta.ab_on || v.kind !== "long" ? checks : checks.filter((c) => c.k !== "Test A/B") };
  }));

  function write(change: (p: Required<PublishData>) => void, delay = 500): void {
    const next = structuredClone({ videos: {}, pub: {}, ...saved() }) as Required<PublishData>;
    change(next);
    update({ publish: next }, delay);
  }
  const setMeta = (id: string, patch: Partial<VideoMeta>) =>
    write((p) => { p.videos[id] = { ...p.videos[id], ...patch }; });
  const setPub = (id: string, patch: Partial<{ vis: Visibility; sched: string }>) => {
    const current = videos.value.find((v) => v.id === id)?.pub;
    write((p) => { p.pub[id] = { ...(current ?? { vis: "private", sched: "" }), ...p.pub[id], ...patch }; }, 0);
  };

  async function send(path: string, video: string): Promise<void> {
    try {
      data.value = await post<View>(`/api/projects/${pid}/${path}`, { video, selection: selection.value });
      refresh().catch(() => {});
    } catch (e) {
      toast((e as Error).message, true);
    }
  }

  return {
    data, videos, load, setMeta, setPub,
    account: computed(() => data.value?.account ?? null),
    longTitle: computed(() => videos.value.find((v) => v.kind === "long")?.meta.title ?? ""),
    start: (video: string) => send("upload", video),
    stop: (video: string) => send("upload/stop", video),
  };
}

/** Ce qui manque à une vidéo (vérifications ratées). */
export const missing = (v: Video) => v.checks.filter((c) => !c.ok);
/** Ce qui manque dans ce qui se saisit à l'étape Description. */
export const metaMissing = (v: Video) => v.checks.filter((c) => c.meta && !c.ok);

export const titleCount = (t: string) => `${t.length}/${MAX_TITLE}`;
