<script setup lang="ts">
/**
 * Onglet Images : on dit à Claude ce qu'on cherche (logo d'une marque, photo d'une personne…), il
 * cherche sur le web ; les images trouvées sont vérifiées et téléchargées par le studio, on coche
 * celles à garder et on les range dans le projet ou dans les assets communs.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api, post } from "../../lib/api";
import { usePref } from "../../lib/composables";
import { toast } from "../../lib/toast";
import { store } from "../store";
import type { ImagesState } from "../types";
import CheckBox from "./CheckBox.vue";
import DestPicker from "./DestPicker.vue";

const emit = defineEmits<{ added: [] }>();
const { t } = useI18n();
const base = `/api/projects/${store.project!.id}/assets`;
const state = ref<ImagesState>({ messages: [], results: [], busy: false, error: null, activity: null });
const input = ref("");
const sending = ref(false);
const picked = ref(new Set<string>());
const scroller = ref<HTMLElement>();
let timer: ReturnType<typeof setTimeout> | undefined;

/** Relit l'état toutes les 1,5 s tant que Claude cherche. */
function receive(s: ImagesState): void {
  const fresh = state.value.busy && !s.busy;
  state.value = s;
  // les nouvelles images arrivent cochées pour la première, comme une proposition
  if (fresh) {
    const first = s.results.find((r) => !r.added);
    const asked = [...s.messages].reverse().find((m) => m.role === "user")?.text;
    if (first && first.query === asked) picked.value = new Set([...picked.value, first.id]);
  }
  clearTimeout(timer);
  if (s.busy) timer = setTimeout(() => api<ImagesState>(`${base}/images`).then(receive).catch(() => receive(s)), 1500);
}

onMounted(() => api<ImagesState>(`${base}/images`).then(receive).catch((e) => toast(e.message, true)));
onBeforeUnmount(() => clearTimeout(timer));

watch(() => state.value.messages.length + (state.value.busy ? 1 : 0), async () => {
  await nextTick();
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight });
});

async function send() {
  const text = input.value.trim();
  if (!text || sending.value || state.value.busy) return;
  sending.value = true;
  try {
    receive(await post<ImagesState>(`${base}/images`, { text }));
    input.value = "";
  } catch (e) {
    toast((e as Error).message, true);
  } finally {
    sending.value = false;
  }
}

function toggle(id: string) {
  const s = new Set(picked.value);
  if (s.has(id)) s.delete(id);
  else s.add(id);
  picked.value = s;
}

const selection = computed(() => state.value.results.filter((r) => picked.value.has(r.id) && !r.added));

const common = usePref("assets.imgCommon", false);
const category = usePref("assets.imgCategory", "logos");

async function validate() {
  if (!selection.value.length) return toast(t("sourcing.images.checkOne"), true);
  try {
    const out = await post<ImagesState & { added: number }>(`${base}/images/add`, {
      ids: selection.value.map((r) => r.id), common: common.value, category: common.value ? category.value : "images",
    });
    picked.value = new Set();
    receive(out);
    const dest = out.results.find((r) => r.added)?.added ?? "";
    toast(t("sourcing.images.added", { dest }, out.added));
    if (out.added) emit("added");
  } catch (e) {
    toast((e as Error).message, true);
  }
}

const src = (file: string) => `${base}/candidates/${encodeURIComponent(file)}`;
</script>

