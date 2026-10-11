<script setup lang="ts">
/** Onglet Plan du script : le détail du plan choisi dans le texte, sinon la liste des plans. */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import ConfirmX from "../../../components/ConfirmX.vue";
import Thumb from "../../../components/Thumb.vue";
import { duration as fmtDuration } from "../../../lib/format";
import type { Plan, PlanMedia, Setup } from "../../types";
import MediaPanel from "./MediaPanel.vue";
import { colorOf, FILMED, FRAMES, frameLabel, type OrderedPlan, PLAN_TYPES, typeLabel } from "./plans";
import { letterOf, setupColor, setupOfOrdered } from "./setups";

const props = defineProps<{
  ordered: OrderedPlan[];
  active: string | null;
  used: Record<string, number>;
  setups: Setup[];
  /** le setup de chaque section */
  sections: Record<string, string>;
}>();
const emit = defineEmits<{
  select: [id: string | null];
  update: [id: string, changes: Partial<Plan>, delay?: number];
  remove: [id: string];
  /** le plan couvre désormais la sélection du texte */
  reanchor: [id: string];
  show: [id: string];
  /** un nouveau setup, où ce plan se tourne */
  newSetup: [id: string];
}>();

const { t } = useI18n();
const current = computed(() => props.ordered.find((o) => o.plan.id === props.active) ?? null);
const placed = computed(() => props.ordered.filter((o) => o.plan.block));
const detached = computed(() => props.ordered.filter((o) => !o.plan.block));
const picking = ref(false);
watch(() => props.active, () => (picking.value = false));

/** Le rang du setup où se tourne le plan (le sien, sinon celui de sa section), -1 : aucun. */
const setupAt = computed(() => {
  const o = current.value;
  return o ? props.setups.findIndex((s) => s.id === setupOfOrdered(o, props.sections)) : -1;
});
/** La lettre du setup qu'il tient de sa section, s'il n'a pas le sien. */
const inherited = computed(() => (current.value?.plan.setup || setupAt.value < 0 ? "" : letterOf(setupAt.value)));

function pickSetup(e: Event): void {
  const id = value(e), plan = current.value!.plan.id;
  if (id === "new") emit("newSetup", plan);
  else emit("update", plan, { setup: id });
}

const value = (e: Event) => (e.target as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).value;
const cut = (t: string, n: number) => (t.length > n ? t.slice(0, n - 1) + "…" : t);

function addMedia(p: Plan, m: PlanMedia): void {
  if (!p.media.some((x) => x.url === m.url)) emit("update", p.id, { media: [...p.media, m] });
  picking.value = false;
}
</script>

<template>
  <div class="panel">
    <!-- un plan -->
    <template v-if="current">
      <div class="head">
        <button class="link-btn" @click="emit('select', null)">{{ t("script.plan.allPlans") }}</button>
        <span class="num mono">{{ t("script.plan.num", { num: current.num }) }}</span>
      </div>

      <label class="field">
        <span class="k">{{ t("common.type") }}</span>
        <span class="type-row">
          <span class="swatch" :style="{ background: colorOf(current.plan.type) }" />
          <select class="select" :value="current.plan.type" @change="emit('update', current.plan.id, { type: value($event) })">
            <option v-for="pt in PLAN_TYPES" :key="pt" :value="pt">{{ typeLabel(pt) }}</option>
          </select>
          <select v-if="FILMED.includes(current.plan.type)" class="select" :value="current.plan.frame" :title="t('script.plan.framing')"
            @change="emit('update', current.plan.id, { frame: value($event) })">
            <option value="">{{ t("script.plan.framingPick") }}</option>
            <option v-for="f in FRAMES" :key="f" :value="f">{{ frameLabel(f) }}</option>
          </select>
        </span>
      </label>

      <label v-if="FILMED.includes(current.plan.type)" class="field">
        <span class="k">{{ t("script.plan.setup") }}</span>
        <span class="type-row">
          <span class="swatch" :style="{ background: setupAt >= 0 ? setupColor(setupAt) : 'var(--line-strong)' }" />
          <select class="select" :value="current.plan.setup ?? ''" @change="pickSetup($event)">
            <option value="">{{ inherited ? t("script.plan.inherited", { letter: inherited }) : t("script.plan.none") }}</option>
            <option v-for="(st, n) in setups" :key="st.id" :value="st.id">{{ letterOf(n) }}{{ st.name ? ` · ${st.name}` : "" }}</option>
            <option value="new">{{ t("script.plan.newSetup") }}</option>
          </select>
        </span>
      </label>

      <label class="field">
        <span class="k">{{ t("script.plan.note") }}</span>
        <textarea class="note" rows="4" :value="current.plan.note" :placeholder="t('script.plan.notePlaceholder')"
          @input="emit('update', current.plan.id, { note: value($event) }, 600)" />
      </label>

      <div class="field">
        <span class="k">{{ t("script.plan.passage") }}</span>
        <span v-if="current.plan.block" class="q">{{ t("chat.quoted", { q: cut(current.plan.q, 320) }) }}</span>
        <span v-else class="q detached">{{ t("script.plan.detached") }}</span>
        <span class="actions">
          <button v-if="current.plan.block" class="link-btn" @click="emit('show', current.plan.id)">{{ t("script.plan.showInText") }}</button>
          <button class="link-btn" :title="t('script.toasts.selectFirst')" @click="emit('reanchor', current.plan.id)">
            {{ current.plan.block ? t("script.plan.reanchor") : t("script.plan.attach") }}
          </button>
        </span>
      </div>

      <div class="field">
        <span class="k">{{ t("script.plan.files") }}</span>
        <div v-for="m in current.plan.media" :key="m.url" class="file">
          <Thumb :src="m.url" :kind="m.kind" :name="m.name" />
          <span class="fname">{{ m.name }}<span class="mono dur">{{ m.duration ? fmtDuration(m.duration) : "" }}</span></span>
          <button class="x-btn" :title="t('script.plan.removeFile')"
            @click="emit('update', current.plan.id, { media: current.plan.media.filter((x) => x.url !== m.url) })">×</button>
        </div>
        <button v-if="!picking" class="btn sm dashed" @click="picking = true">{{ t("script.plan.addFile") }}</button>
        <div v-else class="picker">
          <button class="link-btn" @click="picking = false">{{ t("common.close") }}</button>
          <MediaPanel :used="used" picking @pick="addMedia(current.plan, $event)" />
        </div>
      </div>

      <div class="foot">
        <button class="check-label" @click="emit('update', current.plan.id, { on: !current.plan.on })">
          <span class="check" :class="{ on: current.plan.on }">{{ current.plan.on ? "✓" : "" }}</span>{{ t("script.plan.done") }}
        </button>
        <ConfirmX :label="t('script.plan.deleteConfirm')" :title="t('script.plan.deleteTitle')" @confirm="emit('remove', current.plan.id)" />
      </div>
    </template>

    <!-- la liste -->
    <template v-else>
      <span class="hint">
        {{ t("script.plan.listHint") }}
      </span>
      <button v-for="o in placed" :key="o.plan.id" class="row" :class="{ on: o.plan.on }"
        @click="emit('select', o.plan.id); emit('show', o.plan.id)">
        <span class="swatch" :style="{ background: colorOf(o.plan.type) }" />
        <span class="num mono">{{ o.num }}</span>
        <span class="txt">
          <span class="t">{{ typeLabel(o.plan.type) }}<template v-if="o.plan.note"> · {{ cut(o.plan.note, 60) }}</template></span>
          <span class="sub">{{ o.section?.label ?? "" }} · {{ t("chat.quoted", { q: cut(o.plan.q, 50) }) }}</span>
        </span>
      </button>
      <span v-if="!placed.length" class="hint">{{ t("script.plan.empty") }}</span>
      <template v-if="detached.length">
        <span class="eyebrow det-title">{{ t("script.plan.detachedTitle") }}</span>
        <button v-for="o in detached" :key="o.plan.id" class="row" @click="emit('select', o.plan.id)">
          <span class="swatch" :style="{ background: colorOf(o.plan.type) }" />
          <span class="num mono">{{ o.num }}</span>
          <span class="txt"><span class="t">{{ typeLabel(o.plan.type) }}<template v-if="o.plan.note"> · {{ cut(o.plan.note, 60) }}</template></span></span>
        </button>
      </template>
    </template>
  </div>
