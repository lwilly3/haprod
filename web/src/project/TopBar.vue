<script setup lang="ts">
/** La barre du haut : navigation générale, ou, dans un projet, le projet et ses phases (un menu par phase). */
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { api } from "../lib/api";
import { usePolling } from "../lib/composables";
import { bytes } from "../lib/format";
import { stepGroups } from "./nav";
import { firstCur, stage } from "./steps";
import { loadList, store, update } from "./store";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const pid = computed(() => (typeof route.params.pid === "string" ? route.params.pid : null));
const project = computed(() => (pid.value && store.project?.id === pid.value ? store.project : null));

/** le menu ouvert : "project", ou une phase */
const menu = ref<string | null>(null);
const toggle = (k: string) => { menu.value = menu.value === k ? null : k; };
watch(() => route.fullPath, () => { menu.value = null; });

// renommage sur place : Entrée ou clic ailleurs enregistre, Échap annule
const renaming = ref(false);
const draft = ref("");
const titleInput = ref<HTMLInputElement>();

async function startRename() {
  if (!project.value) return;
  menu.value = null;
  draft.value = project.value.title;
  renaming.value = true;
  await nextTick();
  titleInput.value?.select();
}

function endRename(save: boolean) {
  if (!renaming.value) return;
  renaming.value = false;
  const name = draft.value.trim();
  if (save && name && name !== project.value?.title) update({ title: name });
}

onMounted(() => loadList().catch(() => {}));

// le worker exécute tous les jobs : s'il est arrêté, rien n'avance
const workerAlive = ref<boolean | null>(null);
usePolling(async () => {
  try {
    workerAlive.value = (await api<{ worker: { alive: boolean } }>("/api/status")).worker.alive;
  } catch {
    workerAlive.value = null;
  }
  return 5000;
});

const globalNav = computed(() => [
  { label: t("nav.home"), to: "/", on: route.name === "home" },
  { label: t("nav.newProjectBtn"), to: "/nouveau", on: route.name === "new" },
  { label: t("nav.library"), to: "/bibliotheque", on: route.name === "library" },
]);

const groups = computed(() => {
  const p = project.value;
  if (!p) return [];
  return stepGroups(p).map((g) => {
    const items = g.items.map((s) => ({ ...s, on: route.name === "step" && route.params.step === s.id }));
    const short = t(`steps.phasesShort.${g.g}`);
    const n = g.g === "short" ? p.runtime.shorts.count : 0;
    return { ...g, items, short: n ? `${short} · ${n}` : short, on: items.some((s) => s.on) };
  });
});

function openProject(id: string) {
  menu.value = null;
  const summary = store.list.find((p) => p.id === id);
  router.push(summary ? `/p/${id}/${firstCur(summary)}` : `/p/${id}`);
}
</script>

