<script setup lang="ts">
/** Retrouver un endroit de la timeline par ce qui s'y dit : on tape des mots, un clic y pose la tête de lecture. */
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../../../lib/api";
import { toast } from "../../../lib/toast";
import { tcd } from "./types";

const props = defineProps<{ pid: string }>();
const emit = defineEmits<{ seek: [number] }>();
const { t } = useI18n();

const query = ref("");
const hits = ref<{ t: number; text: string }[] | null>(null);
/** le résultat où l'on se trouve : Entrée passe au suivant */
const at = ref(-1);
let last = "";

async function go() {
  const q = query.value.trim();
  if (!q) return;
  if (q === last && hits.value?.length) {
    at.value = (at.value + 1) % hits.value.length;
    return emit("seek", hits.value[at.value].t);
  }
  try {
    hits.value = (await api<{ hits: { t: number; text: string }[] }>(
      `/api/projects/${props.pid}/montage/find?${new URLSearchParams({ q })}`)).hits;
    last = q;
    at.value = hits.value.length ? 0 : -1;
    if (hits.value.length) emit("seek", hits.value[0].t);
  } catch (e) {
    toast((e as Error).message, true);
  }
}

function pick(i: number) {
  at.value = i;
  emit("seek", hits.value![i].t);
}

function close() {
  hits.value = null;
  last = "";
}
</script>

<template>
  <div class="find">
    <input v-model="query" class="input" :placeholder="t('editing.find.placeholder')" :title="t('editing.find.title')"
      @keydown.enter="go" @keydown.esc="close">
    <div v-if="hits" class="results">
      <div class="head">
        <span>{{ hits.length ? t("editing.find.count", hits.length) : t("editing.find.none") }}</span>
        <button class="link-btn" @click="close">{{ t("common.close") }}</button>
      </div>
      <button v-for="(h, i) in hits" :key="i" class="hit" :class="{ on: i === at }" @click="pick(i)">
        <span class="mono">{{ tcd(h.t) }}</span><span class="text">{{ h.text }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.find { position: relative; }
.input { width: 230px; height: 30px; font-size: 13px; }
.results { position: absolute; top: 34px; left: 0; z-index: 30; width: 460px; max-height: 320px; overflow: auto; background: var(--bg, #fff);
  border: 1px solid var(--line, #ccc); border-radius: 6px; box-shadow: 0 6px 24px rgba(0, 0, 0, 0.12); padding: 6px; display: flex; flex-direction: column; }
.head { display: flex; justify-content: space-between; padding: 2px 6px 6px; font-size: 12px; color: var(--muted, #777); }
.hit { display: grid; grid-template-columns: 62px minmax(0, 1fr); gap: 10px; padding: 6px; border: 0; border-radius: 4px; background: none; cursor: pointer; text-align: left; font-size: 13px; }
.hit:hover, .hit.on { background: var(--line-soft, #eee); }
.text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
