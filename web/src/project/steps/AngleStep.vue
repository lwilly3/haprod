<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { act, failed, running, store, update } from "../store";
import AngleAssistant from "./angle/AngleAssistant.vue";

const router = useRouter();
const { t } = useI18n();
const project = computed(() => store.project!);
const angles = computed(() => project.value.angles);

const briefRows = computed(() => {
  const b = project.value.brief;
  return [
    { k: t("angle.brief.idea"), v: b.idea || "—" },
    { k: t("angle.brief.direction"), v: b.dir || "—" },
    { k: t("angle.brief.duration"), v: b.dur || "—" },
    { k: t("angle.brief.notes"), v: b.notes || "—" },
  ];
});
const refs = computed(() => (project.value.brief.links ?? []).map((l) => ({ text: l, url: /^https?:/.test(l) })));

// --- génération ---------------------------------------------------------------------
const genNote = ref("");
const busy = computed(() => running("angles"));
const error = computed(() => failed("angles"));
/** Angle en cours de réécriture ; null = recherche d'angles. */
const iterIndex = computed(() => {
  const job = project.value.runtime.jobs.angles;
  return busy.value && job?.mode === "iterate" ? job.index ?? null : null;
});

const genLabel = computed(() => busy.value ? t("angle.searching") : angles.value.length ? t("angle.searchMore") : t("angle.search"));
const activity = computed(() => project.value.runtime.jobs.angles?.activity ?? null);
const searching = computed(() => busy.value && iterIndex.value === null);

function generate() {
  if (busy.value) return;
  cmtOpen.value = null;
  act("/angles", { note: genNote.value.trim() });
}

// --- commentaire et itération sur un angle ------------------------------------------
const cmtOpen = ref<number | null>(null);
const cmtText = ref("");

function toggleCmt(i: number) {
  cmtOpen.value = cmtOpen.value === i ? null : i;
  cmtText.value = "";
}

async function iterate(i: number) {
  const note = cmtText.value.trim();
  if (!note || busy.value) return;
  cmtOpen.value = null;
  cmtText.value = "";
  await act("/angles/iterate", { index: i, note });
}

const letter = (i: number) => String.fromCharCode(65 + i);
</script>

<template>
  <div class="wrap">
    <div class="col">
      <section class="brief">
        <div class="brief-head">
          <span class="eyebrow">{{ t("angle.brief.title") }}</span>
          <button class="link-btn" @click="router.push(`/p/${project.id}/brief`)">{{ t("common.edit") }}</button>
        </div>
        <div v-for="b in briefRows" :key="b.k" class="brief-row">
          <span class="k">{{ b.k }}</span>
          <span class="v">{{ b.v }}</span>
        </div>
        <div v-if="refs.length" class="brief-row">
          <span class="k">{{ t("angle.brief.references") }}</span>
          <div v-for="(r, i) in refs" :key="i" class="ref">
            <span class="ref-tag">{{ r.url ? t("angle.brief.link") : t("angle.brief.note") }}</span>
            <a v-if="r.url" :href="r.text" target="_blank" rel="noopener">{{ r.text }}</a>
            <span v-else>{{ r.text }}</span>
          </div>
        </div>
      </section>

      <section class="gen">
        <div class="gen-row">
          <input
            v-model="genNote" class="input soft gen-input"
            :placeholder="t('angle.genPlaceholder')"
            @keydown.enter="generate"
          >
          <button class="btn dark lg gen-btn" @click="generate">{{ genLabel }}</button>
        </div>
        <span class="hint">{{ t("angle.genHint") }}</span>
        <span v-if="error && !busy" class="error">{{ error }}</span>
      </section>

      <div class="list-head">
        <span class="eyebrow">{{ t("angle.listTitle", { n: angles.length }) }}</span>
        <span class="mono meta">{{ angles.length ? t("angle.round", { n: project.angle_round }) : "" }}</span>
      </div>

      <div class="list">
        <div v-if="!angles.length && !busy" class="dashed-box">
          {{ t("angle.empty") }}
        </div>

        <div
          v-for="(a, i) in angles" :key="i" class="angle"
          :class="{ on: i === project.angle_sel, busy: busy && iterIndex === i }"
        >
          <div class="angle-main">
            <span class="letter">{{ letter(i) }}</span>
            <div class="angle-text">
              <div class="angle-title">
                <span class="t">{{ a.t }}</span>
                <span v-if="(a.v ?? 1) > 1" class="v">v{{ a.v }}</span>
              </div>
              <span class="p">{{ a.p }}</span>
              <span v-if="a.why" class="why">{{ a.why }}</span>
              <span v-if="a.note" class="note">{{ t("angle.yourNote", { note: a.note }) }}</span>
            </div>
          </div>
          <div class="angle-actions">
            <button class="pick" @click="update({ angle_sel: i })">{{ i === project.angle_sel ? t("angle.kept") : t("angle.keep") }}</button>
            <button class="btn h30" @click="toggleCmt(i)">{{ t("common.comment") }}</button>
            <span v-if="busy && iterIndex === i" class="mono rewriting">{{ t("angle.rewriting") }}</span>
          </div>
          <div v-if="cmtOpen === i" class="cmt">
            <textarea v-model="cmtText" class="textarea soft" :placeholder="t('angle.cmtPlaceholder')" />
            <div class="cmt-actions">
              <button class="btn dark" :disabled="busy" @click="iterate(i)">{{ t("angle.iterate") }}</button>
              <button class="btn" @click="toggleCmt(i)">{{ t("common.cancel") }}</button>
            </div>
          </div>
        </div>

        <template v-if="searching">
          <div v-for="k in 3" :key="`skel${k}`" class="skel">
            <div style="width: 55%" />
            <div style="width: 35%" />
            <div style="width: 70%" />
          </div>
          <span class="mono meta">{{ t("angle.searchingFromBrief") }}</span>
          <span v-if="activity" class="mono meta">{{ activity }}</span>
        </template>
      </div>
    </div>
    <AngleAssistant class="side" />
  </div>
