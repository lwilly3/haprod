/** Un document Markdown du projet (script.md, notes.md, recherche.md) : chargement et enregistrement automatique. */
import { onBeforeUnmount, onMounted, ref } from "vue";
import { api, putJson } from "../../../lib/api";
import { t } from "../../../i18n";
import { toast } from "../../../lib/toast";
import { store } from "../../store";

export type SaveState = "saved" | "saving" | "error";

export function useDoc(name: string, onSaved?: () => void) {
  const url = `/api/projects/${store.project!.id}/docs/${name}`;
  /** null tant que le document n'est pas chargé */
  const content = ref<string | null>(null);
  const state = ref<SaveState>("saved");
  let timer: ReturnType<typeof setTimeout> | undefined;
  let dirty = false;

  async function load(): Promise<void> {
    try {
      content.value = (await api<{ content: string }>(url)).content;
    } catch (e) {
      toast(t("script.toasts.docLoadError", { name, error: (e as Error).message }), true);
    }
  }

  /** Modifie le texte ; enregistré après une pause dans la frappe. */
  function set(value: string, delay = 800): void {
    content.value = value;
    dirty = true;
    state.value = "saving";
    clearTimeout(timer);
    timer = setTimeout(save, delay);
  }

  async function save(): Promise<void> {
    clearTimeout(timer);
    if (!dirty || content.value == null) return;
    dirty = false;
    try {
      await putJson(url, { content: content.value });
      if (!dirty) state.value = "saved";
      onSaved?.();
    } catch (e) {
      dirty = true;
      state.value = "error";
      toast(t("script.toasts.saveError", { error: (e as Error).message }), true);
    }
  }

  onMounted(load);
  onBeforeUnmount(save);
  return { content, state, load, set, save };
}
