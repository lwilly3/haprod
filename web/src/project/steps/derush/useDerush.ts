/** L'analyse du dérush (phrases, vides, prises ratées de chaque rush) et la timeline : des bouts de rushes. */
import { computed, ref, watch, type Ref } from "vue";
import { t } from "../../../i18n";
import { api } from "../../../lib/api";
import { toast } from "../../../lib/toast";
import { update } from "../../store";
import type { DerushAnalysis, DerushSeg, DerushTimeline, Project, TimelineClip } from "../../types";
import { clipLen, contains, flatten, insert, newId } from "./clips";

/** Ce qu'on pose depuis la médiathèque : un rush entier ou une timeline. */
export interface MediaItem { rush?: string; tl?: string }
/** Le type des données glissées de la médiathèque vers la timeline. */
export const MEDIA_TYPE = "application/x-studio-media";

const r3 = (n: number) => Math.round(n * 1000) / 1000;

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

  // --- timelines : la globale (celle qu'on exporte) et celles qu'on monte à part, rush par rush ou séquence par séquence
  const timelines = computed(() => project.value.derush.timelines);
  const mainId = computed(() => project.value.derush.main);
  /** La timeline ouverte. */
  const current = ref(mainId.value);
  watch(timelines, (list) => { if (!list.some((k) => k.id === current.value)) current.value = mainId.value; });

  /** Les bouts d'une timeline, tels qu'on les édite ; la globale jamais retouchée découle des rushes (serveur). */
  function own(id: string): TimelineClip[] {
    const tl = timelines.value.find((k) => k.id === id);
    if (!tl) return [];
    const rushes = new Set(project.value.rushes.map((r) => r.id)), ids = new Set(timelines.value.map((k) => k.id));
    const list: TimelineClip[] = tl.clips ?? (id !== mainId.value ? [] : analysis.value?.clips
      ?? project.value.rushes.filter((r) => r.duration).map((r) => ({ id: r.id, rush: r.id, in: 0, out: r.duration! })));
    return list.filter((c) => (c.tl ? ids.has(c.tl) : rushes.has(c.rush!)));
  }
  /** La timeline ouverte : ses bouts (rushes et timelines imbriquées), et les bouts de rushes qu'elle lit. */
  /** La durée lue par une timeline. */
  const lengthOf = (id: string) => flatten(own, id).reduce((a, c) => a + clipLen(c), 0);
  // une timeline imbriquée raccourcie depuis : son bout s'arrête là où elle s'arrête
  const clips = computed(() => own(current.value).flatMap((c) => {
    if (!c.tl) return [c];
    const out = Math.min(c.out, r3(lengthOf(c.tl)));
    return out - c.in < 0.04 ? [] : [out === c.out ? c : { ...c, out }];
  }));
  const flat = computed(() => flatten(own, current.value));
  const kept = computed(() => flat.value.reduce((a, c) => a + clipLen(c), 0));
  const nameOf = (id: string) => timelines.value.find((k) => k.id === id)?.name
    || (id === mainId.value ? t("derush.timelines.main") : id);
  /** Peut-on imbriquer `id` dans la timeline ouverte ? (pas elle-même, ni une qui la contient déjà) */
  const canNest = (id: string) => !contains(timelines.value, id, current.value);

  function save(list: DerushTimeline[], delay = 0) {
    update({ timelines: list }, delay);
  }
  const put = (id: string, list: TimelineClip[]) =>
    save(timelines.value.map((k) => (k.id === id ? { ...k, clips: list } : k)), 300);

  // --- retouches, avec annuler / rétablir (qui rouvrent la timeline retouchée)
  type Step = { tl: string; clips: TimelineClip[] };
  const past: Step[] = [], future: Step[] = [];
  const history = ref(0);
  /** Applique une retouche à la timeline ouverte. */
  function edit(fn: (clips: TimelineClip[]) => TimelineClip[]) {
    const before = clips.value, next = fn(before);
    if (next === before) return;
    past.push({ tl: current.value, clips: before });
    if (past.length > 200) past.shift();
    future.length = 0;
    history.value++;
    put(current.value, next);
  }
  function restore(from: Step[], to: Step[]) {
    const s = from.pop();
    if (!s) return;
    to.push({ tl: s.tl, clips: own(s.tl) });
    put(s.tl, s.clips);
    current.value = s.tl;
    history.value++;
  }
  const undo = () => restore(past, future);
  const redo = () => restore(future, past);
  const canUndo = computed(() => history.value >= 0 && past.length > 0);
  const canRedo = computed(() => history.value >= 0 && future.length > 0);

  /** Un rush entier ou une timeline, prêt à poser (null : vide, ou l'imbriquer ferait une boucle). */
  function clipOf(item: MediaItem): TimelineClip | null {
    if (item.rush) {
      const d = project.value.rushes.find((k) => k.id === item.rush)?.duration;
      return d ? { id: newId(), rush: item.rush, in: 0, out: d } : null;
    }
    const d = item.tl && canNest(item.tl) ? lengthOf(item.tl) : 0;
    return d > 0 ? { id: newId(), tl: item.tl, in: 0, out: r3(d) } : null;
  }
  /** Pose des rushes entiers ou des timelines avant le bout `before` (à la fin s'il est nul). */
  function add(items: MediaItem[], before: string | null = null) {
    const added = items.map(clipOf).filter((c): c is TimelineClip => !!c);
    if (added.length) edit((list) => insert(list, added, before));
  }

  /** Nouvelle timeline (vide, ou avec ces bouts), qui s'ouvre. La globale est figée : elle ne suit plus les rushes. */
  function create(name: string, list: TimelineClip[] = []) {
    const id = `t${Math.random().toString(36).slice(2, 8)}`;
    const frozen = timelines.value.map((k) => (k.clips === null ? { ...k, clips: own(k.id) } : k));
    save([...frozen, { id, name, clips: list }]);
    current.value = id;
    return id;
  }
  function rename(id: string, name: string) {
    save(timelines.value.map((k) => (k.id === id ? { ...k, name: name.trim() } : k)));
  }
  /** Supprime une timeline (jamais la globale), et ses imbrications dans les autres. */
  function drop(id: string) {
    if (id === mainId.value) return;
    save(timelines.value.filter((k) => k.id !== id)
      .map((k) => (k.clips?.some((c) => c.tl === id) ? { ...k, clips: k.clips.filter((c) => c.tl !== id) } : k)));
    for (const stack of [past, future]) stack.splice(0, stack.length, ...stack.filter((s) => s.tl !== id));
    history.value++;
  }

  /** Transcriptions des rushes en cours, et leur avancement moyen (%). */
  const transcribing = computed(() => Object.values(project.value.runtime.rush_transcripts)
    .some((r) => !FINISHED.includes(r.status)));
  const progress = computed(() => {
    const all = project.value.rushes.map((r) => project.value.runtime.rush_transcripts[r.id]);
    const sum = all.reduce((a, r) => a + (r?.status === "done" ? 1 : r?.progress ?? 0), 0);
    return all.length ? Math.round(sum / all.length * 100) : 0;
  });
  /** Message de la dernière transcription en échec, s'il y en a une. */
  const transcriptError = computed(() => project.value.rushes
    .map((r) => project.value.runtime.rush_transcripts[r.id])
    .find((r) => r?.status === "error")?.error ?? null);

  return {
    analysis, ready, segsByRush, transcribing, progress, transcriptError,
    timelines, mainId, current, clips, flat, kept, lengthOf, nameOf, canNest,
    edit, undo, redo, canUndo, canRedo, add, create, rename, drop,
  };
}
