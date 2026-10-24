<script setup lang="ts">
/** Vue d'ensemble d'un projet : avancement, toutes les étapes, place occupée sur le disque, suppression. */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { api } from "../lib/api";
import { bytes } from "../lib/format";
import { toast } from "../lib/toast";
import { stepGroups } from "./nav";
import { bars, doneCount, firstCur, stepById, STEPS } from "./steps";
import { open, removeProject, store } from "./store";
import type { ProjectStorage, UnusedStorage } from "./types";

const { t, locale } = useI18n();
const route = useRoute();
const router = useRouter();
const pid = computed(() => String(route.params.pid));
const project = computed(() => (store.project?.id === pid.value ? store.project : null));
const storage = ref<ProjectStorage | null>(null);
const unused = ref<UnusedStorage | null>(null);

watch(pid, async (id) => {
  storage.value = null;
  unused.value = null;
  try {
    await open(id);
  } catch {
    router.replace("/");
    return;
  }
  loadStorage(id);
}, { immediate: true });

function loadStorage(id: string) {
  api<ProjectStorage>(`/api/projects/${id}/storage`).then((s) => { storage.value = s; }).catch(() => {});
  api<UnusedStorage>(`/api/projects/${id}/storage/unused`).then((u) => { unused.value = u; }).catch(() => {});
}

watch([project, locale], ([p]) => {
  if (p) document.title = `${p.title} · Studio`;
}, { immediate: true });

const CHIP = computed(() => ({
  done: [t("project.state.done"), "var(--ink)", "#fff"], cur: [t("project.state.cur"), "var(--red-bg)", "var(--red-dark)"],
  skip: [t("project.state.skip"), "transparent", "var(--faint)"], todo: [t("project.state.todo"), "var(--line-soft)", "var(--muted-2)"],
}));

const groups = computed(() => (project.value ? stepGroups(project.value).map((g) => ({
  ...g,
  count: `${g.items.filter((s) => s.state === "done" || s.state === "skip").length}/${g.items.length}`,
  cur: g.items.some((s) => s.state === "cur"),
})) : []));

const next = computed(() => (project.value ? firstCur(project.value) : ""));
const created = computed(() => (project.value
  ? new Date(project.value.created_at * 1000).toLocaleDateString(locale.value, { day: "numeric", month: "long", year: "numeric" })
  : ""));

/** gris du plus foncé au plus clair ; le rouge pour ce qui se régénère (scripts, montage, cache) */
const COLORS: Record<string, string> = {
  rushes: "var(--ink)", source: "var(--ink-3)", derush: "var(--muted-2)", renders: "var(--off)", media: "var(--dash)", other: "var(--red)",
};
const categories = computed(() => {
  const s = storage.value;
  if (!s) return [];
  const total = s.total || 1;
  return s.categories.filter((c) => c.bytes > 0).map((c) => ({
    ...c, label: t(`overview.categories.${c.key}`), size: bytes(c.bytes), color: COLORS[c.key], w: `${(c.bytes / total) * 100}%`,
  }));
});

const unusedCategories = computed(() => (unused.value?.categories ?? []).filter((c) => c.bytes > 0).map((c) => ({
  ...c, label: t(`overview.unusedCategories.${c.key}`), size: bytes(c.bytes),
})));

const purging = ref(false);
const confirmingPurge = ref(false);
async function purge() {
  const id = pid.value;
  purging.value = true;
  try {
    const r = await api<{ freed: number; unused: UnusedStorage }>(`/api/projects/${id}/storage/purge`, { method: "POST" });
    toast(t("overview.purged", { size: bytes(r.freed) }));
    confirmingPurge.value = false;
    loadStorage(id);
  } catch (e) {
    toast(t("overview.purgeFailed", { error: String(e) }), true);
  } finally {
    purging.value = false;
  }
}

const confirming = ref(false);
async function remove() {
  const p = project.value;
  if (!p) return;
  try {
    await removeProject(p.id);
    toast(t("overview.deleted", { title: p.title }));
    router.replace("/");
  } catch (e) {
    toast(t("overview.deleteFailed", { error: String(e) }), true);
  }
}
</script>

