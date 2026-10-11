<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { bytes, shortDate } from "../lib/format";
import { bars, doneCount, firstCur, stage, STEPS, stepById } from "../project/steps";
import { close, loadList, store } from "../project/store";
import type { ProjectSummary } from "../project/types";

const { t } = useI18n();
const router = useRouter();

onMounted(() => {
  close();
  loadList().catch(() => {});
});

const resume = computed(() => store.list[0]);
const others = computed(() => store.list.slice(1));

function card(p: ProjectSummary) {
  return {
    stage: stage(p), bars: bars(p), date: shortDate(p.updated_at), size: bytes(p.size ?? 0),
    done: t("home.stepsDone", { done: doneCount(p), total: STEPS.length }),
    idea: p.brief.idea || (p.mode === "video" ? t("home.fromVideo") : ""),
  };
}

const cover = (p: ProjectSummary) => p.thumb && `/api/projects/${p.id}/files/${p.thumb.split("/").map(encodeURIComponent).join("/")}`;

function go(p: ProjectSummary) {
  router.push(`/p/${p.id}/${firstCur(p)}`);
}
</script>

<template>
  <div class="page">
    <div class="head">
      <span class="h1">{{ t("nav.projects") }}</span>
      <RouterLink to="/nouveau" class="btn red lg new">{{ t("nav.newProjectBtn") }}</RouterLink>
    </div>

    <div v-if="!store.list.length" class="dashed-box empty">
      {{ t("home.empty") }}
    </div>

    <section v-if="resume">
      <span class="eyebrow">{{ t("home.resume") }}</span>
      <div class="resume" @click="go(resume)">
        <img v-if="cover(resume)" class="thumb" :src="cover(resume)!" alt="">
        <div v-else class="thumb hatch" />
        <div class="info">
          <span class="title">{{ resume.title }}</span>
          <span v-if="card(resume).idea" class="idea">{{ card(resume).idea }}</span>
          <div class="bars wide"><div v-for="(c, i) in card(resume).bars" :key="i" :style="{ background: c }" /></div>
          <div class="cta-row">
            <span class="btn dark md">{{ t("home.continue", { step: stepById(firstCur(resume))?.label ?? "" }) }}</span>
            <span class="meta">{{ card(resume).stage }} · {{ card(resume).done }} · {{ card(resume).size }} · {{ card(resume).date }}</span>
          </div>
        </div>
      </div>
    </section>

    <section v-if="others.length">
      <span class="eyebrow">{{ t("home.others") }}</span>
      <div class="grid">
        <div v-for="p in others" :key="p.id" class="card" @click="go(p)">
          <img v-if="cover(p)" class="thumb" :src="cover(p)!" alt="" loading="lazy">
          <div v-else class="thumb hatch" />
          <div class="names"><span class="t">{{ p.title }}</span><span class="s">{{ card(p).stage }}</span></div>
          <div class="bars"><div v-for="(c, i) in card(p).bars" :key="i" :style="{ background: c }" /></div>
          <div class="foot"><span>{{ card(p).done }}</span><span class="right"><span>{{ card(p).size }}</span><span>{{ card(p).date }}</span></span></div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page { flex: 1; overflow: auto; padding: 32px 40px 48px; display: flex; flex-direction: column; gap: 32px; }
.head { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; }
.h1 { font-size: 26px; font-weight: 600; letter-spacing: -0.015em; }
.new { font-weight: 500; text-decoration: none !important; color: #fff !important; }
.empty { max-width: 720px; }
section { display: flex; flex-direction: column; gap: 10px; }
.resume {
  display: grid; grid-template-columns: minmax(200px, 320px) minmax(0, 1fr); gap: 24px; padding: 16px;
  border: 1px solid var(--line-strong); border-radius: 4px; cursor: pointer;
}
.resume:hover { border-color: var(--ink); }
.thumb { aspect-ratio: 16 / 9; width: 100%; object-fit: cover; display: block; }
.info { display: flex; flex-direction: column; gap: 12px; justify-content: center; min-width: 0; }
.title { font-size: 20px; font-weight: 600; letter-spacing: -0.01em; }
.idea { font-size: 14px; color: var(--muted); line-height: 1.5; text-wrap: pretty; }
.bars { display: flex; gap: 2px; }
.bars.wide { max-width: 420px; }
.bars > div { flex: 1; height: 5px; }
.cta-row { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.meta { font-family: var(--mono); font-size: 12px; color: var(--faint); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 18px; }
.card { border: 1px solid var(--line); border-radius: 4px; padding: 14px; display: flex; flex-direction: column; gap: 12px; cursor: pointer; }
.card:hover { border-color: var(--faint); }
.names { display: flex; flex-direction: column; gap: 3px; }
.names .t { font-size: 15px; font-weight: 600; }
.names .s { font-size: 12.5px; color: var(--muted); }
.foot { display: flex; justify-content: space-between; font-family: var(--mono); font-size: 11.5px; color: var(--faint); }
.foot .right { display: flex; gap: 10px; }
</style>
