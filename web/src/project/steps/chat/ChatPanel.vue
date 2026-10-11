<script setup lang="ts">
/**
 * Panneau de discussion avec Claude, partagé par les étapes. Chaque sujet (angle, script, roast) a ses
 * discussions, chacune avec sa propre session Claude : on en ouvre une nouvelle quand on change de sujet.
 * Celles du roast portent sur un roast précis (`scope`).
 * Événements : `sent` (message parti), `replied` (Claude a fini de répondre).
 * Slots : `message` (sous une réponse de Claude), `compose` (au-dessus de la saisie).
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api, post } from "../../../lib/api";
import { toast } from "../../../lib/toast";
import { store } from "../../store";
import type { ChatMessage, ChatState } from "../../types";

const props = defineProps<{
  topic: "angle" | "script" | "roast";
  /** pour le roast : l'id du roast discuté */
  scope?: string;
  empty: string;
  placeholder: string;
  /** passage joint au message */
  quote?: string | null;
  /** appelé avant l'envoi (ex. enregistrer le script en cours de frappe : Claude le relit) */
  beforeSend?: () => Promise<void>;
}>();
const emit = defineEmits<{ sent: []; replied: [] }>();
const { t } = useI18n();

const url = `/api/projects/${store.project!.id}/chat/${props.topic}`;
const scoped = props.scope ? `scope=${encodeURIComponent(props.scope)}` : "";
const chat = ref<ChatState>({ thread: null, threads: [], messages: [], busy: false, error: null, activity: null });
const input = ref("");
const sending = ref(false);
const scroller = ref<HTMLElement>();
const box = ref<HTMLTextAreaElement>();

const load = (thread: string | null) => {
  const query = [thread ? `thread=${thread}` : "", scoped].filter(Boolean).join("&");
  return api<ChatState>(query ? `${url}?${query}` : url);
};
let timer: ReturnType<typeof setTimeout> | undefined;

const short = (t: string) => (t.length > 140 ? t.slice(0, 140) + "…" : t);

/** Relit la discussion toutes les 1,5 s tant que Claude rédige. */
function schedule(): void {
  clearTimeout(timer);
  if (!chat.value.busy) return;
  timer = setTimeout(async () => {
    try {
      receive(await load(chat.value.thread));
    } catch {
      schedule();
    }
  }, 1500);
}

function receive(state: ChatState): void {
  if (chat.value.busy && !state.busy) emit("replied");
  chat.value = state;
  schedule();
}

onMounted(async () => {
  try {
    receive(await load(null));
  } catch (e) {
    toast((e as Error).message, true);
  }
});
onBeforeUnmount(() => clearTimeout(timer));

watch(() => [chat.value.messages.length, chat.value.busy], async () => {
  await nextTick();
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight });
});

async function send(text: string): Promise<void> {
  const q = text.trim();
  if (!q || chat.value.busy || sending.value) return;
  sending.value = true;
  try {
    await props.beforeSend?.();
    receive(await post<ChatState>(url, { text: q, quote: props.quote ?? null, thread: chat.value.thread, scope: props.scope ?? null }));
    input.value = "";
    emit("sent");
  } catch (e) {
    toast((e as Error).message, true);
  } finally {
    sending.value = false;
  }
}

/** Une discussion vierge : elle n'existe côté serveur qu'au premier message. */
function newThread(): void {
  clearTimeout(timer);
  chat.value = { thread: null, threads: chat.value.threads, messages: [], busy: false, error: null, activity: null };
}

async function openThread(id: string): Promise<void> {
  if (!id) return newThread();
  try {
    receive(await load(id));
  } catch (e) {
    toast((e as Error).message, true);
  }
}

function onKey(e: KeyboardEvent): void {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send(input.value);
  }
}

defineExpose({ focus: () => box.value?.focus() });

defineSlots<{
  message?: (props: { m: ChatMessage }) => unknown;
  compose?: (props: { send: (text: string) => void; busy: boolean }) => unknown;
}>();
</script>

