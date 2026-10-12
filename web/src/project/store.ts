/**
 * Le projet ouvert et la liste des projets.
 *
 * Les modifications sont appliquées tout de suite à l'écran puis envoyées (PATCH), regroupées
 * quand elles arrivent en rafale (frappe au clavier). Tant qu'un job tourne (Claude, copie,
 * transcription, rendu), le projet est relu régulièrement : ce qui n'est pas encore envoyé
 * reste prioritaire sur ce qui revient du serveur.
 */
import { reactive } from "vue";
import { t } from "../i18n";
import { api, del, patchJson, post } from "../lib/api";
import { toast } from "../lib/toast";
import type { Project, ProjectPatch, ProjectSummary, Runtime } from "./types";

export const store = reactive({
  list: [] as ProjectSummary[],
  project: null as Project | null,
  /** id du projet en cours de chargement (le précédent reste affiché d'ici là) */
  loading: null as string | null,
});

const base = (pid: string) => `/api/projects/${pid}`;

let pending: ProjectPatch = {};
let flushTimer: ReturnType<typeof setTimeout> | undefined;
let pollTimer: ReturnType<typeof setTimeout> | undefined;

export async function loadList(): Promise<void> {
  store.list = await api<ProjectSummary[]>("/api/projects");
}

function applyPatch(p: Project, changes: ProjectPatch): void {
  for (const [key, value] of Object.entries(changes)) {
    if (key === "cuts" || key === "splits" || key === "timelines") p.derush = { ...p.derush, [key]: value };
    else if (key === "capture") p.assets = { ...p.assets, capture: value as Project["assets"]["capture"] };
    else if (key === "rush_order") {
      const order = value as string[];
      p.rushes = [...p.rushes].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
    } else (p as any)[key] = value;
  }
}

/** Remplace le projet affiché par ce que renvoie le serveur, sans perdre ce qui n'est pas encore envoyé. */
export function receive(view: Project): void {
  if (store.project && store.project.id === view.id) applyPatch(view, pending);
  store.project = view;
  const i = store.list.findIndex((p) => p.id === view.id);
  if (i >= 0) store.list[i] = { ...store.list[i], title: view.title, status: view.status, brief: view.brief };
  schedulePoll();
}

export async function open(pid: string): Promise<void> {
  if (store.project?.id === pid) return;
  await flush();
  store.loading = pid;
  try {
    const view = await api<Project>(base(pid));
    pending = {};
    store.project = view;
    schedulePoll();
    // dernier projet ouvert : c'est lui que l'accueil propose de reprendre
    patchJson(base(pid), { opened_at: Date.now() / 1000 }).catch(() => {});
    if (!store.list.length) loadList().catch(() => {});
  } finally {
    store.loading = null;
  }
}

export function close(): void {
  store.project = null;
}

/** Modifie le projet ; `delay` regroupe les frappes successives (ms). */
export function update(changes: ProjectPatch, delay = 0): void {
  const p = store.project;
  if (!p) return;
  applyPatch(p, changes);
  Object.assign(pending, changes);
  clearTimeout(flushTimer);
  flushTimer = setTimeout(flush, delay);
}

export async function flush(): Promise<void> {
  clearTimeout(flushTimer);
  const p = store.project;
  if (!p || !Object.keys(pending).length) return;
  const changes = pending;
  pending = {};
  try {
    receive(await patchJson<Project>(base(p.id), changes));
  } catch (e) {
    toast(t("project.saveFailed", { error: (e as Error).message }), true);
  }
}

/** Appel d'une action du projet (POST par défaut) ; le projet renvoyé remplace l'affiché. */
export async function act(path: string, body?: unknown, method: "POST" | "DELETE" = "POST"): Promise<Project | null> {
  const p = store.project;
  if (!p) return null;
  await flush();
  try {
    const view = method === "DELETE" ? await del<Project>(base(p.id) + path) : await post<Project>(base(p.id) + path, body);
    receive(view);
    return view;
  } catch (e) {
    toast((e as Error).message, true);
    return null;
  }
}

export async function refresh(): Promise<void> {
  const p = store.project;
  if (!p) return;
  receive(await api<Project>(base(p.id)));
}

export async function createProject(body: unknown): Promise<Project> {
  const view = await post<Project>("/api/projects", body);
  store.project = view;
  pending = {};
  await loadList();
  return view;
}

export async function removeProject(pid: string): Promise<void> {
  await del(base(pid));
  if (store.project?.id === pid) store.project = null;
  await loadList();
}

// --- relecture pendant que des jobs tournent -------------------------------------------

const RUNNING_TRANSCRIPT = ["queued", "extracting", "loading", "transcribing", "running"];

export function isBusy(r: Runtime | undefined, p: Project | null = store.project): boolean {
  if (!r || !p) return false;
  return Object.values(r.jobs).some((j) => j && !j.finished)
    || r.importing.length > 0
    || Object.values(r.rush_transcripts).some((t) => RUNNING_TRANSCRIPT.includes(t.status))
    || !!(r.source_transcript && !r.source_transcript.finished)
    || !!p.source?.pending
    || r.assets.downloads.some((d) => !d.finished);
}

function schedulePoll(): void {
  clearTimeout(pollTimer);
  const p = store.project;
  if (!p || !isBusy(p.runtime, p)) return;
  pollTimer = setTimeout(async () => {
    if (store.project?.id !== p.id) return;
    try {
      await refresh();
    } catch {
      schedulePoll();
    }
  }, 1500);
}

/** Un job du projet est-il en cours ? (angles, script, render…) */
export function running(name: string): boolean {
  const j = store.project?.runtime.jobs[name];
  return !!j && !j.finished;
}

/** Le job s'est-il terminé en erreur ? Son message, sinon null. */
export function failed(name: string): string | null {
  const j = store.project?.runtime.jobs[name];
  return j && j.status === "error" ? j.error : null;
}