</template>

<style scoped>
.panel { display: flex; flex-direction: column; gap: 14px; flex: 1; min-height: 0; overflow-y: auto; padding: 0 4px 12px 2px; }
.head { display: flex; justify-content: space-between; align-items: center; }
.head .link-btn { font-size: 12px; }
.num { font-size: 11px; color: var(--faint); }
.field { display: flex; flex-direction: column; gap: 6px; }
.k { font-size: 11.5px; color: var(--faint); }
.type-row { display: flex; align-items: center; gap: 8px; }
.swatch { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
.select { height: 28px; border: 1px solid var(--line-strong); border-radius: 4px; background: #fff; font-size: 13px; padding: 0 4px; min-width: 0; }
.note { border: 1px solid var(--line); border-radius: 4px; padding: 8px 10px; font: inherit; font-size: 13.5px; line-height: 1.5; resize: vertical; }
.app .note:focus { outline: none; border-color: #B9B9B4; }
.q { font-size: 13px; font-style: italic; line-height: 1.5; color: var(--ink-3); white-space: pre-line; }
.q.detached { color: var(--red-ink); font-style: normal; }
.actions { display: flex; gap: 14px; flex-wrap: wrap; }
.actions .link-btn { font-size: 12px; }
.file { display: flex; align-items: center; gap: 8px; }
.file :deep(.thumb) { width: 56px; height: 32px; border-radius: 3px; flex-shrink: 0; }
.fname { flex: 1; min-width: 0; font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dur { margin-left: 6px; font-size: 11px; color: var(--faint); }
.dashed { align-self: flex-start; }
.picker { display: flex; flex-direction: column; gap: 6px; padding: 8px; border: 1px solid var(--line); border-radius: 4px; }
.picker > .link-btn { align-self: flex-end; font-size: 12px; }
.foot { display: flex; justify-content: space-between; align-items: center; padding-top: 6px; border-top: 1px solid var(--line-soft); }
.check-label { display: flex; align-items: center; gap: 7px; font-size: 13px; color: var(--ink-3); cursor: pointer; border: none; background: none; padding: 0; }
.check {
  width: 15px; height: 15px; border-radius: 3px; border: 1px solid var(--dash); background: #fff; color: #fff;
  font-size: 10px; display: flex; align-items: center; justify-content: center;
}
.check.on { background: var(--ink); border-color: var(--ink); }
.hint { font-size: 12.5px; color: var(--faint); line-height: 1.5; }
.row {
  display: flex; gap: 8px; align-items: flex-start; padding: 7px 6px; border: none; border-radius: 4px;
  background: transparent; text-align: left; cursor: pointer;
}
.row:hover { background: var(--bg-soft); }
.row.on { opacity: 0.55; }
.row .swatch { margin-top: 4px; }
.row .num { padding-top: 1px; }
.txt { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.txt .t { font-size: 13px; }
.txt .sub { font-size: 11.5px; color: var(--faint); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.det-title { padding-top: 8px; color: var(--red-ink); }
</style>
