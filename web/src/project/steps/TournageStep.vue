<script setup lang="ts">
/**
 * Étape Tournage : la liste des plans, tirée du script (où on les ajoute), et les setups où on les
 * tourne, avec le texte à dire dans chacun. Les rushes s'importent au dérush.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import ConfirmX from "../../components/ConfirmX.vue";
import Seg from "../../components/Seg.vue";
import { usePref } from "../../lib/composables";
import { duration } from "../../lib/format";
import { toast } from "../../lib/toast";
import { store } from "../store";
import SetupList from "./script/SetupList.vue";
import { FILMED, FRAMES, frameLabel, orderPlans, type OrderedPlan, PLAN_TYPES, plain, type Section, sectionsOf, typeLabel } from "./script/plans";
import { letterOf, setupColor, setupOfOrdered, setupStats, setupText, spoken } from "./script/setups";
import { useScript } from "./script/useScript";

const { t } = useI18n();
const project = computed(() => store.project!);
const script = useScript();
const blocks = computed(() => script.blocks.value ?? []);

const scope = usePref<"filmer" | "tous">("tournage.scope", "filmer");
const grouping = usePref<"script" | "type" | "setup">("tournage.group", "script");
const todoOnly = usePref("tournage.todo", false);

const ordered = computed(() => orderPlans(blocks.value, script.plans.value));
const inScope = computed(() => ordered.value.filter((o) => scope.value === "tous" || FILMED.includes(o.plan.type)));
const done = computed(() => inScope.value.filter((o) => o.plan.on).length);

// --- Setups -------------------------------------------------------------------------------

const setups = computed(() => script.setups.value);
const sections = computed(() => script.sections.value);
const indexOf = computed(() => new Map(setups.value.map((s, i) => [s.id, i])));
const parts = computed(() => spoken(blocks.value, script.plans.value, sections.value));

/** Le setup d'une ligne : celui du plan, sinon celui de sa section (face caméra). */
const setupOfRow = (o: OrderedPlan) => setupOfOrdered(o, sections.value);
const letter = (id: string) => (indexOf.value.has(id) ? letterOf(indexOf.value.get(id)!) : "");
const color = (id: string) => (indexOf.value.has(id) ? setupColor(indexOf.value.get(id)!) : "var(--line-strong)");
const setupName = (id: string) => setups.value[indexOf.value.get(id) ?? -1]?.name || t("shoot.setupN", { letter: letter(id) });
const stats = computed(() => setupStats(setups.value, ordered.value, parts.value, sections.value));

/** Le setup d'une section ; un second clic sur le même l'enlève. */
function setSection(section: string, id: string): void {
  const next = { ...sections.value };
  if (next[section] === id) delete next[section];
  else next[section] = id;
  script.setSetups(setups.value, next);
}

async function copySetup(id: string): Promise<void> {
  const text = setupText(parts.value, id);
  if (!text) return;
  await navigator.clipboard.writeText(text);
  toast(id ? t("shoot.setupCopied", { letter: letter(id) }) : t("shoot.noSetupCopied"));
}

// --- La liste ------------------------------------------------------------------------------

const list = computed(() => {
  let all = inScope.value;
  if (grouping.value === "type") {
    all = [...all].sort((a, b) => PLAN_TYPES.indexOf(a.plan.type as never) - PLAN_TYPES.indexOf(b.plan.type as never));
  } else if (grouping.value === "setup") {
    const rank = (o: OrderedPlan) => indexOf.value.get(setupOfRow(o)) ?? Infinity;
    all = [...all].sort((a, b) => rank(a) - rank(b));
  }
  return todoOnly.value ? all.filter((o) => !o.plan.on) : all;
});

type Row =
  | { kind: "plan"; o: OrderedPlan }
  | { kind: "section"; section: Section }
  | { kind: "setup"; id: string }
  | { kind: "detached" };

/** Les lignes : par section (même sans plan, pour lui donner un setup), par setup, ou à plat par type. */
const rows = computed<Row[]>(() => {
  const plan = (o: OrderedPlan): Row => ({ kind: "plan", o });
  if (grouping.value === "type") return list.value.map(plan);
  if (grouping.value === "setup") {
    const out: Row[] = [];
    let last: string | null = null;
    for (const o of list.value) {
      const id = setupOfRow(o);
      if (id !== last) out.push({ kind: "setup", id });
      last = id;
      out.push(plan(o));
    }
    return out;
  }
  const bySection = new Map<string, OrderedPlan[]>();
  for (const o of list.value) {
    const key = o.plan.block ? o.section?.id ?? "" : "detached";
    bySection.set(key, [...(bySection.get(key) ?? []), o]);
  }
  const out: Row[] = (bySection.get("") ?? []).map(plan);
  for (const section of sectionsOf(blocks.value)) {
    out.push({ kind: "section", section }, ...(bySection.get(section.id) ?? []).map(plan));
  }
  const detached = bySection.get("detached") ?? [];
  if (detached.length) out.push({ kind: "detached" }, ...detached.map(plan));
  return out;
});
const rowKey = (r: Row, i: number) => (r.kind === "plan" ? r.o.plan.id : r.kind === "section" ? r.section.id : `${r.kind}-${i}`);