<template>
  <div class="images">
    <div class="chat">
      <div ref="scroller" class="messages">
        <div class="msg ai">{{ t("sourcing.images.hello") }}</div>
        <div v-for="(m, i) in state.messages" :key="i" class="msg" :class="m.role">{{ m.text }}</div>
        <span v-if="state.busy" class="mono faint activity">{{ state.activity ? t("sourcing.images.activity", { activity: state.activity }) : t("sourcing.images.searching") }}</span>
        <span v-if="state.error" class="error">{{ t("sourcing.images.error", { e: state.error }) }}</span>
      </div>
      <div class="compose">
        <input v-model="input" class="input soft" :placeholder="t('sourcing.images.placeholder')"
          :disabled="state.busy" @keydown.enter="send">
        <button class="btn dark md" :disabled="state.busy || sending || !input.trim()" @click="send">{{ t("sourcing.images.search") }}</button>
      </div>
    </div>

    <div class="results">
      <span class="eyebrow">{{ t("sourcing.images.results") }}{{ state.results.length ? ` · ${state.results.length}` : "" }}</span>
      <div v-if="!state.results.length" class="dashed-box empty faint">{{ t("sourcing.images.resultsEmpty") }}</div>
      <div v-else class="grid">
        <div v-for="r in state.results" :key="r.id" class="card" :class="{ on: picked.has(r.id), added: !!r.added }"
          @click="!r.added && toggle(r.id)">
          <div class="frame hatch">
            <img :src="src(r.file)" :alt="r.title" loading="lazy">
            <CheckBox class="pick" :model-value="picked.has(r.id) || !!r.added" :disabled="!!r.added"
              @update:model-value="toggle(r.id)" />
          </div>
          <div class="cap">
            <span class="t" :title="r.title">{{ r.title }}</span>
            <span class="mono faint tag">{{ r.added ? t("sourcing.images.addedTag") : r.file.split(".").pop()!.toUpperCase() }}</span>
          </div>
          <div class="sub">
            <span class="muted v">{{ r.added ?? r.variant }}</span>
            <a v-if="r.page" :href="r.page" target="_blank" rel="noreferrer" :title="r.license || r.page" @click.stop>{{ t("sourcing.images.source") }}</a>
          </div>
        </div>
      </div>
      <div v-if="state.results.length" class="actions">
        <DestPicker v-model:common="common" v-model:category="category" project-category="images" />
        <span class="spacer" />
        <button class="btn red md" :disabled="!selection.length || state.busy" @click="validate">
          {{ t("sourcing.images.validateN", selection.length) }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.images { display: grid; grid-template-columns: 340px minmax(0, 1fr); gap: 24px; align-items: start; }
.chat { display: flex; flex-direction: column; border: 1px solid var(--line); border-radius: 4px; height: 520px; position: sticky; top: 0; }
.messages { flex: 1; overflow: auto; padding: 14px; display: flex; flex-direction: column; gap: 10px; }
.msg { max-width: 88%; padding: 8px 11px; border-radius: 6px; font-size: 13px; line-height: 1.45; white-space: pre-wrap; }
.msg.ai { align-self: flex-start; background: #F2F2EF; color: var(--ink-2); }
.msg.user { align-self: flex-end; background: var(--ink); color: #fff; }
.activity { font-size: 11.5px; }
.error { font-size: 12.5px; color: var(--red-ink); }
.compose { display: flex; gap: 8px; padding: 10px; border-top: 1px solid var(--line); }
.compose .input { flex: 1; min-width: 0; height: 34px; font-size: 13px; padding: 0 10px; }
.results { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.empty { padding: 48px 20px; text-align: center; font-size: 13px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 14px; }
.card { display: flex; flex-direction: column; gap: 4px; cursor: pointer; }
.card.added { opacity: .5; cursor: default; }
.frame { position: relative; aspect-ratio: 4/3; outline: 2px solid transparent; outline-offset: -2px; display: flex; align-items: center; justify-content: center; overflow: hidden; }
.card.on .frame { outline-color: var(--ink); }
.frame img { max-width: 100%; max-height: 100%; object-fit: contain; }
.pick { position: absolute; top: 8px; left: 8px; }
.pick :deep(.box) { width: 18px; height: 18px; font-size: 11px; }
.cap { display: flex; justify-content: space-between; gap: 8px; font-size: 12.5px; }
.cap .t { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tag { font-size: 11px; flex-shrink: 0; }
.sub { display: flex; justify-content: space-between; gap: 8px; font-size: 11.5px; }
.sub .v { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sub a { flex-shrink: 0; }
.actions { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; padding-top: 12px; border-top: 1px solid var(--line-soft); }
</style>
