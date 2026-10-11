<script setup lang="ts">
/**
 * Assistant de l'étape Script : discussion avec Claude, éventuellement sur un passage sélectionné.
 * Les plans qu'il propose (motion design, B-roll, images…) s'acceptent ou se refusent un par un.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { usePref } from "../../../lib/composables";
import { toast } from "../../../lib/toast";
import { store } from "../../store";
import type { ChatMessage, Plan, ProposedPlan } from "../../types";
import ChatPanel from "../chat/ChatPanel.vue";
import { colorOf, typeLabel } from "./plans";

const props = defineProps<{
  /** passage sélectionné dans le script */
  quote: string | null;
  /** appelé avant l'envoi (le script en cours de frappe doit être enregistré : Claude le relit) */
  beforeSend?: () => Promise<void>;
  /** les plans du script : une proposition acceptée y est (même id) */
  plans: Plan[];
  /** pose un plan proposé sur le script ; false si son passage est introuvable */
  accept: (p: ProposedPlan) => boolean;
}>();
const emit = defineEmits<{ clearQuote: []; replace: [quote: string, text: string]; show: [p: ProposedPlan] }>();

const { t } = useI18n();
const SUGGESTIONS = computed(() => ["shorten", "punchier", "factCheck", "spoken"].map((k) => t(`script.assistant.suggestions.${k}`)));
const plansAsk = (quote: boolean) =>
  t("script.assistant.plansAsk", { target: t(quote ? "script.assistant.thisPassage" : "script.assistant.wholeScript") });
const short = (t: string) => (t.length > 140 ? t.slice(0, 140) + "…" : t);

/** les propositions refusées (par id), gardées d'une visite à l'autre */
const refused = usePref<string[]>(`script.refused.${store.project!.id}`, []);

const accepted = (p: ProposedPlan) => props.plans.some((x) => x.id === p.id);
const pending = (m: ChatMessage) => (m.plans ?? []).filter((p) => !accepted(p) && !refused.value.includes(p.id));

function acceptOne(p: ProposedPlan): void {
  if (props.accept(p)) toast(t("script.assistant.plansAdded", 1));
}

function acceptAll(m: ChatMessage): void {
  const todo = pending(m);
  const done = todo.filter((p) => props.accept(p)).length;
  if (done) toast(t("script.assistant.plansAdded", done));
}

function refuse(p: ProposedPlan): void {
  refused.value = [...refused.value, p.id];
}

function undo(p: ProposedPlan): void {
  refused.value = refused.value.filter((id) => id !== p.id);
}

async function copy(m: ChatMessage): Promise<void> {
  await navigator.clipboard.writeText(m.text);
  toast(t("chat.copied"));
}
</script>

