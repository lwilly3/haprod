/** L'analyse du dérush (phrases, vides, prises ratées de chaque rush) et la timeline : des bouts de rushes. */
import { computed, ref, watch, type Ref } from "vue";
import { t } from "../../../i18n";
import { api } from "../../../lib/api";
import { toast } from "../../../lib/toast";
import { update } from "../../store";
import type { DerushAnalysis, DerushClip, DerushSeg, Project } from "../../types";
import { clipLen, newId } from "./clips";

const FINISHED = ["done", "error", "cancelled", "none"];

export const segDur = (s: DerushSeg) => s.end - s.start;

export function useDerush(project: Ref<Project>) {
  const analysis = ref<DerushAnalysis | null>(null);

  // relu quand des rushes arrivent ou partent, changent de durée, ou qu'une transcription se termine
  const signature = computed(() => project.value.rushes
    .map((r) => `${r.id}:${r.duration}:${project.value.runtime.rush_transcripts[r.id]?.status}`).sort().join("|"));
  let request = 0;
  watch(signature, async () => {
    const n = ++request;
    try {
      const a = await api<DerushAnalysis>(`/api/projects/${project.value.id}/derush`);
      if (n === request) analysis.value = a;
    } catch (e) {
      toast(t("derush.unreadable", { e: (e as Error).message }), true);
    }
  }, { immediate: true });

  const ready = computed(() => !!analysis.value?.ready);

  /** Phrases, vides et prises ratées, rush par rush (en secondes de chaque rush). */
  const segsByRush = computed(() => {
    const out: Record<string, DerushSeg[]> = {};
    for (const s of analysis.value?.segs ?? []) (out[s.rush] ??= []).push({ ...s, src: s.key, words: s.words ?? [] });
    return out;
  });

  /** La timeline : celle de l'utilisateur, sinon celle déduite par le serveur (anciennes coupes, rushes entiers). */
  const clips = computed<DerushClip[]>(() => {
    const known = new Set(project.value.rushes.map((r) => r.id));
    const list = project.value.derush.clips ?? analysis.value?.clips
      ?? project.value.rushes.filter((r) => r.duration).map((r) => ({ id: r.id, rush: r.id, in: 0, out: r.duration! }));
    return list.filter((c) => known.has(c.rush));
  });
  const kept = computed(() => clips.value.reduce((a, c) => a + clipLen(c), 0));

  // --- retouches, avec annuler / rétablir
  const past: DerushClip[][] = [], future: DerushClip[][] = [];
  const history = ref(0);
  const put = (list: DerushClip[]) => update({ clips: list }, 300);
  /** Applique une retouche à la timeline. */
  function edit(fn: (clips: DerushClip[]) => DerushClip[]) {
    const before = clips.value, next = fn(before);
    if (next === before) return;
    past.push(before);
    if (past.length > 200) past.shift();
    future.length = 0;
    history.value++;
    put(next);
  }
  function undo() {
    const s = past.pop();
    if (!s) return;
    future.push(clips.value);
    put(s);
    history.value++;
  }
  function redo() {
    const s = future.pop();
    if (!s) return;
    past.push(clips.value);
    put(s);
    history.value++;
  }
  const canUndo = computed(() => history.value >= 0 && past.length > 0);
  const canRedo = computed(() => history.value >= 0 && future.length > 0);
  /** Remet un rush entier au bout de la timeline. */
  function append(rush: string) {
    const r = project.value.rushes.find((k) => k.id === rush);
    if (r?.duration) edit((list) => [...list, { id: newId(), rush, in: 0, out: r.duration! }]);
  }

  /** Transcriptions des rushes en cours, et leur avancement moyen (%). */
  const transcribing = computed(() => Object.values(project.value.runtime.rush_transcripts)
    .some((r) => !FINISHED.includes(r.status)));
  const progress = computed(() => {
    const all = project.value.rushes.map((r) => project.value.runtime.rush_transcripts[r.id]);
    const sum = all.reduce((a, r) => a + (r?.status === "done" ? 1 : r?.progress ?? 0), 0);
    return all.length ? Math.round(sum / all.length * 100) : 0;
  });

  return { analysis, ready, segsByRush, clips, kept, transcribing, progress, edit, undo, redo, canUndo, canRedo, append };
}
