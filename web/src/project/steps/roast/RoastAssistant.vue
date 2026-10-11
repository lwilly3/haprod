<script setup lang="ts">
/**
 * Discussion avec Claude sur un roast : « Discuter » sur une note, une section, une boucle, une
 * promesse ou une remarque la joint au message, pour se la faire expliquer ou la contester.
 */
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { toast } from "../../../lib/toast";
import type { ChatMessage } from "../../types";
import ChatPanel from "../chat/ChatPanel.vue";

const props = defineProps<{
  /** le roast discuté */
  roast: string;
  /** l'élément du roast joint au message */
  quote: string | null;
}>();
const emit = defineEmits<{ clearQuote: [] }>();

const { t } = useI18n();
const SUGGESTIONS = computed(() => ["explain", "fix", "disagree"].map((k) => t(`roast.assistant.suggestions.${k}`)));
const short = (t: string) => (t.length > 180 ? t.slice(0, 180) + "…" : t);

const panel = ref<InstanceType<typeof ChatPanel>>();
watch(() => props.quote, async (q) => {
  if (!q) return;
  await nextTick();
  panel.value?.focus();
});

async function copy(m: ChatMessage): Promise<void> {
  await navigator.clipboard.writeText(m.text);
  toast(t("chat.copied"));
}
</script>

<template>
  <ChatPanel
    ref="panel" topic="roast" :scope="roast" :quote="quote"
    :empty="t('roast.assistant.empty')"
    :placeholder="quote ? t('roast.assistant.placeholderQuote') : t('roast.assistant.placeholder')"
    @sent="emit('clearQuote')"
  >
    <template #message="{ m }">
      <div class="msg-actions">
        <button class="btn sm" @click="copy(m)">{{ t("common.copy") }}</button>
      </div>
    </template>
    <template #compose="{ send, busy }">
      <div v-if="quote" class="sel">
        <span>{{ short(quote) }}</span>
        <button class="x-btn" :title="t('roast.assistant.removeItem')" @click="emit('clearQuote')">×</button>
      </div>
      <div v-if="quote" class="chips">
        <button v-for="s in SUGGESTIONS" :key="s" :disabled="busy" @click="send(s)">{{ s }}</button>
      </div>
    </template>
  </ChatPanel>
</template>

<style scoped>
.msg-actions { display: flex; gap: 6px; padding-top: 2px; }
.msg-actions .btn { font-size: 12px; }
.sel { display: flex; gap: 8px; align-items: flex-start; padding: 8px 10px; background: var(--bg-soft); border-radius: 4px; }
.sel span { flex: 1; font-size: 12px; color: var(--ink-3); line-height: 1.45; white-space: pre-line; }
.sel .x-btn { font-size: 13px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chips button {
  height: 26px; padding: 0 9px; border: 1px solid var(--line-strong); border-radius: 13px;
  background: #fff; font-size: 12px; cursor: pointer;
}
.chips button:hover:not(:disabled) { border-color: var(--faint); }
</style>