<template>
  <header>
    <div v-if="menu" class="backdrop" @click="menu = null" />
    <RouterLink to="/" class="brand"><span class="logo" />studio</RouterLink>
    <div class="divider" />

    <template v-if="!project">
      <nav class="global">
        <RouterLink v-for="n in globalNav" :key="n.to" :to="n.to" class="nav-item" :class="{ on: n.on }">{{ n.label }}</RouterLink>
      </nav>
      <div class="fill" />
    </template>

    <template v-else>
      <div class="switcher">
        <div class="box" :class="{ on: route.name === 'project', editing: renaming }">
          <input
            v-if="renaming" ref="titleInput" v-model="draft" class="rename"
            @keydown.enter.prevent="endRename(true)" @keydown.esc.prevent="endRename(false)" @blur="endRename(true)"
          >
          <RouterLink v-else :to="`/p/${project.id}`" class="title" :title="t('nav.overview')" @dblclick.prevent="startRename">
            {{ project.title }}
          </RouterLink>
          <button class="edit" :title="t('nav.renameProject')" @click="startRename">✎</button>
          <button class="caret" :title="t('nav.switchProject')" @click="toggle('project')">▾</button>
        </div>
        <div v-if="menu === 'project'" class="menu wide">
          <button v-for="p in store.list" :key="p.id" class="recent" :class="{ on: p.id === project.id }" @click="openProject(p.id)">
            <span class="row"><span class="t">{{ p.title }}</span><span class="size">{{ bytes(p.size) }}</span></span>
            <span class="s">{{ stage(p) }}</span>
          </button>
          <div class="sep" />
          <div class="menu-actions">
            <RouterLink to="/nouveau" class="btn dark">{{ t("nav.newProjectBtn") }}</RouterLink>
            <RouterLink to="/" class="btn">{{ t("nav.allProjects") }}</RouterLink>
          </div>
        </div>
      </div>

      <nav class="phases">
        <div v-for="(g, i) in groups" :key="g.g" class="phase">
          <span v-if="i" class="slash">/</span>
          <button class="phase-btn" :class="{ on: g.on, open: menu === g.g }" :title="g.label" @click="toggle(g.g)">
            <span class="short">{{ g.short }}</span>
            <span class="dots"><span v-for="s in g.items" :key="s.id" class="dot" :style="{ background: s.dot[0], border: s.dot[1] }" /></span>
          </button>
          <div v-if="menu === g.g" class="menu">
            <div class="eyebrow menu-label">{{ g.label }}</div>
            <RouterLink v-for="s in g.items" :key="s.id" :to="`/p/${project.id}/${s.id}`" class="step" :class="{ on: s.on, todo: s.state === 'todo' }">
              <span class="dot" :style="{ background: s.dot[0], border: s.dot[1] }" />
              <span class="label">{{ s.label }}</span>
              <span class="sub">{{ s.sub }}</span>
            </RouterLink>
          </div>
        </div>
      </nav>
      <RouterLink :to="`/p/${project.id}/ressources`" class="nav-item" :class="{ on: route.name === 'resources' }">{{ t("nav.media") }}</RouterLink>
      <div class="divider" />
      <RouterLink to="/bibliotheque" class="nav-item">{{ t("nav.library") }}</RouterLink>
    </template>

    <RouterLink to="/settings" class="nav-item" :class="{ on: route.name === 'settings' }">{{ t("nav.settings") }}</RouterLink>
    <div
      class="worker"
      :class="workerAlive === null ? 'unknown' : workerAlive ? 'ok' : 'down'"
      :title="workerAlive === null ? t('nav.apiUnreachable') : workerAlive ? t('nav.workerAlive') : t('nav.workerDownHint')"
    >
      <span class="wdot" /><span v-if="workerAlive === false">{{ t("nav.workerDown") }}</span>
    </div>
  </header>
</template>

