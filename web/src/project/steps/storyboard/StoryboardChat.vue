<script setup lang="ts">
/**
 * Le chat avec Daryl sur le storyboard : ajouter des beats, en retoucher, demander son avis. Une demande
 * peut porter sur le moment choisi (le beat sélectionné, sinon la tête de lecture), avec l'image de la
 * vidéo à ce moment, qu'il regarde. Ses changements arrivent dans les beats à la fin de sa réponse.
 */
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { tcd, type Beat, type StoryboardChat } from "../montage/types";

const props = defineProps<{ chat: StoryboardChat; t: number; beat: Beat | null; beats: Beat[] }>();
const emit = defineEmits<{ send: [string, number | null, string | null, boolean]; stop: []; seek: [number]; focus: [string] }>();
const { t: tr } = useI18n();

const input = ref("");
const thread = ref<HTMLElement>();
/** le moment joint à la demande (retiré avec × : la demande porte alors sur toute la vidéo) */
const attach = ref(true);
const frame = ref(true);
watch(() => props.beat?.id, () => { attach.value = true; });
const at = computed(() => (props.beat ? props.beat.at : props.t));
const number = (id: string) => props.beats.findIndex((b) => b.id === id) + 1;

watch(() => [props.chat.messages.length, props.chat.busy, props.chat.activity], async () => {
  await nextTick();
  thread.value?.scrollTo({ top: thread.value.scrollHeight });
}, { immediate: true });

function send() {
  const text = input.value.trim();
  if (!text || props.chat.busy) return;
  emit("send", text, attach.value ? at.value : null, attach.value ? props.beat?.id ?? null : null, attach.value && frame.value);
  input.value = "";
}
function onKey(e: KeyboardEvent) {
  e.stopPropagation();
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}
</script>

<template>
  <div class="chat">
    <div ref="thread" class="thread">
      <span v-if="!chat.messages.length" class="empty">{{ tr("editing.storyboard.chat.empty") }}</span>
      <div v-for="(m, i) in chat.messages" :key="i" class="msg" :class="m.role">
        <button v-if="m.role === 'user' && m.at != null" class="ref mono" @click="emit('seek', m.at!)">
          {{ tcd(m.at) }}<template v-if="m.beat && number(m.beat)"> · {{ tr("editing.storyboard.chat.beat", { n: number(m.beat) }) }}</template>
          <template v-if="m.frame"> · {{ tr("editing.storyboard.chat.image") }}</template>
        </button>
        <span v-if="m.text" class="text">{{ m.text }}</span>
        <span v-if="m.changes" class="changes">
          <button v-for="id in m.changes.added.filter(number)" :key="`a${id}`" class="chg add" @click="emit('focus', id)">
            + {{ tr("editing.storyboard.chat.beat", { n: number(id) }) }}
          </button>
          <button v-for="id in m.changes.updated.filter(number)" :key="`u${id}`" class="chg" @click="emit('focus', id)">
            ✎ {{ tr("editing.storyboard.chat.beat", { n: number(id) }) }}
          </button>
          <span v-if="m.changes.removed.length" class="chg off">{{ tr("editing.storyboard.chat.removed", m.changes.removed.length) }}</span>
          <span v-for="(a, k) in m.changes.missing" :key="`m${k}`" class="chg warn" :title="a">{{ tr("editing.storyboard.chat.missing", { text: a }) }}</span>
        </span>
      </div>
      <span v-if="chat.busy" class="busy mono">{{ chat.activity ? `${chat.activity}…` : "…" }}</span>
      <span v-if="chat.error" class="error">{{ chat.error }}</span>
    </div>
    <div class="compose">
      <div v-if="attach" class="ctx">
        <span class="mono">
          {{ tcd(at) }}<template v-if="beat"> · {{ tr("editing.storyboard.chat.beat", { n: number(beat.id) }) }}</template>
        </span>
        <label class="img" :title="tr('editing.storyboard.chat.imageTitle')">
          <input v-model="frame" type="checkbox"> {{ tr("editing.storyboard.chat.image") }}
        </label>
        <button class="x-btn" :title="tr('editing.storyboard.chat.wholeVideo')" @click="attach = false">×</button>
      </div>
      <button v-else class="link-btn attach" @click="attach = true">{{ tr("editing.storyboard.chat.attach", { tc: tcd(at) }) }}</button>
      <textarea v-model="input" rows="2" :disabled="chat.busy"
        :placeholder="tr(chat.busy ? 'editing.chat.busy' : attach ? 'editing.storyboard.chat.onMoment' : 'editing.storyboard.chat.onVideo')"
        @keydown="onKey" />
      <div class="foot">
        <span class="spacer" />
        <button v-if="chat.busy" class="btn sm" @click="emit('stop')">{{ tr("common.stop") }}</button>
        <button v-else class="btn dark sm" :disabled="!input.trim()" @click="send">{{ tr("common.send") }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat { flex: 1; min-height: 0; display: flex; flex-direction: column; border: 1px solid var(--line); border-radius: 6px; background: #fff; overflow: hidden; }
.thread { flex: 1; min-height: 0; overflow-y: auto; padding: 12px 14px; display: flex; flex-direction: column; gap: 12px; }
.empty { font-size: 13px; color: var(--faint); line-height: 1.55; }
.msg { display: flex; flex-direction: column; gap: 4px; max-width: 100%; }
.msg.user { align-items: flex-end; }
.msg.ai { align-items: flex-start; }
.ref { font-size: 10.5px; color: var(--muted); border: 1px solid var(--line-strong); border-radius: 3px; padding: 2px 6px; background: #fff; cursor: pointer; }
.ref:hover { border-color: var(--ink); }
.text { font-size: 13.5px; line-height: 1.5; color: var(--ink-2); white-space: pre-wrap; text-wrap: pretty; }
.msg.user .text { background: var(--bg-soft); padding: 8px 10px; border-radius: 6px; }
.changes { display: flex; flex-wrap: wrap; gap: 4px; }
.chg { font-size: 11px; padding: 2px 7px; border-radius: 3px; border: 1px solid var(--line-strong); background: #fff; color: var(--ink-2); cursor: pointer; }
.chg.add { border-color: #7C5CE0; color: #5B3FC4; }
.chg.off { cursor: default; color: var(--faint); }
.chg.warn { cursor: default; border-color: var(--red-bg); color: var(--red-ink); max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.busy { font-size: 12px; color: var(--faint); }
.error { font-size: 12.5px; color: var(--red-ink); }
.compose { border-top: 1px solid var(--line-soft); padding: 10px; display: flex; flex-direction: column; gap: 8px; }
.ctx { display: flex; align-items: center; gap: 10px; align-self: flex-start; background: var(--bg-soft); border-radius: 3px; padding: 3px 4px 3px 8px; }
.ctx .mono { font-size: 11px; color: var(--ink-2); }
.img { display: flex; align-items: center; gap: 4px; font-size: 11.5px; color: var(--muted); cursor: pointer; }
.img input { margin: 0; }
.attach { align-self: flex-start; font-size: 12px; }
textarea { border: 1px solid var(--line-input); border-radius: 4px; padding: 8px 10px; font: inherit; font-size: 13.5px; line-height: 1.45; resize: none; }
.foot { display: flex; align-items: center; gap: 8px; }
.spacer { flex: 1; }
</style>