<template>
  <ChatPanel
    topic="script" :quote="quote" :before-send="beforeSend"
    :empty="t('script.assistant.empty')"
    :placeholder="quote ? t('script.assistant.placeholderQuote') : t('script.assistant.placeholder')"
    @sent="emit('clearQuote')"
  >
    <template #message="{ m }">
      <template v-if="m.plans?.length">
        <div v-for="p in m.plans" :key="p.id" class="proposal" :class="{ off: refused.includes(p.id) }">
          <div class="p-head">
            <span class="swatch" :style="{ background: colorOf(p.type) }" />
            <span class="type">{{ typeLabel(p.type) }}</span>
            <span v-for="f in p.media" :key="f.url" class="file mono" :title="f.name">@{{ f.name }}</span>
            <button class="see" :title="t('script.assistant.showTitle')" @click="emit('show', p)">{{ t("script.assistant.see") }}</button>
          </div>
          <button class="passage" :title="t('script.assistant.showTitle')" @click="emit('show', p)">{{ t("chat.quoted", { q: short(p.passage) }) }}</button>
          <span v-if="p.note" class="note">{{ p.note }}</span>
          <span v-if="p.why" class="why">{{ p.why }}</span>
          <span v-if="accepted(p)" class="done mono">{{ t("script.assistant.accepted") }}</span>
          <span v-else-if="refused.includes(p.id)" class="done mono">
            {{ t("script.assistant.refused") }} · <button class="link-btn" @click="undo(p)">{{ t("script.assistant.undo") }}</button>
          </span>
          <div v-else class="actions">
            <button class="btn sm dark" @click="acceptOne(p)">{{ t("common.accept") }}</button>
            <button class="btn sm" @click="refuse(p)">{{ t("common.reject") }}</button>
          </div>
        </div>
        <button v-if="pending(m).length > 1" class="btn sm all" @click="acceptAll(m)">
          {{ t("script.assistant.acceptAll", { n: pending(m).length }) }}
        </button>
      </template>
      <div v-else-if="m.quote" class="msg-actions">
        <button class="btn sm" @click="emit('replace', m.quote, m.text)">{{ t("script.assistant.replace") }}</button>
        <button class="btn sm" @click="copy(m)">{{ t("common.copy") }}</button>
      </div>
    </template>
    <template #compose="{ send, busy }">
      <div v-if="quote" class="sel">
        <span>{{ t("chat.quoted", { q: short(quote) }) }}</span>
        <button class="x-btn" :title="t('script.assistant.removeQuote')" @click="emit('clearQuote')">×</button>
      </div>
      <div class="chips">
        <template v-if="quote">
          <button v-for="s in SUGGESTIONS" :key="s" :disabled="busy" @click="send(s)">{{ s }}</button>
        </template>
        <button class="plans" :disabled="busy" @click="send(plansAsk(!!quote))">{{ t("script.assistant.proposePlans") }}</button>
      </div>
    </template>
  </ChatPanel>
</template>

<style scoped>
.msg-actions { display: flex; gap: 6px; padding-top: 2px; }
.msg-actions .btn { font-size: 12px; }
.sel { display: flex; gap: 8px; align-items: flex-start; padding: 8px 10px; background: var(--bg-soft); border-radius: 4px; }
.sel span { flex: 1; font-size: 12px; color: var(--ink-3); line-height: 1.45; font-style: italic; }
.sel .x-btn { font-size: 13px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chips button {
  height: 26px; padding: 0 9px; border: 1px solid var(--line-strong); border-radius: 13px;
  background: #fff; font-size: 12px; cursor: pointer;
}
.chips button:hover:not(:disabled) { border-color: var(--faint); }
.chips .plans { font-weight: 500; }

.proposal {
  display: flex; flex-direction: column; gap: 4px; padding: 10px 12px;
  border: 1px solid var(--line); border-radius: 4px; background: #fff;
}
.proposal.off { opacity: 0.55; }
.p-head { display: flex; align-items: center; gap: 6px; min-width: 0; }
.swatch { width: 8px; height: 8px; border-radius: 2px; flex-shrink: 0; }
.type { font-size: 13px; font-weight: 600; }
.file { font-size: 11px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.passage {
  border: none; background: none; padding: 0; font: inherit; font-size: 12px; font-style: italic; color: var(--muted);
  line-height: 1.45; text-align: left; cursor: pointer;
}
.passage:hover { color: var(--ink); text-decoration: underline; }
.see {
  margin-left: auto; flex-shrink: 0; border: none; background: none; padding: 0;
  font-size: 11.5px; color: var(--faint); cursor: pointer; white-space: nowrap;
}
.see:hover { color: var(--ink); text-decoration: underline; }
.note { font-size: 13px; line-height: 1.45; }
.why { font-size: 12px; color: var(--faint); line-height: 1.45; }
.actions { display: flex; gap: 6px; padding-top: 4px; }
.actions .btn, .all { font-size: 12px; }
.all { align-self: flex-start; }
.done { font-size: 11px; color: var(--faint); padding-top: 2px; }
.done .link-btn { font-size: 11px; }
</style>