<style scoped>
header {
  flex-shrink: 0; height: 52px; display: flex; align-items: center; gap: 10px; padding: 0 16px;
  background: var(--bg-soft); border-bottom: 1px solid var(--line); position: relative; z-index: 20; white-space: nowrap;
}
.backdrop { position: fixed; inset: 0; z-index: 19; }
.brand { display: flex; align-items: center; gap: 8px; padding: 0 6px; font-size: 16px; font-weight: 600; color: var(--ink) !important; text-decoration: none !important; }
.logo { width: 10px; height: 10px; background: var(--red); }
.divider { width: 1px; height: 22px; background: var(--line-strong); flex-shrink: 0; }
.fill { flex: 1; }
.global { display: flex; gap: 2px; }
.nav-item {
  height: 32px; display: flex; align-items: center; padding: 0 10px; border-radius: 4px; flex-shrink: 0;
  font-size: 13.5px; color: var(--ink) !important; text-decoration: none !important; font-weight: 450;
}
.nav-item:hover { background: var(--hover); }
.nav-item.on { background: #fff; font-weight: 600; }

.switcher { position: relative; flex-shrink: 1; min-width: 120px; max-width: 240px; z-index: 20; }
.box { position: relative; height: 34px; display: flex; align-items: center; background: #fff; border: 1px solid var(--line); border-radius: 4px; }
.box.on, .box.editing { border-color: var(--ink); }
.title {
  flex: 1; min-width: 0; height: 100%; display: flex; align-items: center; padding: 0 26px 0 10px;
  font-size: 13px; font-weight: 600; color: var(--ink) !important; text-decoration: none !important;
  overflow: hidden; text-overflow: ellipsis; border-radius: 4px 0 0 4px;
}
.title:hover { background: var(--bg-soft); }
.rename { flex: 1; min-width: 0; font: inherit; font-size: 13px; font-weight: 600; border: none; outline: none !important; padding: 0 10px; background: transparent; }
.edit {
  position: absolute; right: 32px; top: 50%; transform: translateY(-50%); width: 22px; height: 22px;
  border: none; border-radius: 3px; background: #fff; color: var(--faint); cursor: pointer; font-size: 13px; opacity: 0;
}
.box:hover .edit, .edit:focus-visible { opacity: 1; }
.box.editing .edit { display: none; }
.edit:hover { background: var(--hover); color: var(--ink); }
.caret {
  width: 28px; height: 100%; flex-shrink: 0; border: none; border-left: 1px solid var(--line-soft); border-radius: 0 4px 4px 0;
  background: transparent; font-size: 11px; color: var(--faint); cursor: pointer;
}
.caret:hover { background: var(--bg-soft); }

.menu {
  position: absolute; top: calc(100% + 8px); left: 0; width: 260px; z-index: 30; background: #fff;
  border: 1px solid var(--line-strong); border-radius: 4px; box-shadow: 0 12px 32px rgba(0, 0, 0, .12);
  padding: 6px; display: flex; flex-direction: column; gap: 1px; max-height: 70vh; overflow-y: auto; white-space: normal;
}
.menu.wide { width: 320px; top: calc(100% + 6px); }
.menu-label { font-size: 10.5px; letter-spacing: 0.06em; padding: 6px 10px 4px; }
.recent {
  display: flex; flex-direction: column; gap: 2px; padding: 8px 10px; border-radius: 3px; cursor: pointer;
  border: none; background: transparent; text-align: left; width: 100%;
}
.recent:hover, .recent.on { background: var(--bg-soft); }
.recent .row { display: flex; gap: 10px; align-items: baseline; }
.recent .t { flex: 1; min-width: 0; font-size: 13.5px; line-height: 1.3; }
.recent.on .t { font-weight: 600; }
.recent .size { font-family: var(--mono); font-size: 10.5px; color: var(--faint); }
.recent .s { font-size: 11.5px; color: var(--faint); }
.sep { height: 1px; background: var(--line-soft); margin: 4px 0; }
.menu-actions { display: flex; gap: 6px; padding: 4px; }
.menu-actions .btn { flex: 1; text-decoration: none; color: var(--ink); }
.menu-actions .btn.dark { color: #fff; }

.phases { flex: 1; min-width: 0; display: flex; align-items: center; gap: 2px; }
.phase { position: relative; display: flex; align-items: center; gap: 2px; }
.slash { font-size: 11px; color: var(--dash); padding: 0 2px; }
.phase-btn {
  height: 32px; display: flex; align-items: center; gap: 8px; padding: 0 10px; border-radius: 4px; cursor: pointer;
  background: transparent; border: 1px solid transparent;
}
.phase-btn:hover, .phase-btn.open { background: #fff; }
.phase-btn.on { background: #fff; border-color: var(--line-strong); }
.short { font-family: var(--mono); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted-2); }
.phase-btn.on .short { color: var(--ink); }
.dots { display: flex; gap: 4px; }
.dots .dot { width: 9px; height: 9px; border-radius: 5px; }
.step {
  display: flex; align-items: center; gap: 10px; height: 32px; padding: 0 10px; border-radius: 3px;
  text-decoration: none !important; color: var(--ink-2) !important;
}
.step:hover { background: var(--bg-soft); }
.step.on { background: var(--bg-soft); }
.step .dot { width: 10px; height: 10px; border-radius: 5px; flex-shrink: 0; }
.step .label { flex: 1; font-size: 13.5px; font-weight: 450; }
.step.on .label { font-weight: 600; color: var(--ink); }
.step.todo .label { color: var(--muted-2); }
.step .sub { font-family: var(--mono); font-size: 10.5px; color: var(--faint); }

.worker { display: flex; align-items: center; gap: 6px; padding: 0 4px; font-family: var(--mono); font-size: 10.5px; color: var(--faint); cursor: default; }
.wdot { width: 7px; height: 7px; border-radius: 50%; background: var(--dash); }
.worker.ok .wdot { background: #4CB782; }
.worker.down { color: var(--red-dark); }
.worker.down .wdot { background: var(--red); }
</style>
