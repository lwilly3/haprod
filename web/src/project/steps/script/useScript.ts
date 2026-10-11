/** Le script du projet en blocs et ses plans (script.json côté serveur) : chargement et enregistrement automatique. */
import { onBeforeUnmount, onMounted, ref, shallowRef } from "vue";
import { api, putJson } from "../../../lib/api";
import { t } from "../../../i18n";
import { toast } from "../../../lib/toast";
import { refresh, store } from "../../store";
import type { Plan, Setup } from "../../types";
import type { SaveState } from "./doc";

/** Un bloc du texte : paragraphe, titre, citation, liste… avec son Markdown. L'id ne change pas à l'édition. */
export interface Block { id: string; md: string }

export function useScript(onSaved?: () => void) {
  const url = `/api/projects/${store.project!.id}/script`;
  /** null tant que le script n'est pas chargé */
  const blocks = shallowRef<Block[] | null>(null);
  const plans = shallowRef<Plan[]>([]);
  const setups = shallowRef<Setup[]>([]);
  /** le setup de chaque section : id du bloc titre → id du setup */
  const sections = shallowRef<Record<string, string>>({});
  /** change à chaque chargement depuis le serveur : l'éditeur repart de ces blocs */
  const version = ref(0);
  const state = ref<SaveState>("saved");
  let timer: ReturnType<typeof setTimeout> | undefined;
  let planTimer: ReturnType<typeof setTimeout> | undefined;
  let dirty = false;
  let plansDirty = false;
  let setupTimer: ReturnType<typeof setTimeout> | undefined;
  let setupsDirty = false;

  async function load(): Promise<void> {
    try {
      const data = await api<{ blocks: Block[]; plans: Plan[]; setups: Setup[]; sections: Record<string, string> }>(url);
      blocks.value = data.blocks;
      plans.value = data.plans;
      setups.value = data.setups;
      sections.value = data.sections;
      dirty = plansDirty = false;
      state.value = "saved";
      version.value++;
    } catch (e) {
      toast(t("script.toasts.scriptLoadError", { error: (e as Error).message }), true);
    }
  }

  /** Les blocs modifiés dans l'éditeur ; enregistrés après une pause dans la frappe. */
  function set(value: Block[], delay = 800): void {
    blocks.value = value;
    dirty = true;
    state.value = "saving";
    clearTimeout(timer);
    timer = setTimeout(save, delay);
  }

  async function save(): Promise<void> {
    clearTimeout(timer);
    if (!dirty || blocks.value == null) return;
    dirty = false;
    try {
      await putJson(url, { blocks: blocks.value });
      if (!dirty) state.value = "saved";
      onSaved?.();
    } catch (e) {
      dirty = true;
      state.value = "error";
      toast(t("script.toasts.saveError", { error: (e as Error).message }), true);
    }
  }

  /** Les plans modifiés ; `delay` pour ce qui se tape (une note). */
  function setPlans(value: Plan[], delay = 0): void {
    plans.value = value;
    plansDirty = true;
    clearTimeout(planTimer);
    planTimer = setTimeout(savePlans, delay);
  }

  async function savePlans(): Promise<void> {
    clearTimeout(planTimer);
    if (!plansDirty) return;
    plansDirty = false;
    try {
      await putJson(`${url}/plans`, { plans: plans.value });
      // le décompte des plans de la barre du haut
      refresh().catch(() => {});
    } catch (e) {
      plansDirty = true;
      toast(t("script.toasts.plansSaveError", { error: (e as Error).message }), true);
    }
  }

  function updatePlan(id: string, changes: Partial<Plan>, delay = 0): void {
    setPlans(plans.value.map((p) => (p.id === id ? { ...p, ...changes } : p)), delay);
  }

  function removePlan(id: string): void {
    setPlans(plans.value.filter((p) => p.id !== id));
  }

  /**
   * Les setups et leur affectation aux sections, enregistrés après `delay` (ce qui se tape : un nom) ;
   * un setup supprimé quitte aussi les plans.
   */
  function setSetups(value: Setup[], secs: Record<string, string> = sections.value, delay = 0): void {
    const ids = new Set(value.map((s) => s.id));
    setups.value = value;
    sections.value = Object.fromEntries(Object.entries(secs).filter(([, s]) => ids.has(s)));
    if (plans.value.some((p) => p.setup && !ids.has(p.setup))) {
      setPlans(plans.value.map((p) => (p.setup && !ids.has(p.setup) ? { ...p, setup: "" } : p)));
    }
    setupsDirty = true;
    clearTimeout(setupTimer);
    setupTimer = setTimeout(saveSetups, delay);
  }

  async function saveSetups(): Promise<void> {
    clearTimeout(setupTimer);
    if (!setupsDirty) return;
    setupsDirty = false;
    try {
      await putJson(`${url}/setups`, { setups: setups.value, sections: sections.value });
    } catch (e) {
      setupsDirty = true;
      toast(t("script.toasts.setupsSaveError", { error: (e as Error).message }), true);
    }
  }

  onMounted(load);
  onBeforeUnmount(() => {
    save();
    savePlans();
    saveSetups();
  });
  return {
    blocks, plans, setups, sections, version, state, load, set, save, setPlans, updatePlan, removePlan, setSetups,
  };
}

/** Le script en Markdown, tel que le serveur l'écrit dans script.md. */
export function toMarkdown(blocks: Block[]): string {
  const text = blocks.map((b) => b.md).filter((md) => md.trim()).join("\n\n");
  return text ? text + "\n" : "";
}