<template>
  <div v-if="project" class="page">
    <div class="wrap">
      <div class="head">
        <div class="titles">
          <span class="eyebrow">{{ t("overview.meta", { date: created }) }}</span>
          <span class="h1">{{ project.title }}</span>
          <span v-if="project.brief.idea" class="idea">{{ project.brief.idea }}</span>
        </div>
        <div class="actions">
          <RouterLink :to="`/p/${project.id}/brief`" class="btn md">{{ t("overview.editBrief") }}</RouterLink>
          <RouterLink :to="`/p/${project.id}/${next}`" class="btn dark md">
            {{ t("home.continue", { step: stepById(next)?.label ?? "" }) }}
          </RouterLink>
        </div>
      </div>

      <section>
        <div class="row-between">
          <span class="eyebrow">{{ t("overview.progress") }}</span>
          <span class="mono">{{ t("home.stepsDone", { done: doneCount(project), total: STEPS.length }) }}</span>
        </div>
        <div class="bars"><div v-for="(c, i) in bars(project)" :key="i" :style="{ background: c }" /></div>
      </section>

      <div class="cols">
        <section class="workflow">
          <span class="eyebrow">{{ t("overview.workflow") }}</span>
          <div class="groups">
            <div v-for="g in groups" :key="g.g" class="group" :class="{ cur: g.cur }">
              <div class="group-head"><span class="label">{{ g.label }}</span><span class="mono">{{ g.count }}</span></div>
              <RouterLink v-for="s in g.items" :key="s.id" :to="`/p/${project.id}/${s.id}`" class="step" :class="{ todo: s.state === 'todo' }">
                <span class="dot" :style="{ background: s.dot[0], border: s.dot[1] }" />
                <span class="names"><span class="name">{{ s.label }}</span><span v-if="s.sub" class="sub">{{ s.sub }}</span></span>
                <span class="chip" :style="{ background: CHIP[s.state][1], color: CHIP[s.state][2] }">{{ CHIP[s.state][0] }}</span>
              </RouterLink>
            </div>
          </div>
        </section>

        <div class="side">
          <section>
            <span class="eyebrow">{{ t("overview.storage") }}</span>
            <template v-if="storage">
              <div class="total">
                <span class="big">{{ bytes(storage.total) }}</span>
                <span class="free">{{ t("overview.free", { size: bytes(storage.free) }) }}</span>
              </div>
              <div class="stack"><div v-for="c in categories" :key="c.key" :style="{ width: c.w, background: c.color }" /></div>
              <div class="cats">
                <div v-for="c in categories" :key="c.key" class="cat">
                  <span class="swatch" :style="{ background: c.color }" /><span>{{ c.label }}</span><span class="mono">{{ c.size }}</span>
                </div>
              </div>
            </template>
            <span v-else class="mono">{{ t("common.loading") }}</span>
          </section>

          <section v-if="unused">
            <div class="row-between">
              <span class="eyebrow">{{ t("overview.unused") }}</span>
              <span class="mono">{{ unused.total ? bytes(unused.total) : t("overview.unusedNone") }}</span>
            </div>
            <template v-if="unused.total">
              <div class="cats">
                <div v-for="c in unusedCategories" :key="c.key" class="cat unused">
                  <span>{{ c.label }}</span><span class="mono">{{ c.count }} · {{ c.size }}</span>
                </div>
              </div>
              <button v-if="!confirmingPurge" class="btn sm" @click="confirmingPurge = true">
                {{ t("overview.purgeBtn", { size: bytes(unused.total) }) }}
              </button>
              <div v-else class="confirm">
                <span>{{ t("overview.purgeConfirm", { size: bytes(unused.total) }) }}</span>
                <button class="btn sm" :disabled="purging" @click="confirmingPurge = false">{{ t("overview.cancel") }}</button>
                <button class="btn sm dark" :disabled="purging" @click="purge">{{ t("overview.purge") }}</button>
              </div>
            </template>
          </section>

          <div class="danger">
            <div class="danger-row">
              <div class="danger-text">
                <span class="danger-title">{{ t("overview.delete") }}</span>
                <span class="danger-desc">{{ t("overview.deleteDesc", { size: storage ? bytes(storage.total) : "…" }) }}</span>
              </div>
              <button v-if="!confirming" class="btn sm danger-btn" @click="confirming = true">{{ t("overview.deleteBtn") }}</button>
            </div>
            <div v-if="confirming" class="confirm">
              <span>{{ t("overview.deleteConfirm", { title: project.title }) }}</span>
              <button class="btn sm" @click="confirming = false">{{ t("overview.cancel") }}</button>
              <button class="btn sm red-solid" @click="remove">{{ t("overview.deleteForever") }}</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="loading eyebrow">{{ t("common.loading") }}</div>
