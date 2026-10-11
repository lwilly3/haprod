/**
 * Lecture enchaînée de plages de fichiers vidéo dans un seul <video> : les morceaux gardés des
 * rushes mis bout à bout (dérush), ou simplement une vidéo entière (un seul morceau).
 *
 * `t` est la position sur la timeline brute : tous les morceaux bout à bout, coupés compris.
 * Les morceaux coupés (`on: false`) sont sautés pendant la lecture.
 */
import { computed, onMounted, onUnmounted, ref, watch, type Ref } from "vue";

export interface Piece { src: string; start: number; end: number; on: boolean }

const len = (p: Piece) => p.end - p.start;

export function usePlaylist(pieces: Ref<Piece[]>) {
  const video = ref<HTMLVideoElement | null>(null);
  const t = ref(0);
  const playing = ref(false);

  /** Début de chaque morceau sur la timeline brute. */
  const offsets = computed(() => {
    let a = 0;
    return pieces.value.map((p) => { const o = a; a += len(p); return o; });
  });
  /** Temps gardé avant chaque morceau. */
  const keptBefore = computed(() => {
    let k = 0;
    return pieces.value.map((p) => { const o = k; if (p.on) k += len(p); return o; });
  });
  const rawTotal = computed(() => pieces.value.reduce((a, p) => a + len(p), 0));
  const total = computed(() => pieces.value.reduce((a, p) => a + (p.on ? len(p) : 0), 0));

  /** Index du morceau sous la position `time` (-1 sans morceau). */
  function indexAt(time: number): number {
    const o = offsets.value;
    let lo = 0, hi = o.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (o[mid] <= time) lo = mid; else hi = mid - 1;
    }
    return hi < 0 ? -1 : lo;
  }

  const index = computed(() => indexAt(t.value));
  /** Temps gardé déjà lu. */
  const elapsed = computed(() => {
    const i = index.value;
    if (i < 0) return 0;
    const p = pieces.value[i];
    return keptBefore.value[i] + (p.on ? Math.min(t.value - offsets.value[i], len(p)) : 0);
  });

  /** Première position lisible à partir de `time`, null s'il n'y en a plus. */
  function nextOn(time: number): number | null {
    const ps = pieces.value, o = offsets.value;
    for (let i = Math.max(0, indexAt(time)); i < ps.length; i++) {
      if (ps[i].on && o[i] + len(ps[i]) > time) return Math.max(o[i], time);
    }
    return null;
  }

  // fichier chargé dans la vidéo (v.src renvoie une url absolue)
  let loaded = "";

  /** Place la vidéo sur la position `time` de la timeline brute. */
  function place(time: number) {
    t.value = time;
    const v = video.value, i = indexAt(time);
    if (!v || i < 0) return;
    const p = pieces.value[i], at = p.start + Math.min(time - offsets.value[i], len(p));
    if (loaded !== p.src) {
      loaded = p.src;
      v.src = p.src;
      // appliqué une fois le fichier chargé (position de départ par défaut)
      v.currentTime = at;
    } else if (Math.abs(v.currentTime - at) > 0.05) v.currentTime = at;
    if (playing.value) v.play().catch(() => {});
  }

  /** Suit la lecture : position courante, puis morceau suivant (les coupés sont sautés). */
  function follow(ct: number) {
    const ps = pieces.value, o = offsets.value;
    let i = Math.max(0, index.value);
    if (ps[i]?.src !== loaded) i = ps.findIndex((p) => p.src === loaded);
    if (i < 0) {
      // le fichier en cours a disparu (rush retiré) : on reprend au plus près
      const n = nextOn(Math.min(t.value, rawTotal.value));
      return n == null ? stop() : place(n);
    }
    // les morceaux d'un même fichier ne se suivent pas forcément dans l'ordre du fichier :
    // on suit le morceau en cours, et l'on passe au suivant à sa fin
    const p = ps[i];
    if (ct < p.start - 0.5) return;
    if (ct < p.end && p.on) {
      t.value = o[i] + Math.max(0, ct - p.start);
      return;
    }
    const n = nextOn(o[i] + len(p));
    if (n == null) stop(); else place(n);
  }

  let raf = 0;
  function frame() {
    raf = requestAnimationFrame(frame);
    const v = video.value;
    // pendant un saut ou le chargement d'un autre rush, la position n'est pas encore fiable
    if (v && !v.seeking && v.readyState >= HTMLMediaElement.HAVE_METADATA) follow(v.currentTime);
  }

  function play() {
    const n = nextOn(t.value) ?? nextOn(0);
    if (n == null) return;
    playing.value = true;
    place(n);
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(frame);
  }

  function pause() {
    playing.value = false;
    cancelAnimationFrame(raf);
    video.value?.pause();
  }

  /** Fin de la lecture : retour au début, comme dans un lecteur. */
  function stop() {
    pause();
    place(0);
  }

  const toggle = () => (playing.value ? pause() : play());
  const seek = (time: number) => place(Math.max(0, Math.min(time, rawTotal.value)));
  const restart = () => seek(0);

  // nouvelle vidéo, ou morceaux changés à l'arrêt (coupes, ordre des rushes) : on se recale
  watch(video, (v, old) => {
    old?.removeEventListener("ended", onEnded);
    v?.addEventListener("ended", onEnded);
    loaded = "";
  });
  watch([video, pieces], () => {
    if (!playing.value) place(Math.min(t.value, rawTotal.value));
  });
  function onEnded() {
    if (playing.value) follow(Infinity);
  }

  // barre d'espace : lecture / pause, sauf pendant une saisie
  function onKey(e: KeyboardEvent) {
    if (e.code !== "Space" || e.repeat || e.ctrlKey || e.metaKey || e.altKey) return;
    const el = e.target as HTMLElement | null;
    if (el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))) return;
    e.preventDefault();
    // sinon le bouton qui a le focus serait aussi cliqué au relâchement
    if (el?.tagName === "BUTTON") el.blur();
    toggle();
  }
  onMounted(() => window.addEventListener("keydown", onKey));
  onUnmounted(() => {
    window.removeEventListener("keydown", onKey);
    cancelAnimationFrame(raf);
    video.value?.removeEventListener("ended", onEnded);
  });

  return { video, t, playing, index, elapsed, total, rawTotal, toggle, seek, restart };
}

export type Playlist = ReturnType<typeof usePlaylist>;

/** Fait défiler `box` jusqu'à la ligne courante (`[data-li]`), sauf juste après un clic dans la liste. */
export function useFollowScroll(box: Ref<HTMLElement | null>, current: Ref<number>) {
  let skip = false;
  // après le rendu : la ligne est cherchée à sa place actuelle (l'ordre des rushes a pu changer)
  watch(current, (li) => {
    if (skip) { skip = false; return; }
    const el = box.value?.querySelector<HTMLElement>(`[data-li="${li}"]`);
    if (el) box.value!.scrollTo({ top: el.offsetTop - 60, behavior: "smooth" });
  }, { flush: "post" });
  return { skipNext: () => { skip = true; } };
}
