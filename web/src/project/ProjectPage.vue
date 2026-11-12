<script setup lang="ts">
/** Une étape d'un projet : une ligne commune (les étapes de la phase en onglets, statut, précédent / suivant) et l'écran de l'étape. */
import { computed, defineAsyncComponent, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { stepGroups } from "./nav";
import { firstCur, stepById, STEPS } from "./steps";
import { act, open, store } from "./store";

const SCREENS: Record<string, ReturnType<typeof defineAsyncComponent>> = {
  angle: defineAsyncComponent(() => import("./steps/AngleStep.vue")),
  titre: defineAsyncComponent(() => import("./steps/TitleStep.vue")),
  vignette: defineAsyncComponent(() => import("./steps/VignetteStep.vue")),
  script: defineAsyncComponent(() => import("./steps/ScriptStep.vue")),
  roast: defineAsyncComponent(() => import("./steps/RoastStep.vue")),
  tournage: defineAsyncComponent(() => import("./steps/TournageStep.vue")),
  derush: defineAsyncComponent(() => import("./steps/DerushStep.vue")),
  transcript: defineAsyncComponent(() => import("./steps/SourceStep.vue")),
  storyboard: defineAsyncComponent(() => import("./steps/StoryboardStep.vue")),
  montage: defineAsyncComponent(() => import("./steps/MontageStep.vue")),
  selection: defineAsyncComponent(() => import("./steps/SelectionStep.vue")),
  smontage: defineAsyncComponent(() => import("./steps/SMontageStep.vue")),
  rendu: defineAsyncComponent(() => import("./steps/RenduStep.vue")),
  description: defineAsyncComponent(() => import("./steps/DescriptionStep.vue")),
  upload: defineAsyncComponent(() => import("./steps/UploadStep.vue")),
};

const { t, locale } = useI18n();
const route = useRoute();
const router = useRouter();
const pid = computed(() => String(route.params.pid));
const project = computed(() => (store.project?.id === pid.value ? store.project : null));
const step = computed(() => stepById(String(route.params.step ?? "")));

watch(pid, async (id) => {
  try {
    await open(id);
  } catch {
    router.replace("/");
  }
}, { immediate: true });

// /p/:id ou une étape pas encore portée : on va à l'étape en cours
watch([project, () => route.params.step], ([p]) => {
  if (p && !step.value) router.replace(`/p/${p.id}/${firstCur(p)}`);
}, { immediate: true });

watch([project, step, locale], ([p, s]) => {
  if (p && s) document.title = `${s.label} · ${p.title} · Daryl`;
}, { immediate: true });

const index = computed(() => (step.value ? STEPS.findIndex((s) => s.id === step.value!.id) : 0));
const prev = computed(() => STEPS[index.value - 1]);
const next = computed(() => STEPS[index.value + 1]);
const state = computed(() => (project.value && step.value ? project.value.status[step.value.id] ?? "todo" : "todo"));
const chip = computed(() => ({
  done: [t("project.state.done"), "var(--ink)", "#fff"], cur: [t("project.state.cur"), "var(--red-bg)", "var(--red-dark)"],
  skip: [t("project.state.skip"), "var(--line-soft)", "var(--muted)"], todo: [t("project.state.todo"), "var(--line-soft)", "var(--muted)"],
}[state.value]));
/** On ne passe aux titres qu'avec un angle retenu. */
const blocked = computed(() => step.value?.id === "angle" && !(project.value && project.value.angle_sel != null
  && project.value.angles[project.value.angle_sel]));

/** les étapes de la phase, en onglets : elles tiennent lieu de titre */
const siblings = computed(() => (project.value && step.value
  ? stepGroups(project.value).find((g) => g.g === step.value!.g)?.items ?? []
  : []));

function toggleDone() {
  if (step.value) act(`/steps/${step.value.id}`, { done: state.value !== "done" });
}
</script>

<template>
  <template v-if="project && step">
    <header>
      <nav class="siblings">
        <RouterLink v-for="s in siblings" :key="s.id" :to="`/p/${project.id}/${s.id}`" class="sib" :class="{ on: s.id === step.id }">
          <span class="dot" :style="{ background: s.dot[0], border: s.dot[1] }" />
          <span class="label">{{ s.label }}</span>
          <span class="sub">{{ s.sub }}</span>
        </RouterLink>
        <!-- le prompteur, outil du tournage sans statut : ouvert à part -->
        <RouterLink v-if="step.g === 'tour'" :to="`/prompteur/${project.id}`" target="_blank" class="sib">
          <span class="dot tool" />
          <span class="label">{{ t("shoot.teleprompter") }}</span>
        </RouterLink>
      </nav>
      <div class="actions">
        <span class="chip" :style="{ background: chip[1], color: chip[2] }">{{ chip[0] }}</span>
        <button class="btn" @click="toggleDone">{{ state === "done" ? t("project.reopen") : t("project.markDone") }}</button>
        <RouterLink v-if="prev" :to="`/p/${project.id}/${prev.id}`" class="btn">← {{ prev.label }}</RouterLink>
        <button v-else class="btn" disabled style="color: var(--off-2)">{{ t("project.start") }}</button>
        <button v-if="next" class="btn dark" :disabled="blocked" :title="blocked ? t('project.needAngle') : ''"
          @click="router.push(`/p/${project.id}/${next.id}`)">{{ next.label }} →</button>
      </div>
    </header>
    <div class="body">
      <component :is="SCREENS[step.id]" :key="`${project.id}-${step.id}`" />
    </div>
  </template>
  <div v-else class="loading eyebrow">{{ t("common.loading") }}</div>
</template>

<style scoped>
header {
  flex-shrink: 0; height: 48px; display: flex; align-items: stretch; justify-content: space-between; gap: 16px;
  padding: 0 24px; border-bottom: 1px solid var(--line); white-space: nowrap;
}
.siblings { display: flex; align-items: stretch; gap: 2px; min-width: 0; overflow-x: auto; overflow-y: hidden; scrollbar-width: none; }
.sib {
  display: flex; align-items: center; gap: 8px; padding: 0 10px; border-bottom: 2px solid transparent;
  text-decoration: none !important; color: var(--muted) !important;
}
.sib:hover { background: var(--bg-soft); }
.sib.on { border-bottom-color: var(--ink); color: var(--ink) !important; }
.sib .dot { width: 8px; height: 8px; border-radius: 4px; flex-shrink: 0; }
.sib .dot.tool { border: 1px dashed var(--dash); }
.sib .label { font-size: 14px; font-weight: 450; }
.sib.on .label { font-weight: 600; }
.sib .sub { font-family: var(--mono); font-size: 10.5px; color: var(--faint); }
.actions { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
.actions .btn { height: 30px; }
.actions a.btn { color: var(--ink); text-decoration: none; }
.chip { font-family: var(--mono); font-size: 11px; padding: 3px 8px; border-radius: 3px; }
.body { flex: 1; min-height: 0; overflow: auto; }
.loading { padding: 32px; }
</style>