</template>

<style scoped>
.page { flex: 1; overflow: auto; padding: 32px 40px 48px; }
.wrap { max-width: 1180px; display: flex; flex-direction: column; gap: 28px; }
.head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 16px; }
.titles { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.h1 { font-size: 28px; font-weight: 600; letter-spacing: -0.02em; text-wrap: pretty; }
.idea { font-size: 14px; color: var(--muted); max-width: 640px; line-height: 1.5; text-wrap: pretty; }
.actions { display: flex; gap: 8px; }
.actions .btn { text-decoration: none !important; color: var(--ink) !important; display: inline-flex; align-items: center; }
.actions .btn.dark { color: #fff !important; font-weight: 500; }
section { display: flex; flex-direction: column; gap: 12px; }
.row-between { display: flex; justify-content: space-between; align-items: baseline; }
.mono { font-family: var(--mono); font-size: 12px; color: var(--muted); }
.bars { display: flex; gap: 3px; }
.bars > div { flex: 1; height: 6px; }
.cols { display: flex; flex-wrap: wrap; gap: 32px; align-items: flex-start; }
.workflow { flex: 1 1 560px; min-width: 0; }
.groups { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 12px; }
.group { display: flex; flex-direction: column; border: 1px solid var(--line); border-radius: 4px; padding: 6px; }
.group.cur { border-color: var(--dash); }
.group-head { display: flex; justify-content: space-between; align-items: baseline; padding: 8px 8px 6px; }
.group-head .label { font-size: 13.5px; font-weight: 600; }
.group-head .mono { font-size: 11px; color: var(--faint); }
.step {
  display: grid; grid-template-columns: 10px minmax(0, 1fr) auto; gap: 10px; align-items: center; min-height: 34px;
  padding: 4px 8px; border-radius: 3px; color: var(--ink-2) !important; text-decoration: none !important;
}
.step:hover { background: var(--bg-soft); }
.step .dot { width: 10px; height: 10px; border-radius: 5px; }
.names { display: flex; flex-direction: column; min-width: 0; }
.name { font-size: 13.5px; }
.step.todo .name { color: var(--muted-2); }
.sub { font-family: var(--mono); font-size: 10.5px; color: var(--faint); }
.chip { font-family: var(--mono); font-size: 10.5px; padding: 2px 6px; border-radius: 3px; }
.side { flex: 0 1 360px; min-width: 300px; display: flex; flex-direction: column; gap: 28px; }
.total { display: flex; align-items: baseline; gap: 10px; }
.big { font-size: 28px; font-weight: 600; letter-spacing: -0.02em; }
.free { font-size: 13px; color: var(--faint); }
.stack { display: flex; height: 10px; gap: 2px; }
.stack > div { height: 10px; min-width: 2px; }
.cats { display: flex; flex-direction: column; }
.cat {
  display: grid; grid-template-columns: 10px minmax(0, 1fr) auto; gap: 10px; align-items: center;
  padding: 7px 0; border-bottom: 1px solid var(--line-soft); font-size: 13.5px;
}
.cat.unused { grid-template-columns: minmax(0, 1fr) auto; }
.side section > .btn { align-self: flex-start; }
.swatch { width: 10px; height: 10px; }
.danger { display: flex; flex-direction: column; gap: 10px; padding: 12px; border: 1px solid #F0C8C9; border-radius: 4px; }
.danger-row { display: flex; gap: 12px; align-items: center; }
.danger-text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.danger-title { font-size: 13.5px; font-weight: 500; color: var(--red-ink); }
.danger-desc { font-size: 12.5px; color: var(--faint); line-height: 1.4; }
.danger-btn { border-color: #F0C8C9; color: var(--red-ink); }
.danger-btn:hover:not(:disabled) { border-color: var(--red-ink); }
.confirm { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.confirm > span { flex: 1; min-width: 160px; font-size: 12.5px; color: var(--ink-2); }
.red-solid { background: var(--red-ink); border-color: var(--red-ink); color: #fff; }
.loading { padding: 32px; }
</style>
