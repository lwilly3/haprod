<script setup lang="ts">
/**
 * L'onglet Daryl du dérush : il lit tous les rushes et propose un dérush complet (silences, bégaiements,
 * prises ratées, faux départs, indications de tournage). Rien n'est coupé avant « Appliquer » : on
 * décoche ce qu'on garde, on clique une coupe pour l'écouter. Les coupes appliquées passent par la
 * timeline (Ctrl + Z les annule).
 */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../../../lib/api";
import { mmss } from "../../../lib/format";
import { toast } from "../../../lib/toast";
import { act, store } from "../../store";
import type { AutoCut, AutoDerush, AutoWarning, DerushClip } from "../../types";

const props = defineProps<{ clips: DerushClip[]; names: Record<string, string>; ready: boolean }>();
const emit = defineEmits<{ apply: [AutoCut[]]; seek: [string, number] }>();
const { t, locale } = useI18n();

const project = computed(() => store.project!);
const job = computed(() => project.value.runtime.jobs.autoderush ?? null);
const busy = computed(() => !!job.value && !job.value.finished);
const auto = ref<AutoDerush | null>(null);
const note = ref("");
const off = ref(new Set<string>());
const open = ref<Record<string, boolean>>({ takes: true });

async function load() {
  try {
    auto.value = await api<AutoDerush | null>(`/api/projects/${project.value.id}/derush/auto`);
    note.value = auto.value?.note ?? note.value;
  } catch (e) {
    toast((e as Error).message, true);
  }
}
// relu à chaque changement d'état du job (le projet est relu tant qu'il tourne)
watch(() => `${job.value?.id}:${job.value?.status}`, load, { immediate: true });
// un nouveau résultat : tout est coché
watch(() => auto.value?.result, () => { off.value = new Set(); });

const result = computed(() => auto.value?.result ?? null);

/** Une coupe encore présente dans la timeline (au moins 50 ms de son rush y sont lus). */
function present(it: AutoCut) {
  return props.clips.some((c) => c.rush === it.rush && Math.min(c.out, it.end) - Math.max(c.in, it.start) >= 0.05);
}
const items = computed(() => (result.value?.items ?? []).map((it) => ({ ...it, present: present(it) })));
const groups = computed(() => {
  const g = { silence: [] as typeof items.value, stutter: [] as typeof items.value, takes: [] as typeof items.value };
  for (const it of items.value) (it.kind === "silence" ? g.silence : it.kind === "stutter" ? g.stutter : g.takes).push(it);
  return g;
});
const chosen = computed(() => items.value.filter((it) => it.present && !off.value.has(it.id)));
const secs = (n: number) => n.toLocaleString(locale.value, { minimumFractionDigits: 1, maximumFractionDigits: 1 });

function toggle(ids: string[], on: boolean) {
  const next = new Set(off.value);
  for (const id of ids) on ? next.delete(id) : next.add(id);
  off.value = next;
}
function groupState(list: typeof items.value) {
  const live = list.filter((it) => it.present);
  const n = live.filter((it) => !off.value.has(it.id)).length;
  return { live, n, all: !!live.length && n === live.length, some: n > 0 && n < live.length };
}

async function run() {
  await act("/derush/auto", { note: note.value });
}
async function stop() {
  await act("/jobs/autoderush/stop");
}
function apply() {
  const list = chosen.value;
  if (!list.length) return;
  emit("apply", list);
  toast(t("derush.auto.appliedToast", { n: list.length }));
}
function seekWarning(w: AutoWarning) {
  if (w.rush) emit("seek", w.rush, w.t);
}
const kindLabel = (k: string) => t(`derush.auto.kinds.${k}`);
</script>