<template>
  <div class="assistant">
    <div class="head">
      <span class="name">{{ t("common.assistant") }}</span>
      <select v-if="chat.threads.length" class="threads" :value="chat.thread ?? ''" :title="t('chat.previous')"
        @change="openThread(($event.target as HTMLSelectElement).value)">
        <option v-if="!chat.thread" value="">{{ t("chat.newThread") }}</option>
        <option v-for="t in chat.threads" :key="t.id" :value="t.id">{{ t.title }}</option>
      </select>
      <span v-else class="spacer" />
      <button class="new" :disabled="!chat.thread" @click="newThread">{{ t("chat.newThread") }}</button>
    </div>
    <div ref="scroller" class="thread">
      <span v-if="!chat.messages.length && !chat.busy" class="empty">{{ empty }}</span>
      <div v-for="(m, i) in chat.messages" :key="i" class="msg" :class="m.role">
        <span v-if="m.role === 'user' && m.quote" class="quote">{{ t("chat.quoted", { q: short(m.quote) }) }}</span>
        <span v-if="m.text" class="text">{{ m.text }}</span>
        <slot v-if="m.role === 'ai'" name="message" :m="m" />
      </div>
      <span v-if="chat.busy" class="busy">{{ t("chat.writing") }}<template v-if="chat.activity"> · {{ chat.activity }}</template></span>
      <span v-if="chat.error" class="error">{{ chat.error }}</span>
    </div>
    <div class="compose">
      <slot name="compose" :send="send" :busy="chat.busy" />
      <div class="row">
        <textarea ref="box" v-model="input" rows="2" :placeholder="placeholder" @keydown="onKey" />
        <button class="btn md red" :disabled="chat.busy || sending || !input.trim()" @click="send(input)">{{ t("common.send") }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.assistant {
  display: flex; flex-direction: column; flex: 1 1 280px; max-width: 340px; min-width: 260px;
  height: calc(100vh - 252px); min-height: 498px; border: 1px solid var(--line); border-radius: 4px; background: #fff;
}
.head { display: flex; align-items: center; gap: 8px; padding: 10px 14px; border-bottom: 1px solid var(--line-soft); }
.name { font-size: 13.5px; font-weight: 600; flex-shrink: 0; }
.threads {
  flex: 1; min-width: 0; height: 26px; border: 1px solid var(--line); border-radius: 4px; background: #fff;
  font-size: 12px; color: var(--muted); padding: 0 4px; cursor: pointer; text-overflow: ellipsis;
}
.new { flex-shrink: 0; border: none; background: none; padding: 0; font-size: 12px; color: var(--faint); cursor: pointer; white-space: nowrap; }
.new:hover:not(:disabled) { color: var(--ink); text-decoration: underline; }
.new:disabled { color: var(--off-2); cursor: default; }
.thread { flex: 1; overflow: auto; padding: 14px; display: flex; flex-direction: column; gap: 14px; }
.empty { font-size: 13px; color: var(--faint); line-height: 1.55; }
.msg { display: flex; flex-direction: column; gap: 6px; max-width: 92%; border-radius: 6px; }
.msg.user { align-self: flex-end; padding: 8px 10px; background: var(--bg-soft); }
.msg.ai { align-self: flex-start; }
.quote { font-size: 12px; color: var(--muted); line-height: 1.5; font-style: italic; }
.text { font-size: 13.5px; line-height: 1.55; white-space: pre-wrap; }
.busy { font-family: var(--mono); font-size: 12px; color: var(--faint); }
.error { font-size: 12.5px; color: var(--red-ink); line-height: 1.45; }
.compose { display: flex; flex-direction: column; gap: 8px; padding: 12px; border-top: 1px solid var(--line-soft); }
.row { display: flex; gap: 8px; align-items: flex-end; }
.row textarea {
  flex: 1; border: 1px solid var(--line-input); border-radius: 4px; padding: 8px 10px;
  font-size: 13.5px; line-height: 1.45; resize: none;
}
</style>