const text = computed(() => Object.fromEntries(blocks.value.map((b) => [b.id, plain(b.md)])));

/** Le passage illustré : celui du plan, sinon le début du paragraphe. */
function passage(block: string | null, q: string): string {
  if (q) return q;
  const t = block ? text.value[block] ?? "" : "";
  return t.length > 110 ? t.slice(0, 108) + "…" : t;
}

const value = (e: Event) => (e.target as HTMLInputElement | HTMLSelectElement).value;
</script>

<template>
  <div class="layout">
    <div class="main">
      <div class="bar">
        <Seg v-model="scope" :options="[['filmer', t('shoot.scope.toFilm')], ['tous', t('shoot.scope.all')]]" />
        <Seg v-model="grouping" :options="[['script', t('shoot.grouping.script')], ['type', t('shoot.grouping.type')], ['setup', t('shoot.grouping.setup')]]" />
        <button class="check-label" @click="todoOnly = !todoOnly">
          <span class="check" :class="{ on: todoOnly }">{{ todoOnly ? "✓" : "" }}</span>{{ t("shoot.todoOnly") }}
        </button>
        <span class="spacer" />
        <span class="count mono">{{ t("shoot.doneCount", { done, total: inScope.length }) }}</span>
        <RouterLink class="btn sm" :to="`/prompteur/${project.id}`" target="_blank">{{ t("shoot.teleprompter") }}</RouterLink>
      </div>

      <div class="row head mono">
        <span /><span>#</span><span>{{ t("shoot.cols.section") }}</span><span>{{ t("shoot.cols.plan") }}</span><span>{{ t("common.type") }}</span><span>{{ t("shoot.cols.setup") }}</span><span>{{ t("shoot.cols.framing") }}</span><span />
      </div>
      <template v-for="(r, i) in rows" :key="rowKey(r, i)">
        <div v-if="r.kind === 'section'" class="group">
          <span class="group-title">{{ r.section.label }}<span v-if="r.section.title" class="group-sub"> — {{ r.section.title }}</span></span>
          <span class="spacer" />
          <span v-if="setups.length" class="pills">
            <button v-for="(st, n) in setups" :key="st.id" class="pill mono" :class="{ on: sections[r.section.id] === st.id }"
              :style="{ '--c': setupColor(n) }" :title="t('script.editor.sectionShotIn', { setup: `${letterOf(n)}${st.name ? ' · ' + st.name : ''}` })"
              @click="setSection(r.section.id, st.id)">
              {{ letterOf(n) }}
            </button>
          </span>
        </div>
        <div v-else-if="r.kind === 'setup'" class="group">
          <span v-if="r.id" class="badge mono" :style="{ background: color(r.id) }">{{ letter(r.id) }}</span>
          <span class="group-title">{{ r.id ? setupName(r.id) : t("shoot.noSetup") }}</span>
          <span v-if="stats[r.id]?.seconds" class="group-sub mono">{{ t("shoot.textLength", { d: duration(stats[r.id].seconds) }) }}</span>
          <span class="spacer" />
          <button v-if="stats[r.id]?.seconds" class="btn sm" @click="copySetup(r.id)">{{ t("shoot.copyText") }}</button>
        </div>
        <div v-else-if="r.kind === 'detached'" class="group"><span class="group-title">{{ t("shoot.detached") }}</span></div>
        <div v-else class="row" :class="{ on: r.o.plan.on }">
          <button class="box" :class="{ on: r.o.plan.on }" :title="t('shoot.doneTitle')" @click="script.updatePlan(r.o.plan.id, { on: !r.o.plan.on })">
            {{ r.o.plan.on ? "✓" : "" }}
          </button>
          <span class="num mono">{{ r.o.num }}</span>
          <span class="sec-label">{{ r.o.plan.block ? r.o.section?.label ?? "—" : t("shoot.detachedOne") }}</span>
          <div class="plan">
            <input class="note" :value="r.o.plan.note" :placeholder="t('shoot.notePlaceholder')"
              @input="script.updatePlan(r.o.plan.id, { note: value($event) }, 500)">
            <RouterLink v-if="r.o.plan.block" class="q ellipsis" :to="`/p/${project.id}/script?b=${r.o.plan.block}`"
              :title="t('shoot.seeInScript')">{{ t("chat.quoted", { q: passage(r.o.plan.block, r.o.plan.q) }) }}</RouterLink>
            <span v-if="r.o.plan.media.length" class="files mono">{{ r.o.plan.media.map((m) => "@" + m.name).join("  ") }}</span>
          </div>
          <select class="select" :value="r.o.plan.type" @change="script.updatePlan(r.o.plan.id, { type: value($event) })">
            <option v-for="pt in PLAN_TYPES" :key="pt" :value="pt">{{ typeLabel(pt) }}</option>
          </select>
          <select v-if="FILMED.includes(r.o.plan.type)" class="select setup-select" :style="{ '--c': color(setupOfRow(r.o)) }"
            :value="r.o.plan.setup ?? ''" @change="script.updatePlan(r.o.plan.id, { setup: value($event) })">
            <option value="">{{ !r.o.plan.setup && setupOfRow(r.o) ? t("shoot.fromSection", { letter: letter(setupOfRow(r.o)) }) : "—" }}</option>
            <option v-for="(st, n) in setups" :key="st.id" :value="st.id">{{ letterOf(n) }}{{ st.name ? ` · ${st.name}` : "" }}</option>
          </select>
          <span v-else />
          <select v-if="FILMED.includes(r.o.plan.type)" class="select" :value="r.o.plan.frame"
            @change="script.updatePlan(r.o.plan.id, { frame: value($event) })">
            <option value="">—</option>
            <option v-for="f in FRAMES" :key="f" :value="f">{{ frameLabel(f) }}</option>
          </select>
          <span v-else />
          <ConfirmX :title="t('script.plan.deleteTitle')" @confirm="script.removePlan(r.o.plan.id)" />
        </div>
      </template>
      <div v-if="script.blocks.value && !list.length" class="hint empty">
        <template v-if="inScope.length">{{ t("shoot.allDone") }}</template>
        <template v-else>
          {{ t("shoot.empty") }}
          <RouterLink :to="`/p/${project.id}/script`">{{ t("shoot.goToScript") }}</RouterLink>
        </template>
      </div>
    </div>

    <aside class="side">
      <SetupList :setups="setups" :stats="stats" :parts="parts"
        @change="(value, delay) => script.setSetups(value, sections, delay)" />
    </aside>
  </div>
