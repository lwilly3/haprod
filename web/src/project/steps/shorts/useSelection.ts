/**
 * La sélection de shorts du projet : Claude choisit des passages du transcript de la vidéo source,
 * chaque short valide est ensuite monté par ffmpeg (sans sous-titres), puis habillé à l'étape Montage.
 *
 * Plusieurs sélections peuvent exister sur un même transcript : on affiche la dernière ouverte
 * (mémorisée par projet), la plus récente sinon.
 */
import { computed, ref, watch, type Ref } from "vue";
import { api, del, post, putJson } from "../../../lib/api";
import { usePolling, usePref } from "../../../lib/composables";
import { t } from "../../../i18n";
import { toast } from "../../../lib/toast";
import { refresh, store, update } from "../../store";
import type { Project } from "../../types";
import { isActive, type Format, type Selection, type SelectionSummary, type Settings, type Short } from "./types";

/** Passe l'étape en cours si elle était encore « à faire ». */
export function startStep(step: string): void {
  const p = store.project;
  if (p && (p.status[step] ?? "todo") === "todo") update({ status: { ...p.status, [step]: "cur" } });
}

/**
 * Shorts envoyés au montage (« Monter → ») dont la vidéo est encore en découpe : l'étape Montage
 * crée leur montage dès qu'elle est prête.
 */
export function useWanted(pid: string) {
  return usePref<string[]>(`shorts.wanted.${pid}`, []);
}

export function useSelection(project: Ref<Project>) {
  const transcript = computed(() => {
    const id = project.value.source?.transcript;
    const job = project.value.runtime.source_transcript;
    return id && job?.id === id && job.status === "done" ? id : null;
  });
  const chosen = usePref<string | null>(`shorts.selection.${project.value.id}`, null);
  const list = ref<SelectionSummary[]>([]);
  const sel = ref<Selection | null>(null);
  const loaded = ref(false);

  const running = computed(() => isActive(sel.value?.status));
  const rendering = computed(() => (sel.value?.shorts ?? []).some((s) => isActive(s.render?.status)));
  const shorts = computed<Short[]>(() => sel.value?.shorts ?? []);
  const total = computed(() => shorts.value.reduce((n, s) => n + s.duration, 0));
  const base = computed(() => (sel.value ? `/api/shorts/jobs/${sel.value.id}` : ""));

  async function load(): Promise<void> {
    const tid = transcript.value;
    if (!tid) {
      list.value = [];
      sel.value = null;
      loaded.value = true;
      return;
    }
    const found = await api<SelectionSummary[]>(`/api/shorts/jobs?transcript=${tid}`);
    if (tid !== transcript.value) return;
    list.value = found;
    const id = found.some((s) => s.id === chosen.value) ? chosen.value : found.at(-1)?.id ?? null;
    const detail = id ? await api<Selection>(`/api/shorts/jobs/${id}`) : null;
    if (tid === transcript.value) {
      sel.value = detail;
      loaded.value = true;
    }
  }

  usePolling(async () => {
    const before = running.value;
    await load();
    // fin d'un tour de Claude : le nombre de shorts de la barre du haut change
    if (before && !running.value) refresh().catch(() => {});
    return running.value || rendering.value ? 1000 : 4000;
  });
  watch(transcript, () => load());

  /** Réponse du serveur : la sélection affichée change aussitôt, sans attendre la relecture. */
  function receive(s: Selection): void {
    sel.value = s;
    chosen.value = s.id;
    if (!list.value.some((x) => x.id === s.id)) list.value = [...list.value, s];
  }

  async function call(run: () => Promise<Selection>): Promise<boolean> {
    try {
      receive(await run());
      return true;
    } catch (e) {
      toast((e as Error).message, true);
      return false;
    }
  }

  const create = (request: string, settings: Settings) => call(async () => {
    const s = await post<Selection>("/api/shorts/jobs", { transcript_job: transcript.value, request, settings });
    startStep("selection");
    refresh().catch(() => {});
    return s;
  });
  const send = (text: string) => call(() => post<Selection>(`${base.value}/messages`, { text }));
  const setFormat = (format: Format) => call(() => putJson<Selection>(`${base.value}/format`, { format }));
  const removeShort = (id: string) => call(() => del<Selection>(`${base.value}/shorts/${id}`));
  /** Découpe la vidéo du short (ffmpeg) ; une découpe déjà faite ou en cours est reprise, une ratée relancée. */
  const cut = (id: string) => call(() => post<Selection>(`${base.value}/shorts/${id}/render?force=false`));

  async function stop(): Promise<void> {
    if (sel.value) await post(`${base.value}/stop`).catch(() => {});
    await load();
  }

  function open(id: string): void {
    chosen.value = id;
    sel.value = null;
    load();
  }

  async function removeSelection(): Promise<void> {
    const s = sel.value;
    if (!s || !confirm(t("clips.deleteConfirm", { n: s.shorts.length }, s.shorts.length))) return;
    try {
      await del(`/api/shorts/jobs/${s.id}`);
      chosen.value = null;
      await load();
      refresh().catch(() => {});
    } catch (e) {
      toast((e as Error).message, true);
    }
  }

  /** Le montage (projet animations) du short : rouvert s'il existe, créé sinon (le short doit être monté). */
  async function montage(short: Short): Promise<string | null> {
    if (short.project) return short.project;
    try {
      const p = await post<{ id: string }>("/api/animations/jobs/from-short", { selection: sel.value!.id, short: short.id });
      startStep("smontage");
      await load();
      refresh().catch(() => {});
      return p.id;
    } catch (e) {
      toast((e as Error).message, true);
      return null;
    }
  }

  return {
    transcript, list, sel, loaded, running, rendering, shorts, total, base,
    create, send, setFormat, removeShort, cut, stop, open, removeSelection, montage, load,
  };
}

export type SelectionState = ReturnType<typeof useSelection>;
