<script setup lang="ts">
/**
 * Roasting : Claude relit le script avec la grille du skill youtube-scriptwriting. Chaque run rend
 * une note et une décision, une note par critère, une fiche par section, la courbe d'intérêt
 * prédite, les boucles ouvertes, les promesses tenues ou non, et des remarques ancrées sur les
 * blocs du script, qu'on traite ou écarte (les écartées ne reviennent pas aux runs suivants).
 * Chaque élément se discute avec Claude dans le panneau de droite (« Discuter »).
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { locale } from "../../i18n";
import { api, post, putJson } from "../../lib/api";
import { usePolling, usePref } from "../../lib/composables";
import { mmss } from "../../lib/format";
import { toast } from "../../lib/toast";
import ConfirmX from "../../components/ConfirmX.vue";
import Seg from "../../components/Seg.vue";
import { act, store } from "../store";
import type { RoastFinding, RoastList, RoastRun } from "../types";
import InterestCurve from "./roast/InterestCurve.vue";
import RoastAssistant from "./roast/RoastAssistant.vue";
import { decisionLabel, delta, fmt, scoreColor, severityLabel, sourceLabel } from "./roast/roast";
import { plain, sectionsOf, timing } from "./script/plans";
import type { Block } from "./script/useScript";

const { t } = useI18n();
const router = useRouter();
const project = computed(() => store.project!);
const url = `/api/projects/${project.value.id}/roasts`;

const data = ref<RoastList | null>(null);
/** le script tel qu'il est maintenant : une remarque dont le bloc a changé depuis le roast est signalée */
const current = ref<Record<string, string>>({});
const selId = ref<string | null>(null);

const runs = computed(() => data.value?.runs ?? []);
const busy = computed(() => runs.value.find((r) => !r.finished) ?? null);
const done = computed(() => runs.value.filter((r) => r.status === "done" && r.result));
const run = computed(() => done.value.find((r) => r.id === selId.value) ?? done.value[0] ?? null);
/** le roast terminé d'avant celui affiché : les écarts de notes */
const prev = computed(() => {
  const i = done.value.findIndex((r) => r.id === run.value?.id);
  return i >= 0 ? done.value[i + 1] ?? null : null;
});
const lastError = computed(() => {
  const r = runs.value[0];
  return r && r.status === "error" ? r.error : null;
});

async function loadScript(): Promise<void> {
  const s = await api<{ blocks: Block[] }>(`/api/projects/${project.value.id}/script`);
  current.value = Object.fromEntries(s.blocks.map((b) => [b.id, b.md]));
}

async function load(): Promise<void> {
  const wasBusy = busy.value?.id;
  data.value = await api<RoastList>(url);
  // le roast qu'on attendait vient de finir : on l'affiche
  if (wasBusy && !busy.value && done.value.some((r) => r.id === wasBusy)) selId.value = wasBusy;
}

usePolling(async () => {
  await load();
  return busy.value ? 2000 : 30000;
});
loadScript().catch(() => {});

// --- lancement ---------------------------------------------------------------------------

const mode = usePref<"froid" | "contexte">("roast.mode", "froid");
const note = ref("");

async function launch(): Promise<void> {
  if (await act("/roasts", { cold: mode.value === "froid", note: note.value })) {
    note.value = "";
    await Promise.all([load(), loadScript()]);
  }
}

function stop(): void {
  act("/jobs/roast/stop").then(load);
}

async function remove(r: RoastRun): Promise<void> {
  try {
    await api(`${url}/${r.id}`, { method: "DELETE" });
    if (selId.value === r.id) selId.value = null;
    await load();
  } catch (e) {
    toast((e as Error).message, true);
  }
}

