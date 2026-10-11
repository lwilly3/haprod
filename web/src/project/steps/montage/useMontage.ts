/**
 * L'état du montage : la timeline (modifiée tout de suite à l'écran, enregistrée peu après),
 * le chat avec le monteur, et les médias. Le monteur travaille sur sa copie : on continue de monter
 * pendant ce temps, ses changements sont fusionnés à la fin de son tour (les nôtres l'emportent).
 */
import { computed, onUnmounted, ref } from "vue";
import { api, post, putJson } from "../../../lib/api";
import { toast } from "../../../lib/toast";
import { clone, totalOf, type AvailableMedia, type MontageView, type Selection, type Shot, type Timeline } from "./types";

export function useMontage(pid: string) {
  const base = `/api/projects/${pid}/montage`;
  const view = ref<MontageView | null>(null);
  const tl = ref<Timeline | null>(null);
  const available = ref<AvailableMedia[]>([]);
  /** modifié à l'écran, pas encore enregistré */
  const dirty = ref(false);
  /** un glisser en cours : on n'écrase rien */
  const holding = ref(false);

  const busy = computed(() => !!view.value?.chat.busy);
  const total = computed(() => (tl.value ? totalOf(tl.value) : 0));

  /** la version du serveur dont vient la timeline à l'écran : une retouche faite dessus y est fusionnée si elle a changé */
  let rev = "";

  function receive(v: MontageView, force = false) {
    view.value = v;
    if (force || (!dirty.value && !holding.value)) {
      tl.value = clone(v.timeline);
      rev = v.rev;
    }
  }

  async function load(force = false) {
    receive(await api<MontageView>(base), force);
  }

  let timer: ReturnType<typeof setTimeout> | undefined;
  let saveTimer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;
  async function poll() {
    try {
      await load();
    } catch { /* on réessaie */ }
    if (stopped) return;
    const v = view.value;
    const rendering = v ? Object.values(v.motions).some((m) => !["ready", "none", "error"].includes(m.render)) : false;
    timer = setTimeout(poll, busy.value ? 1200 : rendering || v?.analysis.pending ? 2500 : 6000);
  }
  poll();
  onUnmounted(() => { stopped = true; clearTimeout(timer); clearTimeout(saveTimer); });

  /** Enregistre la timeline (regroupe les modifications rapprochées). */
  function save(delay = 500) {
    dirty.value = true;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(flush, delay);
  }

  // les insertions dans l'A-roll pas encore envoyées : le serveur y décale les beats du storyboard (et l'annulation
  // les remet en place)
  let shifts: { at: number; length: number }[] = [];
  /** Une insertion de `length` s à `at` dans l'A-roll : envoyée avec le prochain enregistrement. */
  function shiftBeats(at: number, length: number) {
    shifts.push({ at, length });
  }

  async function flush() {
    clearTimeout(saveTimer);
    if (!dirty.value || !tl.value) return;
    const sent = clone(tl.value);
    const beats_shift = shifts;
    shifts = [];
    try {
      const v = await putJson<MontageView>(base, { timeline: sent, beats_shift, rev });
      // rien n'a bougé depuis l'envoi : la version du serveur (nettoyée) fait foi
      const same = JSON.stringify(sent) === JSON.stringify(tl.value);
      if (same) dirty.value = false;
      receive(v, same);
    } catch (e) {
      toast((e as Error).message, true);
      dirty.value = false;
      await load(true);
    }
  }

  /** Applique une modification à la timeline. */
  function edit(change: (tl: Timeline) => void, delay = 300): boolean {
    if (!tl.value) return false;
    change(tl.value);
    save(delay);
    return true;
  }

  async function undo() {
    await flush();
    try {
      receive(await post<MontageView>(`${base}/undo`), true);
    } catch (e) {
      toast((e as Error).message, true);
    }
  }

  /** `shot` : l'image en pause dont on parle ; `fresh` : dans une nouvelle discussion. */
  async function send(text: string, selection: Selection | null, shot: Shot | null = null, fresh = false) {
    await flush();
    try {
      receive(await post<MontageView>(`${base}/chat`, { text, selection, frame: shot?.t ?? null, image: shot?.image ?? null, fresh }), true);
      return true;
    } catch (e) {
      toast((e as Error).message, true);
      return false;
    }
  }

  async function stop() {
    receive(await post<MontageView>(`${base}/stop`), true);
  }

  async function exportResolve(): Promise<{ rel: string; name: string; problems: string[] } | null> {
    await flush();
    try {
      return await post(`${base}/export`);
    } catch (e) {
      toast((e as Error).message, true);
      return null;
    }
  }

  async function loadAvailable() {
    try {
      available.value = await api<AvailableMedia[]>(`${base}/media`);
    } catch { /* la liste reste vide */ }
  }
  loadAvailable();

  return { view, tl, available, dirty, holding, busy, total, edit, shiftBeats, save, flush, undo, send, stop, exportResolve, load, loadAvailable };
}

export type MontageState = ReturnType<typeof useMontage>;
