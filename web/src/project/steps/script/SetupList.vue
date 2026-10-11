<script setup lang="ts">
/**
 * Les setups de tournage : les créer, les nommer, copier le texte de chacun pour le prompteur, ou les
 * exporter tous dans un fichier texte (un setup après l'autre).
 */
import { useI18n } from "vue-i18n";
import ConfirmX from "../../../components/ConfirmX.vue";
import { duration } from "../../../lib/format";
import { toast } from "../../../lib/toast";
import { store } from "../../store";
import type { Setup } from "../../types";
import { letterOf, newSetup, setupColor, type SetupStat, setupText, type Spoken } from "./setups";

const props = defineProps<{ setups: Setup[]; stats: Record<string, SetupStat>; parts: Spoken[] }>();
const emit = defineEmits<{ change: [setups: Setup[], delay?: number] }>();

const { t } = useI18n();
const value = (e: Event) => (e.target as HTMLInputElement).value;

function edit(id: string, changes: Partial<Setup>): void {
  emit("change", props.setups.map((s) => (s.id === id ? { ...s, ...changes } : s)), 500);
}

/** Le texte de tous les setups, chacun sous son titre, dans un fichier .txt. */
function exportAll(): void {
  const named = [...props.setups.map((s, n) => ({ id: s.id, title: `${letterOf(n)}${s.name ? ` · ${s.name}` : ""}` })),
    { id: "", title: t("shoot.noSetup") }];
  const text = named.flatMap(({ id, title }) => {
    const t = setupText(props.parts, id);
    return t ? [`=== ${title} ===\n\n${t}`] : [];
  }).join("\n\n\n") + "\n";
  const slug = (store.project?.title ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/\W+/g, "-")
    .replace(/^-|-$/g, "").toLowerCase() || "script";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  a.download = `${slug}-${t("shoot.setups.fileSuffix")}.txt`;
  a.click();
  URL.revokeObjectURL(a.href);
}

const hasText = () => Object.values(props.stats).some((s) => s.seconds > 0);

async function copy(id: string): Promise<void> {
  const text = setupText(props.parts, id);
  if (!text) return;
  await navigator.clipboard.writeText(text);
  const at = props.setups.findIndex((s) => s.id === id);
  toast(at >= 0 ? t("shoot.setupCopied", { letter: letterOf(at) }) : t("shoot.noSetupCopied"));
}
</script>

<template>
  <div class="setups">
    <div class="head">
      <span class="title">{{ t("shoot.setups.title") }}</span>
      <span class="actions">
        <button v-if="setups.length" class="btn sm" :disabled="!hasText()" :title="t('shoot.setups.exportTitle')"
          @click="exportAll">{{ t("shoot.setups.export") }}</button>
        <button class="btn sm" @click="emit('change', [...setups, newSetup()])">{{ t("shoot.setups.add") }}</button>
      </span>
    </div>
    <p v-if="!setups.length" class="hint">
      {{ t("shoot.setups.hint") }}
    </p>
    <div v-for="(st, n) in setups" :key="st.id" class="setup">
      <div class="top">
        <span class="badge mono" :style="{ background: setupColor(n) }">{{ letterOf(n) }}</span>
        <input class="name" :value="st.name" :placeholder="t('shoot.setups.namePlaceholder')" @input="edit(st.id, { name: value($event) })">
        <ConfirmX :title="t('shoot.setups.deleteTitle')" @confirm="emit('change', setups.filter((s) => s.id !== st.id))" />
      </div>
      <input class="note" :value="st.note" :placeholder="t('shoot.setups.notePlaceholder')" @input="edit(st.id, { note: value($event) })">
      <div class="foot">
        <span class="mono">{{ t("shoot.setups.plans", stats[st.id]?.plans ?? 0) }} · {{ t("shoot.textLength", { d: duration(stats[st.id]?.seconds ?? 0) }) }}</span>
        <span class="spacer" />
        <button class="btn sm" :disabled="!stats[st.id]?.seconds" @click="copy(st.id)">{{ t("shoot.copyText") }}</button>
      </div>
    </div>
    <div v-if="setups.length && stats['']?.seconds" class="setup none">
      <div class="foot">
        <i18n-t keypath="shoot.setups.noSetupText" tag="span"><template #d><span class="mono">{{ duration(stats[''].seconds) }}</span></template></i18n-t>
        <span class="spacer" />
        <button class="btn sm" @click="copy('')">{{ t("common.copy") }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.setups { display: flex; flex-direction: column; gap: 8px; }
.head { display: flex; align-items: center; justify-content: space-between; }
.actions { display: flex; gap: 6px; }
.title { font-size: 13px; font-weight: 600; color: var(--ink-2); }
.hint { margin: 0; font-size: 12.5px; line-height: 1.5; color: var(--faint); }
.setup {
  border: 1px solid var(--line); border-radius: 6px; padding: 9px 11px; background: #fff;
  display: flex; flex-direction: column; gap: 5px;
}
.setup.none { background: var(--bg-softer); }
.top { display: flex; align-items: center; gap: 8px; }
.badge {
  width: 20px; height: 20px; border-radius: 4px; color: #fff; font-size: 11.5px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
}
.name, .note { border: none; padding: 0; background: transparent; min-width: 0; flex: 1; }
.name { font-size: 13.5px; color: var(--ink); }
.note { font-size: 12.5px; color: var(--muted); }
.app .name:focus, .app .note:focus { outline: none; }
.foot { display: flex; align-items: center; gap: 8px; font-size: 11.5px; color: var(--muted-2); }
.spacer { flex: 1; }
</style>
