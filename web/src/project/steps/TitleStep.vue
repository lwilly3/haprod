<script setup lang="ts">
/**
 * Titre : Claude dérive des titres de l'angle retenu (20 sur trois formules, 10 plus libres) ; on en retient
 * jusqu'à 3 pour l'A/B test.
 */
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { toast } from "../../lib/toast";
import { act, failed, running, store, update } from "../store";
import type { Title } from "../types";

const MAX = 3;
// au-delà, le titre est coupé sur mobile
const MOBILE_CHARS = 60;

const router = useRouter();
const { t } = useI18n();
const project = computed(() => store.project!);
const angle = computed(() => {
  const p = project.value;
  return p.angle_sel != null ? p.angles[p.angle_sel] ?? null : null;
});
const titles = computed(() => project.value.titles);
const picked = computed(() => titles.value.filter((x) => x.pick));

// --- génération ---------------------------------------------------------------------
const note = ref("");
const JOB = "titles";
const busy = computed(() => running(JOB));

/** Les propositions de Claude non retenues, puis les titres ajoutés à la main. */
const columns = computed(() => {
  const cols = [{
    id: "claude", label: t("title.daryl"), titles: titles.value.filter((x) => !x.pick && x.ai),
    busy: busy.value, error: failed(JOB), activity: project.value.runtime.jobs[JOB]?.activity ?? null,
    advice: project.value.titles_advice || "",
  }];
  const mine = titles.value.filter((x) => !x.pick && !x.ai);
  return mine.length
    ? [...cols, { id: "mine", label: t("title.mine"), titles: mine, busy: false, error: null, activity: null, advice: "" }]
    : cols;
});

function generate() {
  if (busy.value) return;
  act("/titles", { note: note.value.trim() });
}

// --- liste --------------------------------------------------------------------------
function save(next: Title[], delay = 0) {
  update({ titles: next }, delay);
}

function togglePick(title: Title) {
  if (!title.pick && picked.value.length >= MAX) {
    toast(t("title.maxPicked", { n: MAX }), true);
    return;
  }
  save(titles.value.map((x) => (x === title ? { ...x, pick: !x.pick } : x)));
}

function edit(title: Title, text: string) {
  save(titles.value.map((x) => (x === title ? { ...x, t: text } : x)), 500);
}

function remove(title: Title) {
  // les positions changent : on replie tout plutôt que de déplier le voisin
  opened.value = new Set();
  save(titles.value.filter((x) => x !== title));
}

/** Les titres dépliés (justification visible), par colonne et position. */
const opened = ref(new Set<string>());
const isOpen = (col: string, i: number) => opened.value.has(`${col}:${i}`);

function toggleOpen(col: string, i: number) {
  const key = `${col}:${i}`;
  const next = new Set(opened.value);
  if (!next.delete(key)) next.add(key);
  opened.value = next;
}

const manual = ref("");

function addManual() {
  const text = manual.value.trim();
  if (!text) return;
  const pick = picked.value.length < MAX;
  save([...titles.value, { t: text, pattern: "", why: "", pick }]);
  manual.value = "";
}

const letter = (i: number) => String.fromCharCode(65 + i);
</script>