</template>

<style scoped>
.layout { padding: 20px 32px 40px; display: flex; flex-wrap: wrap; gap: 32px; align-items: flex-start; }
.main { display: flex; flex-direction: column; flex: 1 1 620px; min-width: 0; }
.bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding-bottom: 14px; }
.spacer { flex: 1; }
.count { font-size: 12px; color: var(--muted); }
.check-label { display: flex; align-items: center; gap: 7px; font-size: 13px; color: var(--ink-3); cursor: pointer; border: none; background: none; padding: 0; }
.check, .box {
  width: 14px; height: 14px; border-radius: 3px; border: 1px solid var(--dash); background: #fff;
  color: #fff; font-size: 10px; display: flex; align-items: center; justify-content: center; padding: 0; flex-shrink: 0;
}
.box { width: 18px; height: 18px; font-size: 11px; cursor: pointer; }
.check.on, .box.on { background: var(--ink); border-color: var(--ink); }
.hint { font-size: 13px; color: var(--muted-2); }
.hint.empty { font-size: 13.5px; padding: 20px 0; }

.row {
  display: grid; grid-template-columns: 22px 28px 92px minmax(0, 1fr) 128px 112px 104px minmax(16px, auto); gap: 12px;
  padding: 10px 0; border-bottom: 1px solid var(--line-soft); align-items: center;
}
.row.on { background: var(--bg-softer); }
.row.head { padding: 8px 0; font-size: 10.5px; color: var(--faint); text-transform: uppercase; border-bottom-color: var(--line); }
.num { font-size: 11.5px; color: var(--red-ink); }
.sec-label { font-size: 12.5px; color: var(--muted); }
.plan { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.note { border: none; padding: 0; font-size: 13.5px; background: transparent; color: var(--ink); min-width: 0; }
.app .note:focus { outline: none; }
.q { font-size: 12px; font-style: italic; line-height: 1.45; color: var(--muted-2) !important; text-decoration: none !important; }
.q:hover { color: var(--ink) !important; }
.files { font-size: 11px; color: var(--faint); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ellipsis { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.select {
  height: 26px; border: 1px solid var(--line-strong); border-radius: 4px; background: #fff;
  font-size: 12.5px; padding: 0 4px; color: var(--ink-2); cursor: pointer; min-width: 0;
}
.setup-select { border-left: 3px solid var(--c); }

.group { display: flex; align-items: center; gap: 8px; padding: 18px 0 6px; border-bottom: 1px solid var(--line); }
.group-title { font-size: 13px; font-weight: 600; color: var(--ink-2); }
.group-sub { font-size: 12px; font-weight: 400; color: var(--muted-2); }
.pills { display: flex; gap: 4px; }
.pill {
  width: 22px; height: 22px; border-radius: 4px; border: 1px solid var(--line-strong); background: #fff;
  font-size: 11.5px; color: var(--muted); cursor: pointer; padding: 0;
}
.pill:hover { border-color: var(--c); color: var(--c); }
.pill.on { background: var(--c); border-color: var(--c); color: #fff; }
.badge {
  width: 20px; height: 20px; border-radius: 4px; color: #fff; font-size: 11.5px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
}

.side { flex: 0 1 300px; position: sticky; top: 20px; }

</style>
