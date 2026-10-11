<script setup lang="ts">
/** Assistant de l'étape Angle : discuter du choix de l'angle ; les angles que Claude propose s'ajoutent d'un clic. */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { toast } from "../../../lib/toast";
import { act, refresh, store } from "../../store";
import type { ProposedAngle } from "../../types";
import ChatPanel from "../chat/ChatPanel.vue";

const { t } = useI18n();
const SUGGESTIONS = computed(() => [
  t("angle.assistant.chips.recommend"), t("angle.assistant.chips.mix"), t("angle.assistant.chips.personal"), t("angle.assistant.chips.edgy"),
]);

/** angles déjà ajoutés depuis cette discussion (par titre) */
const added = ref(new Set<string>());

const known = (a: ProposedAngle) => added.value.has(a.title) || store.project!.angles.some((x) => x.t === a.title);

async function add(a: ProposedAngle, select: boolean): Promise<void> {
  if (await act("/angles/add", { ...a, select })) {
    added.value.add(a.title);
    toast(select ? t("angle.assistant.addedKept") : t("angle.assistant.added"));
  }
}
</script>

<template>
  <ChatPanel
    topic="angle"
    :empty="t('angle.assistant.empty')"
    :placeholder="t('angle.assistant.placeholder')"
    @replied="refresh().catch(() => {})"
  >
    <template #message="{ m }">
      <div v-for="a in m.angles ?? []" :key="a.title" class="proposal">
        <span class="t">{{ a.title }}</span>
        <span class="p">{{ a.promise }}</span>
        <span v-if="a.why" class="why">{{ a.why }}</span>
        <span v-if="known(a)" class="done mono">{{ t("angle.assistant.inList") }}</span>
        <div v-else class="actions">
          <button class="btn sm dark" @click="add(a, true)">{{ t("angle.assistant.addKeep") }}</button>
          <button class="btn sm" @click="add(a, false)">{{ t("angle.assistant.addToAngles") }}</button>
        </div>
      </div>
    </template>
    <template #compose="{ send, busy }">
      <div class="chips">
        <button v-for="s in SUGGESTIONS" :key="s" :disabled="busy" @click="send(s)">{{ s }}</button>
      </div>
    </template>
  </ChatPanel>
</template>

<style scoped>
.proposal {
  display: flex; flex-direction: column; gap: 4px; padding: 10px 12px;
  border: 1px solid var(--line); border-radius: 4px; background: #fff;
}
.proposal .t { font-size: 13.5px; font-weight: 600; line-height: 1.35; }
.proposal .p { font-size: 12.5px; color: var(--muted); }
.proposal .why { font-size: 12px; color: var(--faint); line-height: 1.45; }
.actions { display: flex; gap: 6px; flex-wrap: wrap; padding-top: 4px; }
.actions .btn { font-size: 12px; }
.done { font-size: 11px; color: var(--faint); padding-top: 2px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chips button {
  height: 26px; padding: 0 9px; border: 1px solid var(--line-strong); border-radius: 13px;
  background: #fff; font-size: 12px; cursor: pointer;
}
.chips button:hover:not(:disabled) { border-color: var(--faint); }
</style>