<template>
  <div class="wrap">
    <div class="angle">
      <span class="eyebrow">{{ t("title.keptAngle") }}</span>
      <span class="angle-t">{{ angle?.t ?? t("title.noAngle") }}</span>
      <button class="link-btn" @click="router.push(`/p/${project.id}/angle`)">{{ t("common.change") }}</button>
    </div>

    <section class="ab">
      <span class="eyebrow">{{ t("title.keptForAb", { n: picked.length, max: MAX }) }}</span>
      <div class="slots">
        <div v-for="k in MAX" :key="k" class="slot" :class="{ empty: !picked[k - 1] }">
          <span class="letter">{{ letter(k - 1) }}</span>
          <template v-if="picked[k - 1]">
            <textarea
              class="t-input" rows="1" :value="picked[k - 1].t"
              @input="edit(picked[k - 1], ($event.target as HTMLTextAreaElement).value)"
              @keydown.enter.prevent="($event.target as HTMLTextAreaElement).blur()"
            />
            <span class="mono count" :class="{ long: picked[k - 1].t.length > MOBILE_CHARS }">{{ picked[k - 1].t.length }}</span>
            <button class="btn h30" @click="togglePick(picked[k - 1])">{{ t("common.remove") }}</button>
          </template>
          <span v-else class="placeholder">{{ t("title.slotEmpty") }}</span>
        </div>
      </div>
      <div class="manual">
        <input v-model="manual" class="input soft" :placeholder="t('title.manualPlaceholder')" @keydown.enter="addManual">
        <button class="btn" :disabled="!manual.trim()" @click="addManual">{{ t("common.add") }}</button>
      </div>
    </section>

    <section class="gen">
      <div class="gen-row">
        <input
          v-model="note" class="input soft gen-input"
          :placeholder="t('title.genPlaceholder')"
          @keydown.enter="generate()"
        >
        <button class="btn dark lg gen-btn" :disabled="busy" @click="generate()">
          {{ busy ? t("title.running") : titles.some((x) => x.ai) ? t("common.rerun") : t("title.generate") }}
        </button>
      </div>
      <span class="hint">
        {{ t("title.genHint") }}
      </span>
    </section>

    <div class="columns">
      <section v-for="c in columns" :key="c.id" class="column">
        <div class="col-head">
          <span class="col-title">{{ c.label }}</span>
          <span v-if="c.error && !c.busy" class="error">{{ c.error }}</span>
          <details v-if="c.advice && c.titles.length && !c.busy" class="advice">
            <summary>{{ t("title.advice") }}</summary>
            {{ c.advice }}
          </details>
        </div>

        <div v-if="!c.titles.length && !c.busy" class="dashed-box">{{ t("title.noProposal") }}</div>

        <div v-if="c.titles.length" class="rows">
          <div v-for="(ti, i) in c.titles" :key="`${project.titles_round}-${i}`" class="row" :class="{ top: ti.top }">
            <div class="row-main">
              <button
                class="icon chevron" :class="{ open: isOpen(c.id, i) }" :title="isOpen(c.id, i) ? t('title.collapse') : t('title.why')"
                @click="toggleOpen(c.id, i)"
              >›</button>
              <span v-if="ti.top" class="star" :title="t('title.recommended')">★</span>
              <textarea
                class="t-input" rows="1" :value="ti.t"
                @input="edit(ti, ($event.target as HTMLTextAreaElement).value)"
                @keydown.enter.prevent="($event.target as HTMLTextAreaElement).blur()"
              />
              <span class="mono count" :class="{ long: ti.t.length > MOBILE_CHARS }">{{ ti.t.length }}</span>
              <button class="icon keep" :disabled="picked.length >= MAX" :title="t('title.keepForAb')" @click="togglePick(ti)">+</button>
              <button class="icon drop" :title="t('common.dismiss')" @click="remove(ti)">×</button>
            </div>
            <div v-if="isOpen(c.id, i)" class="row-more">
              <span v-if="ti.pattern" class="tag">{{ ti.pattern }}</span>
              <span class="why">{{ ti.why || t("title.noWhy") }}</span>
            </div>
          </div>
        </div>

        <template v-if="c.busy">
          <div v-for="k in 3" :key="`skel${k}`" class="skel">
            <div style="width: 75%" />
            <div style="width: 50%" />
          </div>
          <span v-if="c.activity" class="mono meta">{{ c.activity }}</span>
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.wrap { padding: 24px 32px 40px; display: flex; flex-direction: column; gap: 22px; }
.ab, .gen { max-width: 860px; }

.angle { display: flex; align-items: center; gap: 12px; font-size: 14px; }
.angle-t { font-weight: 600; }

