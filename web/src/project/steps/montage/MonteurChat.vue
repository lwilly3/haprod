<script setup lang="ts">
/**
 * Une demande au monteur (Claude) et sa conversation, ou une nouvelle demande (`task` null), mise en file :
 * on peut en lancer d'autres sans attendre. Une demande porte sur la sélection en cours (élément ou plage),
 * affichée au-dessus de la saisie, ou sur l'image en pause, avec son timecode et la capture jointes.
 */
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { store } from "../../store";
import { tcd, trackLabel, type MontageTask, type Selection, type Shot } from "./types";

const props = defineProps<{
  task: MontageTask | null; usage: Record<string, number> | null; selection: Selection | null; describe: (s: Selection) => string;
}>();
const emit = defineEmits<{ send: [string, Selection | null, Shot | null]; stop: []; pick: [Selection]; seek: [number] }>();

const { t } = useI18n();
const input = ref("");
const box = ref<HTMLTextAreaElement>();
const thread = ref<HTMLElement>();
/** la sélection jointe à la demande ; retirée avec × (la demande porte alors sur toute la vidéo) */
const attach = ref(true);
watch(() => JSON.stringify(props.selection), () => { attach.value = true; });
const target = computed(() => (attach.value ? props.selection : null));
/** l'image en pause dont on parle (son temps et sa capture), jointe à la demande */
const shot = ref<Shot | null>(null);
const messages = computed(() => props.task?.messages ?? []);
/** Daryl traite la demande, ou elle attend son tour : on ne peut pas y répondre */
const busy = computed(() => props.task?.status === "queued" || props.task?.status === "running");

const CHIPS = computed(() => (shot.value ? [] : target.value
  ? ["motion", "broll", "zooms", "sound"].map((k) => t(`editing.chat.chipsSelection.${k}`))
  : ["chapters", "music", "zooms"].map((k) => t(`editing.chat.chipsVideo.${k}`))));

watch(() => [props.task?.id, messages.value.length, messages.value.at(-1)?.text.length, props.task?.status, props.task?.activity], async () => {
  await nextTick();
  thread.value?.scrollTo({ top: thread.value.scrollHeight });
}, { immediate: true });

function send(text = input.value) {
  if (!text.trim() || busy.value) return;
  emit("send", text.trim(), target.value, shot.value);
  input.value = "";
  shot.value = null;
}
function onKey(e: KeyboardEvent) {
  e.stopPropagation();
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}
const ref_ = (s: Selection) => {
  if ("range" in s) return `${tcd(s.range[0])} → ${tcd(s.range[1])}`;
  const what = `${trackLabel(s.item.track)} ${s.item.id}`;
  return s.item.fx ? t("transitions.of", { item: what }) : what;
};

/** Pré-remplit la saisie (Commenter, demandes de l'inspecteur). */
async function compose(text = "") {
  attach.value = true;
  if (text) input.value = text;
  await nextTick();
  box.value?.focus();
}
/** Joint l'image en pause dont le client veut parler (à la place de la sélection). */
async function frame(at: Shot) {
  shot.value = at;
  attach.value = false;
  await nextTick();
  box.value?.focus();
}
const fileUrl = (rel: string) => `/api/projects/${store.project?.id}/files/${rel}`;
defineExpose({ compose, send, frame });
</script>

