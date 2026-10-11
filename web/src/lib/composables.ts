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