</template>

<style scoped>
.wrap { padding: 24px 32px 40px; display: flex; gap: 28px; align-items: flex-start; }
.col { display: flex; flex-direction: column; gap: 22px; min-width: 0; max-width: 820px; flex: 1 1 520px; }
/* l'assistant reste visible quand on fait défiler les angles */
.side { position: sticky; top: 24px; height: calc(100vh - 200px); }

.brief { display: flex; flex-direction: column; gap: 2px; padding: 16px 18px; background: var(--bg-soft); border-radius: 4px; }
.brief-head { display: flex; justify-content: space-between; align-items: center; padding-bottom: 6px; }
.brief-row { display: flex; flex-direction: column; gap: 2px; padding: 6px 0; font-size: 14px; line-height: 1.5; }
.brief-row .k { color: var(--faint); font-size: 12px; }
.brief-row .v { text-wrap: pretty; white-space: pre-line; }
.ref { display: flex; align-items: baseline; gap: 8px; font-size: 13px; min-width: 0; }
.ref a, .ref span:last-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ref-tag { font-family: var(--mono); font-size: 10.5px; padding: 1px 6px; border-radius: 3px; background: #fff; color: var(--muted); flex-shrink: 0; }

.gen { display: flex; flex-direction: column; gap: 10px; }
.gen-row { display: flex; gap: 8px; }
.gen-input { flex: 1; height: 40px; }
.gen-btn { font-weight: 500; }
.hint { font-size: 12.5px; color: var(--faint); }
.error { font-size: 12.5px; color: var(--red-dark); }

.list-head { display: flex; justify-content: space-between; align-items: center; }
.meta { font-size: 11px; color: var(--faint); }
.list { display: flex; flex-direction: column; gap: 10px; }

.angle {
  display: flex; flex-direction: column; gap: 12px; padding: 16px; border-radius: 4px;
  border: 1px solid var(--line); background: #fff; transition: opacity .2s;
}
.angle.on { border: 1.5px solid var(--red); background: var(--red-wash); }
.angle.busy { opacity: .55; }
.angle-main { display: flex; gap: 16px; align-items: flex-start; }
.letter { font-family: var(--mono); font-size: 12px; color: var(--faint); width: 20px; padding-top: 3px; }
.angle-text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.angle-title { display: flex; align-items: center; gap: 8px; }
.angle-title .t { font-size: 16px; font-weight: 600; text-wrap: pretty; }
.angle-title .v { font-family: var(--mono); font-size: 10.5px; padding: 2px 6px; border-radius: 3px; background: var(--line-soft); color: var(--muted); }
.p { font-size: 13.5px; color: var(--muted); }
.why { font-size: 13px; color: var(--faint); line-height: 1.45; text-wrap: pretty; }
.note { margin-top: 4px; font-size: 12.5px; color: var(--muted); padding: 6px 10px; background: var(--bg-soft); border-radius: 3px; align-self: flex-start; }
.angle-actions { display: flex; gap: 8px; padding-left: 36px; }
.pick {
  height: 30px; padding: 0 12px; border: none; border-radius: 4px; font-size: 13px; cursor: pointer;
  background: var(--line-soft); color: var(--ink);
}
.pick:hover { background: var(--hover); }
.angle.on .pick { background: var(--red); color: #fff; }
.rewriting { align-self: center; font-size: 11px; color: var(--faint); }
.cmt { display: flex; flex-direction: column; gap: 8px; padding-left: 36px; }
.cmt textarea { min-height: 64px; font-size: 13.5px; border-radius: 3px; }
.cmt-actions { display: flex; gap: 8px; }
.btn.h30, .cmt-actions .btn { height: 30px; }
.cmt-actions .btn.dark { padding: 0 14px; }

.skel {
  display: flex; flex-direction: column; gap: 8px; padding: 16px 16px 16px 52px;
  border: 1px solid var(--line); border-radius: 4px; background: #fff;
}
.skel > div { height: 11px; background: #F3F3F0; border-radius: 2px; }
.skel > div:first-child { height: 14px; background: var(--line-soft); }
</style>
