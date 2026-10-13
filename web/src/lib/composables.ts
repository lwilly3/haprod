import { onMounted, onUnmounted, ref, watch, type Ref } from "vue";

/** Valeur memorisee dans le navigateur d'une session a l'autre. */
export function usePref<T>(key: string, initial: T): Ref<T> {
  const saved = localStorage.getItem("studio." + key);
  const value = ref(saved != null ? JSON.parse(saved) : initial) as Ref<T>;
  watch(value, (v) => localStorage.setItem("studio." + key, JSON.stringify(v)), { deep: true });
  return value;
}

/** Appelle `tick` en boucle tant que le composant est affiche ; `tick` renvoie le delai suivant (ms). */
export function usePolling(tick: () => Promise<number>) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;
  async function loop() {
    let delay = 3000;
    try {
      delay = await tick();
    } catch (e) {
      // une erreur ne doit pas arrêter le rafraîchissement pour de bon
      console.error(e);
    }
    if (!stopped) timer = setTimeout(loop, delay);
  }
  onMounted(loop);
  onUnmounted(() => { stopped = true; clearTimeout(timer); });
}

/**
 * Sous Windows, relâcher Alt donne le focus au menu de Chrome (et Espace l'ouvre ensuite). Après un
 * Alt+molette, on annule ce relâchement : appeler la fonction renvoyée à chaque molette avec Alt.
 */
export function useAltWheel(): () => void {
  let used = false;
  const onKeyUp = (e: KeyboardEvent) => {
    if (e.key !== "Alt") return;
    if (used) e.preventDefault();
    used = false;
  };
  onMounted(() => window.addEventListener("keyup", onKeyUp));
  onUnmounted(() => window.removeEventListener("keyup", onKeyUp));
  return () => { used = true; };
}
