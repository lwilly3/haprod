<script setup lang="ts">
/**
 * Le chat avec le monteur (Claude) : tu es le client, il travaille dans la timeline sous tes yeux.
 * Une demande porte sur la sélection en cours (élément ou plage), affichée au-dessus de la saisie.
 * Discuter de l'image en pause ouvre une nouvelle discussion, avec son timecode et l'image joints.
 */
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { store } from "../../store";
import { tcd, trackLabel, type MontageView, type Selection, type Shot } from "./types";

const props = defineProps<{ chat: MontageView["chat"]; selection: Selection | null; describe: (s: Selection) => string }>();
const emit = defineEmits<{ send: [string, Selection | null, Shot | null, boolean]; stop: []; pick: [Selection]; seek: [number] }>();

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
/** la prochaine demande ouvre une nouvelle discussion : l'ancien fil est masqué, puis effacé à l'envoi */
const fresh = ref(false);
const messages = computed(() => (fresh.value ? [] : props.chat.messages));

const CHIPS = computed(() => (shot.value ? [] : target.value
  ? ["motion", "broll", "zooms", "sound"].map((k) => t(`editing.chat.chipsSelection.${k}`))
  : ["chapters", "music", "zooms"].map((k) => t(`editing.chat.chipsVideo.${k}`))));

watch(() => [props.chat.messages.length, props.chat.messages.at(-1)?.text.length, props.chat.busy, props.chat.activity], async () => {
  await nextTick();
  thread.value?.scrollTo({ top: thread.value.scrollHeight });
}, { immediate: true });

function send(text = input.value) {
  if (!text.trim() || props.chat.busy) return;
  emit("send", text.trim(), target.value, shot.value, fresh.value);
  input.value = "";
  shot.value = null;
  fresh.value = false;
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
/** Repart d'une discussion vierge ; `at` : l'image en pause dont le client veut parler. */
async function restart(at: Shot | null = null) {
  fresh.value = true;
  shot.value = at;
  if (at) attach.value = false;
  await nextTick();
  box.value?.focus();
}
function resume() {
  fresh.value = false;
  shot.value = null;
}
const fileUrl = (rel: string) => `/api/projects/${store.project?.id}/files/${rel}`;
defineExpose({ compose, send, restart });
</script>

<template>
  <div class="chat">
    <div ref="thread" class="thread">
      <span v-if="!messages.length" class="empty">
        {{ t(fresh ? "editing.chat.fresh" : "editing.chat.empty") }}
        <button v-if="fresh && chat.messages.length" class="link-btn" @click="resume">{{ t("editing.chat.resume") }}</button>
      </span>
      <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
        <img v-if="m.role === 'user' && m.image" class="shot" :src="fileUrl(m.image)" alt="" @click="emit('seek', m.frame!)">
        <span v-if="m.role === 'user' && m.frame != null" class="ref mono" @click="emit('seek', m.frame!)">{{ t("editing.chat.frameRef", { tc: tcd(m.frame) }) }}</span>
        <span v-if="m.role === 'user' && m.selection" class="ref mono" @click="emit('pick', m.selection!)">{{ ref_(m.selection) }}</span>
        <span v-if="m.text" class="text">{{ m.text }}</span>
        <span v-if="m.role === 'ai' && m.tools?.length" class="tools mono" :title="m.tools.join(' · ')">{{ t("editing.chat.actions", m.tools.length) }}{{ m.changed ? t("editing.chat.timelineChanged") : "" }}</span>
      </div>
      <span v-if="chat.busy && !fresh" class="busy mono">{{ chat.activity ? `${chat.activity}…` : "…" }}</span>
      <span v-if="chat.error" class="error">{{ chat.error }}</span>
    </div>
    <div class="compose">
      <div class="chips">
        <button v-for="c in CHIPS" :key="c" class="chip" :disabled="chat.busy" @click="send(c)">{{ c }}</button>
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
      <textarea ref="box" v-model="input" rows="3" :disabled="chat.busy"
        :placeholder="t(chat.busy ? 'editing.chat.busy' : shot ? 'editing.chat.onFrame' : target ? 'editing.chat.onSelection' : 'editing.chat.onVideo')" @keydown="onKey" />
      <div class="foot">
        <span v-if="chat.usage" class="usage mono" :title="t('editing.chat.usage')">
          <template v-for="(u, k) in chat.usage" :key="k">{{ k === "five_hour" ? t("editing.chat.fiveHour") : k === "seven_day" ? t("editing.chat.sevenDay") : k }} {{ Math.round(u * 100) }} % </template>
        </span>
        <span class="spacer" />
        <button v-if="chat.busy" class="btn" @click="emit('stop')">{{ t("common.stop") }}</button>
        <button v-else class="btn dark" :disabled="!input.trim()" @click="send()">{{ t("common.send") }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.thread { flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 12px; }
.empty { font-size: 13px; color: var(--faint); line-height: 1.55; display: flex; flex-direction: column; align-items: flex-start; gap: 6px; }
.empty .link-btn { font-size: 12.5px; }
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