.ab { display: flex; flex-direction: column; gap: 10px; padding: 16px 18px; background: var(--bg-soft); border-radius: 4px; }
.slots { display: flex; flex-direction: column; gap: 8px; }
.slot {
  display: flex; align-items: center; gap: 12px; min-height: 46px; padding: 6px 12px;
  border: 1.5px solid var(--red); background: #fff; border-radius: 4px;
}
.slot.empty { border: 1px dashed var(--dash); background: transparent; }
.letter { font-family: var(--mono); font-size: 12px; color: var(--faint); width: 14px; flex-shrink: 0; }
.placeholder { font-size: 13px; color: var(--faint); }
.manual { display: flex; gap: 8px; padding-top: 4px; }
.manual .input { flex: 1; height: 34px; padding: 0 10px; font-size: 13.5px; border-radius: 3px; }
.manual .btn { height: 34px; }

/* le titre se lit en entier : il passe à la ligne plutôt que d'être coupé */
.t-input {
  flex: 1; min-width: 0; border: none; background: transparent; padding: 2px 0;
  font: inherit; font-size: 16px; font-weight: 600; line-height: 1.4; color: var(--ink); outline: none;
  resize: none; overflow: hidden; field-sizing: content;
}
.t-input:focus { box-shadow: 0 1px 0 var(--ink); }
.count { font-size: 11px; color: var(--faint); flex-shrink: 0; }
.count.long { color: var(--red-dark); }

.gen { display: flex; flex-direction: column; gap: 10px; }
.gen-row { display: flex; gap: 8px; }
.gen-input { flex: 1; height: 40px; }
.gen-btn { font-weight: 500; }
.hint { font-size: 12.5px; color: var(--faint); }
.error { font-size: 12.5px; color: var(--red-dark); }
.meta { font-size: 11px; color: var(--faint); }

/* les propositions et les tiens côte à côte, l'un sous l'autre sur un écran étroit */
.columns { display: flex; flex-wrap: wrap; gap: 28px 24px; align-items: flex-start; }
.column { flex: 1 1 480px; display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.col-head { display: flex; flex-direction: column; gap: 4px; padding-bottom: 4px; }
.col-title { font-size: 12.5px; font-weight: 600; }
.advice { font-size: 13px; line-height: 1.5; color: var(--muted); text-wrap: pretty; }
.advice summary { cursor: pointer; font-size: 12.5px; color: var(--faint); }
.advice[open] { padding: 6px 10px 8px; background: var(--bg-soft); border-radius: 3px; }

/* une ligne par titre : le titre d'abord, la justification se déplie */
.rows { display: flex; flex-direction: column; border: 1px solid var(--line); border-radius: 4px; background: #fff; }
.row + .row { border-top: 1px solid var(--line-soft); }
.row-main { display: flex; align-items: center; gap: 6px; padding: 3px 6px 3px 2px; }
.row:hover { background: var(--bg-soft); }
.row .t-input { font-size: 14px; font-weight: 500; }
.row.top .t-input { font-weight: 600; }
.star { font-size: 12px; color: var(--red); flex-shrink: 0; }
.row-more { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; padding: 0 12px 8px 30px; }
.tag { font-family: var(--mono); font-size: 10.5px; padding: 2px 6px; border-radius: 3px; background: var(--line-soft); color: var(--muted); }
.why { font-size: 12.5px; color: var(--muted); line-height: 1.45; text-wrap: pretty; }

.icon {
  width: 26px; height: 26px; flex-shrink: 0; border: none; border-radius: 3px; background: transparent;
  color: var(--faint); font-size: 16px; line-height: 1; cursor: pointer;
}
.icon:hover:not(:disabled) { background: var(--hover); color: var(--ink); }
.icon:disabled { color: var(--off-2); cursor: default; }
.chevron { width: 22px; transition: transform .15s; }
.chevron.open { transform: rotate(90deg); }
.keep:hover:not(:disabled) { background: var(--red); color: #fff; }
.btn.h30 { height: 30px; }

.skel {
  display: flex; flex-direction: column; gap: 8px; padding: 14px;
  border: 1px solid var(--line); border-radius: 4px; background: #fff;
}
.skel > div { height: 11px; background: #F3F3F0; border-radius: 2px; }
.skel > div:first-child { height: 14px; background: var(--line-soft); }
</style>