<template>
  <div class="chat">
    <div ref="thread" class="thread">
      <span v-if="!messages.length" class="empty">{{ t("editing.chat.empty") }}</span>
      <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
        <img v-if="m.role === 'user' && m.image" class="shot" :src="fileUrl(m.image)" alt="" @click="emit('seek', m.frame!)">
        <span v-if="m.role === 'user' && m.frame != null" class="ref mono" @click="emit('seek', m.frame!)">{{ t("editing.chat.frameRef", { tc: tcd(m.frame) }) }}</span>
        <span v-if="m.role === 'user' && m.selection" class="ref mono" @click="emit('pick', m.selection!)">{{ ref_(m.selection) }}</span>
        <span v-if="m.text" class="text">{{ m.text }}</span>
        <span v-if="m.role === 'ai' && m.tools?.length" class="tools mono" :title="m.tools.join(' · ')">{{ t("editing.chat.actions", m.tools.length) }}{{ m.changed ? t("editing.chat.timelineChanged") : "" }}</span>
      </div>
      <span v-if="task?.status === 'queued'" class="busy mono">{{ t("editing.chat.queued") }}</span>
      <span v-else-if="task?.status === 'running'" class="busy mono">{{ task.activity ? `${task.activity}…` : "…" }}</span>
      <span v-if="task?.error" class="error">{{ task.error }}</span>
    </div>
    <div class="compose">
      <div class="chips">
        <button v-for="c in CHIPS" :key="c" class="chip" :disabled="busy" @click="send(c)">{{ c }}</button>
      </div>
      <div v-if="shot" class="ctx">
        <img v-if="shot.image" class="shot sm" :src="shot.image" alt="">
        <span class="mono">{{ t("editing.chat.frame", { tc: tcd(shot.t) }) }}</span>
        <button class="x-btn" :title="t('editing.chat.noFrame')" @click="shot = null">×</button>
      </div>
      <div v-if="target" class="ctx">
        <span class="mono">{{ describe(target) }}</span>
        <button class="x-btn" :title="t('editing.chat.wholeVideo')" @click="attach = false">×</button>
      </div>
      <textarea ref="box" v-model="input" rows="3" :disabled="busy"
        :placeholder="t(busy ? 'editing.chat.busy' : shot ? 'editing.chat.onFrame' : target ? 'editing.chat.onSelection' : task ? 'editing.chat.reply' : 'editing.chat.onVideo')" @keydown="onKey" />
      <div class="foot">
        <span v-if="usage" class="usage mono" :title="t('editing.chat.usage')">
          <template v-for="(u, k) in usage" :key="k">{{ k === "five_hour" ? t("editing.chat.fiveHour") : k === "seven_day" ? t("editing.chat.sevenDay") : k }} {{ Math.round(u * 100) }} % </template>
        </span>
        <span class="spacer" />
        <button v-if="busy" class="btn" @click="emit('stop')">{{ t("common.stop") }}</button>
        <button v-else class="btn dark" :disabled="!input.trim()" @click="send()">{{ t("common.send") }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.thread { flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 12px; }
.empty { font-size: 13px; color: var(--faint); line-height: 1.55; }
.msg { display: flex; flex-direction: column; gap: 4px; max-width: 100%; }
.msg.user { align-items: flex-end; }
.msg.ai { align-items: flex-start; }
.ref { font-size: 10.5px; color: var(--muted); border: 1px solid var(--line-strong); border-radius: 3px; padding: 2px 6px; cursor: pointer; }
.ref:hover { border-color: var(--ink); }
.shot { width: 200px; aspect-ratio: 16 / 9; object-fit: cover; border-radius: 4px; cursor: pointer; }
.shot.sm { width: 64px; border-radius: 2px; cursor: default; }
.text { font-size: 13.5px; line-height: 1.5; color: var(--ink-2); white-space: pre-wrap; text-wrap: pretty; }
.msg.user .text { background: var(--bg-soft); padding: 8px 10px; border-radius: 6px; }
.tools { font-size: 10.5px; color: var(--faint); }
.busy { font-size: 12px; color: var(--faint); }
.error { font-size: 12.5px; color: var(--red-ink); }
.compose { border-top: 1px solid var(--line-soft); padding: 10px; display: flex; flex-direction: column; gap: 8px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { border: 1px solid var(--line-strong); border-radius: 3px; background: #fff; padding: 3px 8px; font-size: 12px; cursor: pointer; text-align: left; }
.chip:hover:not(:disabled) { border-color: var(--ink); }
.chip:disabled { color: var(--off); cursor: default; }
.ctx { display: flex; align-items: center; gap: 6px; align-self: flex-start; max-width: 100%; background: var(--bg-soft); border-radius: 3px; padding: 3px 4px 3px 8px; }
.ctx .mono { font-size: 11px; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
textarea { min-height: 64px; border: 1px solid var(--line-input); border-radius: 4px; padding: 8px 10px; font-size: 13.5px; line-height: 1.45; resize: none; }
.foot { display: flex; align-items: center; gap: 8px; }
.usage { font-size: 10.5px; color: var(--faint); }
</style>
