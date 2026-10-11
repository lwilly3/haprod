<script setup lang="ts">
/**
 * Le chat du montage : commentaires et demandes à Claude, sur une slide (celle choisie) ou sur tout le short.
 * Claude retouche les sous-titres (mots clés, emojis, corrections) et écrit ou réécrit les slides.
 */
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { post } from "../../../lib/api";
import { toast } from "../../../lib/toast";
import { isActive, type Montage, type Slide } from "./types";

const props = defineProps<{ montage: Montage; slide: Slide | null; slideLabel: (s: Slide) => string }>();
const emit = defineEmits<{ updated: [Montage]; pick: [string]; stop: [] }>();

const { t } = useI18n();
const input = ref("");
const box = ref<HTMLTextAreaElement>();
const thread = ref<HTMLElement>();
/** la demande porte sur la slide choisie, sauf si on retire son étiquette */
const onSlide = ref(true);
watch(() => props.slide?.id, () => { onSlide.value = true; });
const target = computed(() => (onSlide.value ? props.slide : null));
const busy = computed(() => isActive(props.montage.status));

const SLIDE_CHIPS = computed(() => ["more", "sober", "other", "sync"].map((k) => t(`shortEditing.chat.slideChips.${k}`)));
const VIDEO_CHIPS = computed(() => ["keywords", "emojis", "hook", "missing"].map((k) => t(`shortEditing.chat.videoChips.${k}`)));

const slideOf = (id?: string | null) => props.montage.slides.find((s) => s.id === id) ?? null;

function changes(n?: number) {
  return n ? t("shortEditing.chat.changes", n) : "";
}

watch(() => [props.montage.messages.length, props.montage.messages.at(-1)?.text.length, busy.value], async () => {
  await nextTick();
  thread.value?.scrollTo({ top: thread.value.scrollHeight });
}, { immediate: true });

async function send(text = input.value) {
  if (!text.trim() || busy.value) return;
  try {
    emit("updated", await post<Montage>(`/api/animations/jobs/${props.montage.id}/messages`, {
      text, slide: target.value?.id ?? null,
    }));
    input.value = "";
  } catch (e) {
    toast((e as Error).message, true);
  }
}

function onKey(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}

/** Pré-remplit la saisie (« Commenter », « + Slide au curseur »). */
async function compose(text = "", video = false) {
  if (video) onSlide.value = false;
  input.value = text;
  await nextTick();
  box.value?.focus();
  box.value?.setSelectionRange(text.length, text.length);
}
defineExpose({ compose });
</script>

<template>
  <div class="chat">
    <div class="head"><span class="name">{{ t("shortEditing.chat.name") }}</span><span class="sub">{{ t("shortEditing.chat.sub") }}</span></div>
    <div ref="thread" class="thread">
      <div v-for="(m, i) in montage.messages" :key="i" class="msg" :class="m.role">
        <span v-if="m.role === 'user'" class="ref mono" :class="{ link: slideOf(m.slide) }"
          @click="slideOf(m.slide) && emit('pick', m.slide!)">{{ slideOf(m.slide) ? slideLabel(slideOf(m.slide)!) : t("shortEditing.chat.wholeShort") }}</span>
        <span v-if="m.text" class="text">{{ m.text }}</span>
        <span v-else-if="m.role === 'assistant' && busy && i === montage.messages.length - 1" class="busy mono">
          {{ montage.activity ? t("shortEditing.chat.activity", { activity: montage.activity }) : "…" }}
        </span>
        <span v-if="m.role === 'assistant' && changes(m.changed)" class="changes">→ {{ changes(m.changed) }}</span>
      </div>
      <span v-if="busy && montage.messages.at(-1)?.role !== 'assistant'" class="busy mono">{{ montage.activity ? t("shortEditing.chat.activity", { activity: montage.activity }) : "…" }}</span>
      <span v-if="montage.status === 'error'" class="error">{{ montage.error }}</span>
    </div>
    <div class="compose">
      <div class="chips">
        <button v-for="c in target ? SLIDE_CHIPS : VIDEO_CHIPS" :key="c" class="chip" :disabled="busy" @click="send(c)">{{ c }}</button>
      </div>
      <div v-if="target" class="ctx">
        <span class="mono">{{ slideLabel(target) }}</span>
        <button class="x-btn" :title="t('shortEditing.chat.wholeShortTitle')" @click="onSlide = false">×</button>
      </div>
      <textarea
        ref="box" v-model="input" rows="3" :disabled="busy"
        :placeholder="t(busy ? 'shortEditing.chat.busy' : target ? 'shortEditing.chat.onSlide' : 'shortEditing.chat.onShort')"
        @keydown="onKey"
      />
      <div class="foot">
        <span v-if="montage.usage" class="usage mono" :title="t('shortEditing.chat.usage')">
          <template v-for="(u, k) in montage.usage" :key="k">{{ k === "five_hour" ? t("shortEditing.chat.fiveHour") : k === "seven_day" ? t("shortEditing.chat.sevenDay") : k }} {{ Math.round(u * 100) }} % </template>
        </span>
        <span class="spacer" />
        <button v-if="busy" class="btn" @click="emit('stop')">{{ t("common.stop") }}</button>
        <button v-else class="btn dark" :disabled="!input.trim()" @click="send()">{{ t("common.send") }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat {
  position: sticky; top: 0; height: 680px; display: flex; flex-direction: column;
  border: 1px solid var(--line); border-radius: 6px; background: #fff; overflow: hidden;
}
.head { padding: 12px 14px; border-bottom: 1px solid var(--line-soft); display: flex; align-items: center; gap: 8px; }
.name { font-size: 13.5px; font-weight: 600; }
.sub { font-size: 12px; color: var(--faint); }
.thread { flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 12px; }
.msg { display: flex; flex-direction: column; gap: 4px; max-width: 100%; }
.msg.user { align-items: flex-end; }
.msg.assistant { align-items: flex-start; }
.ref { font-size: 10.5px; color: var(--muted); border: 1px solid var(--line-strong); border-radius: 3px; padding: 2px 6px; }
.ref.link { cursor: pointer; }
.ref.link:hover { border-color: var(--ink); }
.text { font-size: 13.5px; line-height: 1.5; color: var(--ink-2); white-space: pre-wrap; text-wrap: pretty; }
.msg.user .text { background: var(--bg-soft); padding: 8px 10px; border-radius: 6px; }
.changes { font-size: 12px; color: var(--red-ink); }
.busy { font-size: 12px; color: var(--faint); }
.error { font-size: 12.5px; color: var(--red-ink); line-height: 1.45; }
.compose { border-top: 1px solid var(--line-soft); padding: 10px; display: flex; flex-direction: column; gap: 8px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { border: 1px solid var(--line-strong); border-radius: 3px; background: #fff; padding: 3px 8px; font-size: 12px; cursor: pointer; }
.chip:hover:not(:disabled) { border-color: var(--ink); }
.chip:disabled { color: var(--off); cursor: default; }
.ctx { display: flex; align-items: center; gap: 6px; align-self: flex-start; background: var(--bg-soft); border-radius: 3px; padding: 3px 4px 3px 8px; }
.ctx .mono { font-size: 11px; color: var(--ink-2); }
textarea {
  min-height: 64px; border: 1px solid var(--line-input); border-radius: 4px; padding: 8px 10px;
  font-size: 13.5px; line-height: 1.45; resize: none;
}
.foot { display: flex; align-items: center; gap: 8px; }
.usage { font-size: 10.5px; color: var(--faint); }
</style>