const when = (t: number) => new Date(t * 1000).toLocaleString(locale(), { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const runLabel = (r: RoastRun) => t("roast.run.label", {
  when: when(r.created_at), mode: t(r.cold ? "roast.run.cold" : "roast.run.context"), score: fmt(r.result!.verdict.score),
});

// --- lecture d'un roast -------------------------------------------------------------------

const time = computed(() => timing(run.value?.blocks ?? []));
const textOf = computed(() => Object.fromEntries((run.value?.blocks ?? []).map((b) => [b.id, b.md])));
const at = (block: string) => (block && block in time.value.times ? mmss(time.value.times[block]) : null);

const criteria = computed(() => {
  const before = Object.fromEntries((prev.value?.result?.criteria ?? []).map((c) => [c.key, c.score]));
  return (run.value?.result?.criteria ?? []).map((c) => ({
    ...c, label: data.value?.criteria[c.key] ?? c.key, delta: delta(c.score, before[c.key]),
  }));
});

/** Les fiches de section, avec la durée calculée ici (et non par Claude). */
const sections = computed(() => {
  const r = run.value;
  if (!r?.result) return [];
  const secs = sectionsOf(r.blocks);
  const end = (time.value.words / 150) * 60;
  const by = Object.fromEntries(r.result.sections.map((s) => [s.block, s]));
  return secs.map((s, i) => {
    const next = secs[i + 1];
    return { ...s, start: time.value.times[s.id], dur: (next ? time.value.times[next.id] : end) - time.value.times[s.id],
      fiche: by[s.id] ?? null, open: open.value.filter((f) => sectionOf(f) === s.id).length };
  });
});
type SectionRow = (typeof sections.value)[number];

/** La section de chaque bloc (le dernier titre ## au-dessus) ; PRE avant le premier titre. */
const PRE = "_pre", NONE = "_none";
const sectionByBlock = computed(() => {
  const out: Record<string, string> = {};
  let cur = PRE;
  for (const b of run.value?.blocks ?? []) {
    if (/^##\s/.test(b.md)) cur = b.id;
    out[b.id] = cur;
  }
  return out;
});
const sectionOf = (f: RoastFinding) => (f.block && sectionByBlock.value[f.block]) || NONE;

const unclosed = computed(() => (run.value?.result?.loops ?? []).filter((l) => !l.close).length);

// --- remarques ----------------------------------------------------------------------------

const sev = ref<"all" | "bloquant" | "important" | "detail">("all");
const cat = ref<string | null>(null);
const sec = ref<string | null>(null);
const grouping = usePref<"section" | "liste">("roast.grouping", "section");
const showClosed = ref(false);

const findings = computed(() => run.value?.result?.findings ?? []);
const markOf = (f: RoastFinding) => run.value?.marks[f.id] ?? null;
const open = computed(() => findings.value.filter((f) => !markOf(f)));
const shown = computed(() => findings.value.filter((f) => (showClosed.value || !markOf(f))
  && (sev.value === "all" || f.severity === sev.value) && (!cat.value || f.category === cat.value)
  && (!sec.value || sectionOf(f) === sec.value)));
const sevCount = (s: string) => open.value.filter((f) => f.severity === s).length;
const sevOptions = computed(() => [
  ["all", t("roast.findings.all", { n: open.value.length })] as const,
  ...(["bloquant", "important", "detail"] as const).map((s) => [s, `${severityLabel(s)} · ${sevCount(s)}`] as const),
]);

const RANK: Record<string, number> = { bloquant: 0, important: 1, detail: 2 };
const secName = (id: string) => {
  if (id === PRE) return t("roast.sections.pre");
  if (id === NONE) return t("roast.sections.none");
  const s = sections.value.find((x) => x.id === id);
  return s ? [s.label, s.title].filter(Boolean).join(" — ") : t("roast.sections.section");
};

/** Les remarques affichées, par section dans l'ordre du script, la plus grave d'abord dans chacune. */
const groups = computed(() => {
  if (grouping.value === "liste") return [{ id: "all", name: "", start: null as number | null, items: shown.value }];
  const order = [PRE, ...sections.value.map((s) => s.id), NONE];
  return order.map((id) => ({
    id, name: secName(id), start: id in time.value.times ? time.value.times[id] : null,
    items: shown.value.filter((f) => sectionOf(f) === id).sort((a, b) => RANK[a.severity] - RANK[b.severity]),
  })).filter((g) => g.items.length);
});

/** Le bloc d'une remarque a-t-il changé depuis le roast ? */
function drift(f: RoastFinding): string | null {
  if (!f.block) return t("roast.drift.notFound");
  if (!(f.block in current.value)) return t("roast.drift.deleted");
  return current.value[f.block] !== textOf.value[f.block] ? t("roast.drift.edited") : null;
}

async function mark(f: RoastFinding, m: "done" | "ignored"): Promise<void> {
  const r = run.value!;
  const next = markOf(f) === m ? null : m;
  const before = { ...r.marks };
  if (next) r.marks = { ...r.marks, [f.id]: next };
  else r.marks = Object.fromEntries(Object.entries(r.marks).filter(([k]) => k !== f.id));
  try {
    await putJson(`${url}/${r.id}/marks`, { marks: { [f.id]: next } });
  } catch (e) {
    r.marks = before;
    toast((e as Error).message, true);
  }
}

const toFindings = () => document.getElementById("roast-findings")?.scrollIntoView({ behavior: "smooth", block: "start" });

function filterCat(key: string): void {
  cat.value = cat.value === key ? null : key;
  toFindings();
}

function filterSec(id: string): void {
  sec.value = sec.value === id ? null : id;
  toFindings();
}

// --- discussion ---------------------------------------------------------------------------

/** l'élément du roast joint au prochain message de la discussion */
const quote = ref<string | null>(null);
const discuss = (text: string) => { quote.value = text; };
const score = (n: number) => `${fmt(n)}/10`;

const aboutCrit = (c: (typeof criteria.value)[number]) => t("roast.about.crit", { label: c.label, score: score(c.score), why: c.why });
const aboutSection = (s: SectionRow) => [
  t("roast.about.section", { name: [s.label, s.title].filter(Boolean).join(" — "), start: mmss(s.start), dur: mmss(s.dur) }),
  s.fiche ? t(s.fiche.payoff ? "roast.about.withPayoff" : "roast.about.withoutPayoff", { score: score(s.fiche.score) })
    + (s.fiche.too_long ? t("roast.about.tooLong") : "") : "",
  s.fiche ? `${s.fiche.role} — ${s.fiche.verdict}` : "",
].filter(Boolean).join("\n");
const aboutLoop = (l: { question: string; open: string; close: string }) => t("roast.about.loop", {
  q: l.question, open: at(l.open), close: l.close ? t("roast.about.closedAt", { t: at(l.close) }) : t("roast.neverClosed"),
});
const aboutPromise = (p: { source: string; promise: string; block: string; note: string }) => t("roast.about.promise", {
  source: sourceLabel(p.source), promise: p.promise, note: p.note,
  kept: p.block ? t("roast.promises.keptAt", { t: at(p.block) }) : t("roast.promises.notKept"),
});
const aboutFinding = (f: RoastFinding) => [
  t("roast.about.finding", {
    sev: severityLabel(f.severity).toLowerCase(), cat: data.value?.categories[f.category] ?? f.category,
    at: f.block ? t("roast.about.findingAt", { t: at(f.block) }) : "", problem: f.problem,
  }),
  f.quote || f.block ? t("roast.about.passage", { q: f.quote || plain(textOf.value[f.block] ?? "") }) : "",
  t("roast.about.proposedFix", { fix: f.fix }),
].filter(Boolean).join("\n");

function goTo(block: string): void {
  if (block) router.push({ path: `/p/${project.value.id}/script`, query: { b: block } });
}

/** La remarque part dans une nouvelle discussion de l'assistant du script, sur le passage visé. */
async function ask(f: RoastFinding): Promise<void> {
  const quote = f.quote || plain(current.value[f.block] ?? textOf.value[f.block] ?? "");
  const text = t("roast.about.ask", { cat: data.value?.categories[f.category] ?? f.category, problem: f.problem, fix: f.fix });
  try {
    await post(`/api/projects/${project.value.id}/chat/script`, { text, quote: quote || null, thread: null });
  } catch (e) {
    toast((e as Error).message, true);
    return;
  }
  localStorage.setItem("studio.script.side", JSON.stringify("assistant"));
  router.push({ path: `/p/${project.value.id}/script`, query: f.block ? { b: f.block } : {} });
}
</script>

<template>
  <div class="page">
    <div class="wrap">
      <!-- lancement -->
      <section class="launch">
        <div class="launch-row">
          <Seg v-model="mode" :options="[['froid', t('roast.mode.cold')], ['contexte', t('roast.mode.context')]]" size="sm" />
          <input v-model="note" class="input soft note" :placeholder="t('roast.notePlaceholder')"
            @keydown.enter="launch">
          <button v-if="busy" class="btn md" @click="stop">{{ t("common.stop") }}</button>
          <button v-else class="btn dark md" :disabled="!project.runtime.has_script" @click="launch">
            {{ runs.length ? t("roast.relaunch") : t("roast.launch") }}
          </button>
        </div>
        <span class="hint">
          {{ mode === "froid" ? t("roast.coldHint") : t("roast.contextHint") }}
          {{ t("roast.dismissedHint") }}
        </span>
        <span v-if="busy" class="mono running">{{ t("roast.running") }}<template v-if="busy.activity"> · {{ busy.activity }}</template></span>
        <span v-else-if="lastError" class="error">{{ lastError }}</span>
      </section>

      <div v-if="!run && !busy" class="dashed-box empty">
        <template v-if="!project.runtime.has_script">{{ t("roast.noScript") }}</template>
        <template v-else>{{ t("roast.empty") }}</template>
      </div>
      <div v-else-if="!run" class="skel"><div style="width: 40%" /><div style="width: 70%" /><div style="width: 55%" /></div>

      <template v-if="run && run.result">
        <!-- choix du roast -->
        <div class="runs">
          <span class="eyebrow">{{ t("roast.run.title") }}</span>
          <select class="input soft run-sel" :value="run.id" @change="selId = ($event.target as HTMLSelectElement).value">
            <option v-for="r in done" :key="r.id" :value="r.id">{{ runLabel(r) }}</option>
          </select>
          <span v-if="run.note" class="run-note">{{ t("chat.quoted", { q: run.note }) }}</span>
          <span class="spacer" />
          <ConfirmX :label="t('roast.run.deleteConfirm')" :title="t('roast.run.deleteTitle')" @confirm="remove(run)" />
        </div>

        <!-- verdict -->
        <section class="verdict">
          <div class="score" :style="{ color: scoreColor(run.result.verdict.score) }">
            {{ fmt(run.result.verdict.score) }}<span class="out">/10</span>
          </div>
          <div class="verdict-text">
            <div class="verdict-head">
              <span class="decision" :class="run.result.verdict.decision">{{ decisionLabel(run.result.verdict.decision) }}</span>
              <span v-if="prev" class="mono delta" :title="t('roast.verdict.vsPrevTitle', { when: when(prev.created_at) })">
                {{ t("roast.verdict.vsPrev", { delta: delta(run.result.verdict.score, prev.result!.verdict.score) }) }}
              </span>
            </div>
            <p class="headline">{{ run.result.verdict.headline }}</p>
            <button class="link-btn talk" @click="discuss(t('roast.verdict.quote', { score: score(run.result.verdict.score), decision: decisionLabel(run.result.verdict.decision), headline: run.result.verdict.headline }))">
              {{ t("roast.verdict.discuss") }}
            </button>
            <span class="meta mono">
              {{ t("roast.verdict.openFindings", open.length) }}
              · {{ t("roast.verdict.unclosedLoops", unclosed) }}
              · {{ t("roast.verdict.estimated", { t: mmss((time.words / 150) * 60) }) }}
            </span>
          </div>
        </section>

        <!-- critères -->
        <section class="criteria">
          <div v-for="c in criteria" :key="c.key" class="crit" :class="{ on: cat === c.key }">
            <div class="crit-head">
              <span class="crit-label">{{ c.label }}</span>
              <span class="mono crit-score" :style="{ color: scoreColor(c.score) }">{{ fmt(c.score) }}</span>
            </div>
            <div class="gauge"><div :style="{ width: `${c.score * 10}%`, background: scoreColor(c.score) }" /></div>
            <span class="crit-why">{{ c.why }}</span>
            <span v-if="c.delta" class="mono crit-delta">{{ c.delta }}</span>
            <div class="crit-actions">
              <button class="link-btn talk" @click="discuss(aboutCrit(c))">{{ t("common.discuss") }}</button>
              <button class="link-btn" :title="t('roast.crit.filterTitle', { label: c.label })" @click="filterCat(c.key)">
                {{ cat === c.key ? t("roast.crit.allFindings") : t("roast.crit.itsFindings") }}
              </button>
              <button v-if="c.block" class="link-btn mono" :title="t('roast.crit.passageTitle')" @click="goTo(c.block)">{{ at(c.block) }} ↗</button>
            </div>
          </div>
        </section>

        <!-- courbe et boucles -->
        <section class="card">
          <div class="card-head">
            <span class="eyebrow">{{ t("roast.curve.title") }}</span>
            <span class="hint">{{ t("roast.curve.hint") }}</span>
          </div>
          <InterestCurve :blocks="run.blocks" :result="run.result" @go="goTo" />
          <ul v-if="run.result.loops.length" class="loop-list">
            <li v-for="(l, i) in run.result.loops" :key="i" :class="{ open: !l.close }">
              <span class="q">{{ l.question }}</span>
              <span class="mono when">
                <button class="link-btn" @click="goTo(l.open)">{{ at(l.open) }}</button> →
                <button v-if="l.close" class="link-btn" @click="goTo(l.close)">{{ at(l.close) }}</button>
                <span v-else class="never">{{ t("roast.neverClosed") }}</span>
                <button class="link-btn talk" @click="discuss(aboutLoop(l))">{{ t("common.discuss") }}</button>
              </span>
            </li>
          </ul>
        </section>

        <div class="two">
          <!-- sections -->
          <section class="card">
            <div class="card-head">
              <span class="eyebrow">{{ t("roast.sections.title") }}</span>
              <span class="hint">{{ t("roast.sections.hint") }}</span>
            </div>
            <table class="secs">
              <tbody>
                <tr v-for="s in sections" :key="s.id" :class="{ on: sec === s.id }" @click="filterSec(s.id)">
                  <td class="mono t">{{ mmss(s.start) }}</td>
                  <td class="sec-name">
                    <span class="sec-label">{{ s.label }}</span>
                    <span class="sec-title">{{ s.title }}</span>
                    <span v-if="s.fiche" class="sec-verdict">{{ s.fiche.role }} — {{ s.fiche.verdict }}</span>
                    <span class="sec-actions">
                      <button class="link-btn talk" @click.stop="discuss(aboutSection(s))">{{ t("common.discuss") }}</button>
                      <button class="link-btn" @click.stop="goTo(s.id)">{{ t("roast.sections.script") }}</button>
                      <span v-if="s.open" class="mono sec-count">{{ t("roast.sections.count", s.open) }}</span>
                    </span>
                  </td>
                  <td class="mono dur" :class="{ long: s.fiche?.too_long }" :title="s.fiche?.too_long ? t('roast.sections.tooLong') : t('roast.sections.estDuration')">
                    {{ mmss(s.dur) }}
                  </td>
                  <td class="payoff" :title="s.fiche ? (s.fiche.payoff ? t('roast.sections.hasPayoff') : t('roast.sections.noPayoff')) : ''">
                    {{ s.fiche ? (s.fiche.payoff ? "✓" : "✗") : "" }}
                  </td>
                  <td class="mono sc" :style="{ color: s.fiche ? scoreColor(s.fiche.score) : undefined }">{{ s.fiche ? fmt(s.fiche.score) : "—" }}</td>
                </tr>
              </tbody>
            </table>
          </section>

          <!-- promesses -->
          <section class="card">
            <span class="eyebrow">{{ t("roast.promises.title") }}</span>
            <div v-if="!run.result.promises.length" class="hint">{{ t("roast.promises.none") }}</div>
            <div v-for="(p, i) in run.result.promises" :key="i" class="promise">
              <div class="promise-head">
                <span class="tag">{{ sourceLabel(p.source) }}</span>
                <span class="promise-t">{{ p.promise }}</span>
              </div>
              <span class="promise-note">
                <button v-if="p.block" class="link-btn mono" @click="goTo(p.block)">{{ t("roast.promises.keptAt", { t: at(p.block) }) }}</button>
                <span v-else class="never mono">{{ t("roast.promises.notKept") }}</span>
                · {{ p.note }}
                <button class="link-btn talk" @click="discuss(aboutPromise(p))">{{ t("common.discuss") }}</button>
              </span>
            </div>
          </section>
        </div>

        <!-- remarques -->
        <section id="roast-findings" class="findings">
          <div class="find-bar">
            <span class="eyebrow">{{ t("roast.findings.title") }}</span>
            <Seg v-model="grouping" :options="[['section', t('roast.findings.bySection')], ['liste', t('roast.findings.list')]]" size="sm" />
            <Seg v-model="sev" :options="sevOptions" size="sm" />
            <button v-if="cat" class="tag cat-filter" @click="cat = null">{{ data?.categories[cat] ?? cat }} ×</button>
            <button v-if="sec" class="tag cat-filter" @click="sec = null">{{ secName(sec) }} ×</button>
            <span class="spacer" />
            <label class="closed"><input v-model="showClosed" type="checkbox"> {{ t("roast.findings.showClosed") }}</label>
          </div>
          <div v-if="!shown.length" class="dashed-box">{{ t("roast.findings.nothing") }}</div>
          <template v-for="g in groups" :key="g.id">
            <div v-if="g.name" class="group-head">
              <span v-if="g.start != null" class="mono t">{{ mmss(g.start) }}</span>
              <span class="group-name">{{ g.name }}</span>
              <span class="mono group-n">{{ g.items.length }}</span>
            </div>
            <article v-for="f in g.items" :key="f.id" class="finding" :class="[f.severity, { closed: markOf(f) }]">
              <div class="f-head">
                <span class="sev" :class="f.severity">{{ severityLabel(f.severity) }}</span>
                <span class="tag">{{ data?.categories[f.category] ?? f.category }}</span>
                <button v-if="f.block" class="link-btn mono" @click="goTo(f.block)">{{ at(f.block) }}</button>
                <span v-if="drift(f)" class="drift mono">{{ drift(f) }}</span>
                <span v-if="markOf(f)" class="mono state">{{ markOf(f) === "done" ? t("roast.findings.stateDone") : t("roast.findings.stateIgnored") }}</span>
              </div>
              <blockquote v-if="f.quote || f.block">{{ f.quote || plain(textOf[f.block] ?? "") }}</blockquote>
              <p class="problem">{{ f.problem }}</p>
              <p class="fix"><span class="k">{{ t("roast.findings.fix") }}</span>{{ f.fix }}</p>
              <div class="f-actions">
                <button class="btn sm" @click="discuss(aboutFinding(f))">{{ t("common.discuss") }}</button>
                <button class="btn sm" :disabled="!f.block" @click="goTo(f.block)">{{ t("roast.findings.seeInScript") }}</button>
                <button class="btn sm" :title="t('roast.findings.rewriteTitle')" @click="ask(f)">{{ t("roast.findings.rewrite") }}</button>
                <span class="spacer" />
                <button class="btn sm" :class="{ dark: markOf(f) === 'done' }" @click="mark(f, 'done')">{{ t("roast.findings.markDone") }}</button>
                <button class="btn sm" :class="{ dark: markOf(f) === 'ignored' }" :title="t('roast.findings.dismissTitle')"
                  @click="mark(f, 'ignored')">{{ t("common.dismiss") }}</button>
              </div>
            </article>
          </template>
        </section>
      </template>
    </div>
    <aside v-if="run && run.result" class="side">
      <RoastAssistant :key="run.id" :roast="run.id" :quote="quote" @clear-quote="quote = null" />
    </aside>
  </div>
</template>

<style scoped>
.page { display: flex; gap: 20px; align-items: flex-start; padding: 24px 32px 48px; }
.wrap { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 22px; max-width: 1180px; }
.side { position: sticky; top: 16px; display: flex; width: 340px; flex-shrink: 0; }
.talk { font-size: 12px; color: var(--ink-3); }
.hint { font-size: 12.5px; color: var(--faint); }
.error { font-size: 13px; color: var(--red-ink); }
.spacer { flex: 1; }
.tag { font-family: var(--mono); font-size: 10.5px; padding: 2px 6px; border-radius: 3px; background: var(--line-soft); color: var(--muted); border: none; }
.never { color: var(--red-ink); }

.launch { display: flex; flex-direction: column; gap: 8px; max-width: 900px; }
.launch-row { display: flex; gap: 8px; align-items: center; }
.note { flex: 1; height: 34px; font-size: 13.5px; }
.running { font-size: 12px; color: var(--red-ink); }
.empty { padding: 32px; max-width: 640px; line-height: 1.55; }

.skel { display: flex; flex-direction: column; gap: 10px; padding: 18px; border: 1px solid var(--line); border-radius: 4px; max-width: 640px; }
.skel > div { height: 12px; background: var(--line-soft); border-radius: 2px; }

.runs { display: flex; align-items: center; gap: 10px; }
.run-sel { height: 32px; padding: 0 8px; font-size: 13px; max-width: 360px; }
.run-note { font-size: 12.5px; color: var(--muted); font-style: italic; }

.verdict { display: flex; gap: 28px; align-items: center; padding: 20px 24px; background: var(--bg-soft); border-radius: 6px; }
.score { font-size: 64px; font-weight: 600; letter-spacing: -0.03em; line-height: 1; }
.score .out { font-size: 20px; color: var(--faint); font-weight: 500; margin-left: 2px; }
.verdict-text { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.verdict-head { display: flex; align-items: center; gap: 12px; }
.decision { font-family: var(--mono); font-size: 12px; padding: 3px 9px; border-radius: 3px; color: #fff; text-transform: uppercase; letter-spacing: .05em; }
.decision.tourne { background: #2BA471; }
.decision.retouche { background: #E0912F; }
.decision.reecris { background: var(--red); }
.delta { font-size: 12px; color: var(--muted); }
.headline { margin: 0; font-size: 17px; font-weight: 500; line-height: 1.45; text-wrap: pretty; }
.verdict-text .talk { align-self: flex-start; }
.meta { font-size: 11.5px; color: var(--faint); }

.criteria { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 10px; }
.crit {
  position: relative; display: flex; flex-direction: column; gap: 6px; padding: 12px 14px;
  border: 1px solid var(--line); border-radius: 5px; background: #fff;
}
.crit.on { border-color: var(--ink); }
.crit-actions { display: flex; gap: 12px; align-items: baseline; margin-top: auto; padding-top: 2px; }
.crit-actions .link-btn { font-size: 12px; }
.crit-head { display: flex; justify-content: space-between; align-items: baseline; }
.crit-label { font-size: 13px; font-weight: 600; }
.crit-score { font-size: 15px; font-weight: 600; }
.gauge { height: 4px; background: var(--line-soft); border-radius: 2px; overflow: hidden; }
.gauge > div { height: 100%; }
.crit-why { font-size: 12.5px; line-height: 1.45; color: var(--muted); text-wrap: pretty; }
.crit-delta { position: absolute; top: 13px; right: 46px; font-size: 10.5px; color: var(--faint); }

.card { display: flex; flex-direction: column; gap: 10px; padding: 16px 18px; border: 1px solid var(--line); border-radius: 6px; background: #fff; min-width: 0; }
.card-head { display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; }
.loop-list { list-style: none; margin: 6px 0 0; padding: 0; display: flex; flex-direction: column; }
.loop-list li { display: flex; justify-content: space-between; gap: 16px; padding: 6px 0; border-top: 1px solid var(--line-soft); font-size: 13px; }
.loop-list li.open .q { color: var(--red-ink); }
.loop-list .when { font-size: 11.5px; white-space: nowrap; color: var(--faint); }
.loop-list .link-btn { font-size: 11.5px; }

.two { display: grid; grid-template-columns: 3fr 2fr; gap: 16px; align-items: start; }
.secs { width: 100%; border-collapse: collapse; }
.secs tr { cursor: pointer; }
.secs tr:hover, .secs tr.on { background: var(--bg-soft); }
.secs tr.on .sec-title { text-decoration: underline; }
.secs td { padding: 8px 6px; border-top: 1px solid var(--line-soft); vertical-align: top; }
.secs .t { font-size: 11px; color: var(--faint); width: 44px; }
.sec-name { display: flex; flex-direction: column; gap: 2px; }
.sec-label { font-family: var(--mono); font-size: 10.5px; color: var(--faint); }
.sec-title { font-size: 13.5px; font-weight: 500; }
.sec-verdict { font-size: 12.5px; color: var(--muted); line-height: 1.45; }
.sec-actions { display: flex; gap: 12px; align-items: baseline; padding-top: 2px; }
.sec-actions .link-btn { font-size: 12px; }
.sec-count { font-size: 11px; color: var(--faint); }
.secs .dur { font-size: 12px; width: 48px; }
.secs .dur.long { color: var(--red-ink); font-weight: 600; }
.secs .payoff { width: 20px; text-align: center; color: var(--muted); }
.secs .sc { width: 32px; text-align: right; font-weight: 600; }

.promise { display: flex; flex-direction: column; gap: 4px; padding: 8px 0; border-top: 1px solid var(--line-soft); }
.promise-head { display: flex; gap: 8px; align-items: baseline; }
.promise-t { font-size: 13.5px; font-weight: 500; }
.promise-note { font-size: 12.5px; color: var(--muted); line-height: 1.45; }
.promise-note .link-btn, .promise-note .never { font-size: 11.5px; }
.promise-note .talk, .loop-list .talk { margin-left: 8px; font-family: var(--sans, inherit); }

.findings { display: flex; flex-direction: column; gap: 10px; scroll-margin-top: 16px; }
.find-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.cat-filter { cursor: pointer; }
.group-head { display: flex; align-items: baseline; gap: 10px; padding: 10px 2px 0; border-bottom: 1px solid var(--line); }
.group-head .t { font-size: 11px; color: var(--faint); }
.group-name { font-size: 14px; font-weight: 600; }
.group-n { font-size: 11px; color: var(--faint); }
.closed { display: flex; gap: 6px; align-items: center; font-size: 12.5px; color: var(--muted); }
.finding {
  display: flex; flex-direction: column; gap: 8px; padding: 14px 16px; border: 1px solid var(--line);
  border-left: 3px solid var(--line-strong); border-radius: 5px; background: #fff;
}
.finding.bloquant { border-left-color: var(--red); }
.finding.important { border-left-color: #E0912F; }
.finding.closed { opacity: .55; }
.f-head { display: flex; align-items: center; gap: 8px; }
.f-head .link-btn { font-size: 11.5px; }
.sev { font-family: var(--mono); font-size: 10.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
.sev.bloquant { color: var(--red-ink); font-weight: 600; }
.sev.important { color: #B86F14; font-weight: 600; }
.drift { font-size: 10.5px; color: #B86F14; }
.state { font-size: 10.5px; color: var(--faint); }
blockquote { margin: 0; padding: 4px 12px; border-left: 2px solid var(--line-strong); font-size: 13.5px; color: var(--ink-3); line-height: 1.5; }
.problem { margin: 0; font-size: 14px; font-weight: 500; line-height: 1.5; text-wrap: pretty; }
.fix { margin: 0; font-size: 13.5px; color: var(--ink-3); line-height: 1.55; white-space: pre-wrap; text-wrap: pretty; }
.fix .k { font-family: var(--mono); font-size: 10.5px; color: var(--faint); text-transform: uppercase; letter-spacing: .05em; margin-right: 8px; }
.f-actions { display: flex; gap: 6px; align-items: center; }

@media (max-width: 1400px) { .two { grid-template-columns: 1fr; } }
@media (max-width: 1100px) { .page { flex-direction: column; } .side { position: static; width: 100%; } }
</style>