<template>
  <div class="auto">
    <!-- en cours -->
    <div v-if="busy" class="state">
      <span class="state-label">{{ t("derush.auto.working", { a: job?.activity || t("derush.auto.starting") }) }}</span>
      <div class="progress bar"><div :style="{ width: `${Math.round((job?.progress ?? 0) * 100)}%` }" /></div>
      <button class="btn sm" @click="stop">{{ t("derush.auto.stop") }}</button>
    </div>

    <!-- pas encore lancé, ou échoué -->
    <div v-else-if="!result" class="state">
      <span class="state-text">{{ t("derush.auto.intro") }}</span>
      <span v-if="auto?.status === 'error'" class="error">{{ t("derush.auto.failed", { e: auto.error }) }}</span>
      <textarea v-model="note" rows="2" :placeholder="t('derush.auto.notePlaceholder')" />
      <button class="btn dark gen" :disabled="!ready" @click="run">{{ t("derush.auto.run") }}</button>
      <span v-if="!ready" class="hint">{{ t("derush.auto.needsTranscript") }}</span>
    </div>

    <!-- les propositions -->
    <template v-else>
      <div class="scroll">
        <p v-if="result.message" class="message">{{ result.message }}</p>
        <p class="stats">
          {{ t("derush.auto.summary", { removed: mmss(result.stats.removed), total: mmss(result.stats.total) }) }}
          <template v-if="result.stats.repaired"> · {{ t("derush.auto.repaired", { n: result.stats.repaired }) }}</template>
          <template v-if="result.stats.silent.length"><br>{{ t("derush.auto.silent", { names: result.stats.silent.join(", ") }) }}</template>
        </p>

        <section v-if="result.warnings.length" class="warnings">
          <h4>{{ t("derush.auto.warnings.title", { n: result.warnings.length }) }}</h4>
          <button v-for="(w, i) in result.warnings" :key="i" class="warn" :disabled="!w.rush" @click="seekWarning(w)">
            <span class="mono">{{ w.rush ? `${names[w.rush] ?? ""} ${mmss(w.t)}` : "" }}</span>
            {{ t(`derush.auto.warnings.${w.kind}`, { text: w.text }) }}
          </button>
        </section>

        <section v-for="key in (['takes', 'stutter', 'silence'] as const)" :key="key" class="group">
          <template v-if="groups[key].length">
            <div class="group-head">
              <input type="checkbox" :checked="groupState(groups[key]).all" :indeterminate="groupState(groups[key]).some"
                :disabled="!groupState(groups[key]).live.length"
                @change="toggle(groupState(groups[key]).live.map((it) => it.id), ($event.target as HTMLInputElement).checked)">
              <button class="group-title" @click="open[key] = !open[key]">
                {{ open[key] ? "▾" : "▸" }} {{ t(`derush.auto.groups.${key}`) }}
                <span class="count">{{ t("derush.auto.count", { n: groupState(groups[key]).n, d: secs(groupState(groups[key]).live
                  .filter((it) => !off.has(it.id)).reduce((a, it) => a + it.end - it.start, 0)) }) }}</span>
              </button>
            </div>
            <div v-if="open[key]" class="list">
              <div v-for="it in groups[key]" :key="it.id" class="item" :class="{ gone: !it.present }">
                <input type="checkbox" :checked="it.present && !off.has(it.id)" :disabled="!it.present"
                  @change="toggle([it.id], ($event.target as HTMLInputElement).checked)">
                <button class="item-body" :title="t('derush.jumpTo')" @click="emit('seek', it.rush, it.start)">
                  <span class="meta mono">
                    {{ names[it.rush] }} {{ mmss(it.start) }} · {{ secs(it.end - it.start) }} s
                    <template v-if="key === 'takes'"> · {{ kindLabel(it.kind) }}</template>
                    <template v-if="!it.present"> · {{ t("derush.auto.gone") }}</template>
                  </span>
                  <span v-if="key !== 'silence'" class="cut-text">{{ it.text }}</span>
                  <span v-if="it.reason" class="reason">{{ it.reason }}</span>
                </button>
              </div>
            </div>
          </template>
        </section>
      </div>

      <div class="foot">
        <textarea v-model="note" rows="1" :placeholder="t('derush.auto.notePlaceholder')" />
        <button class="btn sm" :disabled="!ready" @click="run">{{ t("derush.auto.rerun") }}</button>
        <button class="btn sm red" :disabled="!chosen.length" @click="apply">{{ t("derush.auto.apply", chosen.length) }}</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.auto { position: absolute; inset: 0; display: flex; flex-direction: column; }
.state {
  position: absolute; inset: 16px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px;
  padding: 20px; border: 1px dashed var(--dash); border-radius: 4px; text-align: center;
}
.state-text { font-size: 14px; color: var(--muted); max-width: 460px; line-height: 1.5; text-wrap: pretty; }
.state-label { font-family: var(--mono); font-size: 12.5px; color: var(--muted); }
.state textarea { width: min(460px, 100%); }
.progress.bar { width: 260px; }
.btn.gen { height: 38px; padding: 0 18px; font-size: 13.5px; }
.hint { font-size: 12px; color: var(--faint); }
.error { font-size: 13px; color: var(--red-ink); max-width: 460px; }
textarea { font: inherit; font-size: 13px; padding: 6px 8px; border: 1px solid var(--line-input); border-radius: 4px; resize: vertical; }

.scroll { flex: 1; overflow-y: auto; padding: 12px 14px; display: flex; flex-direction: column; gap: 12px; }
.message { margin: 0; font-size: 13.5px; line-height: 1.5; color: var(--ink); white-space: pre-line; }
.stats { margin: 0; font-size: 12.5px; color: var(--muted); line-height: 1.5; }
.mono { font-family: var(--mono); }

.warnings { display: flex; flex-direction: column; gap: 4px; padding: 8px 10px; background: var(--bg-soft); border-radius: 4px; }
.warnings h4 { margin: 0 0 2px; font-size: 12.5px; font-weight: 600; }
.warn { text-align: left; border: none; background: transparent; padding: 2px 0; font-size: 12.5px; color: var(--ink-3); cursor: pointer; line-height: 1.4; }
.warn:hover:not(:disabled) { color: var(--ink); }
.warn .mono { font-size: 11.5px; color: var(--faint); margin-right: 6px; }

.group { display: flex; flex-direction: column; gap: 4px; }
.group-head { display: flex; align-items: center; gap: 8px; }
.group-title { border: none; background: transparent; padding: 0; font-size: 13px; font-weight: 600; cursor: pointer; color: var(--ink); }
.count { font-weight: 400; color: var(--muted); margin-left: 6px; font-size: 12.5px; }
.list { display: flex; flex-direction: column; gap: 2px; padding-left: 22px; }
.item { display: flex; gap: 8px; align-items: flex-start; }
.item input { margin-top: 3px; }
.item-body {
  flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; text-align: left; border: none;
  background: transparent; padding: 3px 6px; border-radius: 3px; cursor: pointer;
}
.item-body:hover { background: var(--bg-soft); }
.item.gone { opacity: 0.5; }
.meta { font-size: 11.5px; color: var(--faint); }
.cut-text { font-size: 13px; color: var(--ink-3); text-decoration: line-through; text-decoration-color: var(--red); line-height: 1.4; }
.reason { font-size: 12px; color: var(--muted); line-height: 1.4; }

.foot { display: flex; gap: 8px; align-items: center; padding: 8px 10px; border-top: 1px solid var(--line); }
.foot textarea { flex: 1; min-width: 0; resize: none; }
.btn.sm { height: 28px; padding: 0 10px; font-size: 12.5px; white-space: nowrap; }
</style>
