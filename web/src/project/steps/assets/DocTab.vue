<script setup lang="ts">
/**
 * Onglet Documentation : les sources du script (tableau de l'onglet Recherche), avec pour chacune
 * une case « capture automatique » ; les captures (haut de page en 16:9) vont dans les images du projet.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { act, running, store, update } from "../../store";
import type { ResearchSource } from "../../types";
import CheckBox from "./CheckBox.vue";

const { t } = useI18n();
const project = computed(() => store.project!);
const sources = computed(() => project.value.research);
const capture = computed(() => project.value.assets.capture);
const captures = computed(() => project.value.assets.captures);
const job = computed(() => project.value.runtime.jobs.captures);
const busy = computed(() => running("captures"));

const isWeb = (s: ResearchSource) => /^https?:\/\//.test(s.u);
const web = computed(() => sources.value.filter(isWeb));
const done = (s: ResearchSource) => !!captures.value[s.u]?.rel;
const todo = computed(() => web.value.filter((s) => capture.value[s.u] && !done(s)));
const allOn = computed(() => web.value.length > 0 && web.value.every((s) => capture.value[s.u]));

function set(s: ResearchSource, on: boolean) {
  update({ capture: { ...capture.value, [s.u]: on } });
}

function setAll() {
  const on = !allOn.value;
  update({ capture: { ...capture.value, ...Object.fromEntries(web.value.map((s) => [s.u, on])) } });
}

function status(s: ResearchSource): { text: string; tone: string } {
  if (!isWeb(s)) return { text: t("sourcing.doc.status.notLink"), tone: "faint" };
  const c = captures.value[s.u];
  if (c?.rel) return { text: t("sourcing.doc.status.captured"), tone: "ok" };
  if (!capture.value[s.u]) return { text: t("sourcing.doc.status.noCapture"), tone: "faint" };
  if (busy.value) return { text: t("sourcing.doc.status.running"), tone: "muted" };
  if (c?.error) return { text: t("sourcing.doc.status.failed", { e: c.error }), tone: "err" };
  return { text: t("sourcing.doc.status.todo"), tone: "muted" };
}

const label = computed(() => {
  if (busy.value) return t("sourcing.doc.capturing", { p: Math.round((job.value?.progress ?? 0) * 100) });
  return t("sourcing.doc.captureN", todo.value.length);
});

const thumb = (rel: string) => `/api/projects/${project.value.id}/files/${rel.split("/").map(encodeURIComponent).join("/")}`;
</script>

<template>
  <div class="doc">
    <div class="bar">
      <span class="eyebrow">{{ t("sourcing.doc.sources", { n: sources.length }) }}</span>
      <button v-if="web.length" class="link-btn" @click="setAll">{{ allOn ? t("sourcing.doc.uncheckAll") : t("sourcing.doc.checkAll") }}</button>
      <span class="spacer" />
      <RouterLink :to="`/p/${project.id}/script`" class="manage">{{ t("sourcing.doc.manage") }}</RouterLink>
      <button class="btn dark md cap-btn" :disabled="busy || !todo.length" @click="act('/assets/captures')">
        {{ label }}
        <span v-if="busy" class="cap-progress" :style="{ width: `${Math.round((job?.progress ?? 0) * 100)}%` }" />
      </button>
    </div>
    <span v-if="busy && job?.activity" class="mono faint activity">{{ job.activity }}…</span>

    <div v-if="sources.length" class="list">
      <div v-for="s in sources" :key="s.u || s.t" class="row">
        <CheckBox :model-value="!!capture[s.u]" :disabled="!isWeb(s) || done(s)" :title="t('sourcing.doc.autoCapture')"
          @update:model-value="set(s, $event)" />
        <div class="text">
          <span class="t">{{ s.t }}</span>
          <a v-if="isWeb(s)" :href="s.u" target="_blank" rel="noreferrer" class="mono u">{{ s.u }}</a>
          <span v-else class="mono u faint">{{ s.u }}</span>
          <span v-if="s.n" class="n muted">{{ s.n }}</span>
        </div>
        <span class="st" :class="status(s).tone" :title="status(s).text">{{ status(s).text }}</span>
        <a v-if="captures[s.u]?.rel" :href="thumb(captures[s.u].rel!)" target="_blank" class="th">
          <img :src="thumb(captures[s.u].rel!)" alt="">
        </a>
        <div v-else class="th hatch mono faint">{{ capture[s.u] ? t("sourcing.doc.pending") : "—" }}</div>
      </div>
    </div>
    <div v-else class="dashed-box empty faint">
      {{ t("sourcing.doc.empty") }}
    </div>
  </div>
</template>

<style scoped>
.doc { display: flex; flex-direction: column; gap: 14px; max-width: 960px; }
.bar { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.link-btn { font-size: 12.5px; text-decoration: underline; text-underline-offset: 3px; }
.manage { font-size: 12.5px; color: var(--muted) !important; }
.cap-btn { position: relative; overflow: hidden; }
.cap-progress { position: absolute; left: 0; bottom: 0; height: 2px; background: var(--red); transition: width .3s; }
.activity { font-size: 11.5px; margin-top: -6px; }
.list { display: flex; flex-direction: column; border: 1px solid var(--line); border-radius: 4px; }
.row { display: grid; grid-template-columns: 28px minmax(0, 1fr) 130px 96px; gap: 14px; align-items: center; padding: 12px 14px; border-top: 1px solid var(--line-soft); }
.row:first-child { border-top: none; }
.text { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.t { font-size: 13.5px; font-weight: 500; }
.u { font-size: 11.5px; color: var(--faint) !important; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.n { font-size: 12.5px; line-height: 1.45; }
.st { font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.st.ok { color: var(--ink); font-weight: 500; }
.st.muted { color: var(--muted); }
.st.faint { color: var(--faint); }
.st.err { color: var(--red-ink); }
.th { aspect-ratio: 16/10; border: 1px solid var(--line); display: flex; align-items: center; justify-content: center; font-size: 10px; overflow: hidden; }
.th img { width: 100%; height: 100%; object-fit: cover; object-position: top; }
.empty { padding: 40px 20px; text-align: center; font-size: 13px; }
</style>
