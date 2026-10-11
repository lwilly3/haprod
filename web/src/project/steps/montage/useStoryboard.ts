/**
 * Le storyboard du motion design : généré par Daryl (relu tant qu'il écrit), retouché ici
 * (cocher, supprimer, réécrire « on montre », déplacer ou tirer un beat sur la timeline), enregistré peu après
 * chaque retouche. On y pose aussi des beats à la main, depuis la timeline du montage.
 */
import { computed, onUnmounted, ref } from "vue";
import { api, post, putJson } from "../../../lib/api";
import { toast } from "../../../lib/toast";
import type { Beat, BeatType, StoryboardView } from "./types";

export function useStoryboard(pid: string) {
  const base = `/api/projects/${pid}/montage/storyboard`;
  const view = ref<StoryboardView | null>(null);
  const busy = computed(() => !!view.value?.job && !view.value.job.finished);
  /** Daryl répond dans le chat : ses changements arrivent à la fin, on ne retouche pas pendant ce temps */
  const chatBusy = computed(() => !!view.value?.chat.busy);
  /** des animations de beats en file ou en cours */
  const animating = computed(() => Object.values(view.value?.anim_jobs ?? {}).some((a) => a.status === "queued" || a.status === "running"));

  let timer: ReturnType<typeof setTimeout> | undefined;
  let saveTimer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;
  let pending = false;

  async function load() {
    try {
      const v = await api<StoryboardView>(base);
      // une retouche pas encore enregistrée n'est pas écrasée
      if (!pending) view.value = v;
    } catch { /* on réessaie */ }
  }
  async function poll() {
    await load();
    if (stopped) return;
    timer = setTimeout(poll, busy.value || chatBusy.value || animating.value ? 1500 : 8000);
  }
  poll();
  onUnmounted(() => { stopped = true; clearTimeout(timer); clearTimeout(saveTimer); });

  async function run(density: string, note: string, types: string[]) {
    try {
      view.value = await post<StoryboardView>(base, { density, note, types });
      clearTimeout(timer);
      timer = setTimeout(poll, 1500);
    } catch (e) {
      toast((e as Error).message, true);
    }
  }

  async function send(text: string, at: number | null, beat: string | null, frame: boolean) {
    await flush();
    try {
      view.value = await post<StoryboardView>(`${base}/chat`, { text, at, beat, frame });
      clearTimeout(timer);
      timer = setTimeout(poll, 1500);
    } catch (e) {
      toast((e as Error).message, true);
    }
  }

  /** Fait entrer ces beats au montage (tous les beats cochés pas encore faits sans `beats`) : zooms et B-roll
   * vidéo posés tout de suite, une tâche d'animation pour les autres. */
  async function animate(beats?: string[]) {
    await flush();
    try {
      const r = await post<{ queued: string[]; placed: string[]; skipped: string[]; missing: string[] }>(`${base}/animate`, { beats: beats ?? null });
      await load();
      clearTimeout(timer);
      timer = setTimeout(poll, 1500);
      return r;
    } catch (e) {
      toast((e as Error).message, true);
      return null;
    }
  }

  /** Pose un beat à la main (un motion, par défaut) ; rend son id. */
  async function add(at: number, dur: number, type: BeatType = "motion", show = ""): Promise<string | null> {
    await flush();
    try {
      const v = await post<StoryboardView & { added: string }>(`${base}/beats`, { type, at, dur, show });
      view.value = v;
      return v.added;
    } catch (e) {
      toast((e as Error).message, true);
      return null;
    }
  }

  async function stopAnim(beat: string) {
    view.value = await post<StoryboardView>(`${base}/animate/stop`, { beat });
  }

  async function stopChat() {
    view.value = await post<StoryboardView>(`${base}/chat/stop`);
  }

  async function stop() {
    view.value = await post<StoryboardView>(`${base}/stop`);
  }

  /** Applique une retouche aux beats, enregistrée peu après (les frappes rapprochées sont regroupées). */
  function edit(change: (beats: Beat[]) => Beat[] | void, delay = 600) {
    const board = view.value?.board;
    if (!board || busy.value || chatBusy.value) return;
    board.beats = change(board.beats) ?? board.beats;
    pending = true;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(flush, delay);
  }

  async function flush() {
    clearTimeout(saveTimer);
    const board = view.value?.board;
    if (!pending || !board) return;
    const sent = JSON.stringify(board.beats);
    try {
      const v = await putJson<StoryboardView>(base, {
        beats: board.beats.map((b) => ({
          id: b.id, type: b.type, show: b.show, kind: b.kind, place: b.place, anim: b.anim ?? "", sfx: b.sfx, on: b.on,
          zoom: b.zoom, src: b.src, search: b.search, start: b.start, enter: b.enter ?? null, exit: b.exit ?? null,
          at: b.at, dur: b.dur,
        })),
      });
      if (JSON.stringify(view.value?.board?.beats) === sent) {
        pending = false;
        view.value = v;
      } else if (view.value) {
        // retouché pendant l'envoi : on garde l'écran, seuls les contrôles sont repris
        view.value.checks = v.checks;
      }
    } catch (e) {
      pending = false;
      toast((e as Error).message, true);
      await load();
    }
  }

  return { view, busy, chatBusy, animating, run, stop, send, stopChat, animate, add, stopAnim, edit, flush, load };
}

export type StoryboardState = ReturnType<typeof useStoryboard>;
