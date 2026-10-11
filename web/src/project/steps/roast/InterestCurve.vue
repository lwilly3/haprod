<script setup lang="ts">
/**
 * La courbe d'intérêt prédite par le roast, sur la durée estimée du script, avec ses sections ;
 * dessous, les boucles ouvertes : une barre de l'ouverture à la réponse (rouge : jamais refermée).
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { mmss } from "../../../lib/format";
import type { RoastResult } from "../../types";
import { wordCount } from "../script/markdown";
import { plain, sectionsOf, timing } from "../script/plans";
import { scoreColor } from "./roast";

const props = defineProps<{ blocks: { id: string; md: string }[]; result: RoastResult }>();
const emit = defineEmits<{ go: [block: string] }>();

const { t } = useI18n();

// sous ce seuil, le spectateur décroche
const LOW = 5;

const time = computed(() => timing(props.blocks));
const total = computed(() => Math.max(1, (time.value.words / 150) * 60));
const text = computed(() => Object.fromEntries(props.blocks.map((b) => [b.id, b.md])));

/** La position (0–100 %) du milieu d'un bloc, ou de son début. */
function at(id: string, middle = true): number {
  const start = time.value.times[id] ?? 0;
  const half = middle ? (wordCount(text.value[id] ?? "") / 150) * 30 : 0;
  return Math.min(100, ((start + half) / total.value) * 100);
}

const points = computed(() => props.result.interest.map((i) => ({
  ...i, x: at(i.block), y: 100 - i.score * 10,
  tip: `${mmss(time.value.times[i.block])} · ${i.score}/10 · ${plain(text.value[i.block] ?? "").slice(0, 90)}…`,
})));
const line = computed(() => points.value.map((p, k) => `${k ? "L" : "M"}${p.x * 10},${p.y}`).join(" "));
const area = computed(() => points.value.length ? `${line.value} L${points.value.at(-1)!.x * 10},100 L${points.value[0].x * 10},100 Z` : "");

const sections = computed(() => sectionsOf(props.blocks).map((s) => ({ ...s, x: at(s.id, false) })));

/** Les boucles, rangées sur des lignes sans chevauchement. */
const loops = computed(() => {
  const ends: number[] = [];
  return [...props.result.loops]
    .map((l) => ({ ...l, from: at(l.open), to: l.close ? at(l.close) : 100 }))
    .sort((a, b) => a.from - b.from)
    .map((l) => {
      let lane = ends.findIndex((e) => e <= l.from);
      if (lane < 0) lane = ends.push(0) - 1;
      ends[lane] = l.to + 0.5;
      return { ...l, lane };
    });
});
const lanes = computed(() => Math.max(1, ...loops.value.map((l) => l.lane + 1)));
</script>

<template>
  <div class="curve-box">
    <div class="curve">
      <svg viewBox="0 0 1000 100" preserveAspectRatio="none">
        <path :d="area" class="area" />
        <line x1="0" x2="1000" :y1="100 - LOW * 10" :y2="100 - LOW * 10" class="low" />
        <line v-for="s in sections" :key="s.id" :x1="s.x * 10" :x2="s.x * 10" y1="0" y2="100" class="sec" />
        <path :d="line" class="line" />
      </svg>
      <span v-for="s in sections" :key="s.id" class="sec-label mono" :style="{ left: `${s.x}%` }" :title="s.title">{{ s.label }}</span>
      <button v-for="p in points" :key="p.block" class="pt" :class="{ low: p.score < LOW }"
        :style="{ left: `${p.x}%`, top: `${p.y}%`, background: p.score < LOW ? scoreColor(p.score) : undefined }"
        :title="p.tip" @click="emit('go', p.block)" />
    </div>
    <div class="axis mono"><span>00:00</span><span>{{ mmss(total) }}</span></div>

    <template v-if="loops.length">
      <span class="eyebrow">{{ t("roast.curve.openLoops") }}</span>
      <div class="loops" :style="{ height: `${lanes * 14}px` }">
        <button v-for="(l, i) in loops" :key="i" class="loop" :class="{ open: !l.close }"
          :style="{ left: `${l.from}%`, width: `${Math.max(0.8, l.to - l.from)}%`, top: `${l.lane * 14}px` }"
          :title="`${l.question}\n${mmss(time.times[l.open])} → ${l.close ? mmss(time.times[l.close]) : t('roast.neverClosed')}`"
          @click="emit('go', l.open)" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.curve-box { display: flex; flex-direction: column; gap: 6px; }
.curve { position: relative; height: 150px; margin-top: 16px; }
svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
.area { fill: var(--bg-soft); }
.line { fill: none; stroke: var(--ink); stroke-width: 1.5; vector-effect: non-scaling-stroke; stroke-linejoin: round; }
.low { stroke: var(--red); stroke-width: 1; stroke-dasharray: 3 4; vector-effect: non-scaling-stroke; opacity: .5; }
.sec { stroke: var(--line-strong); stroke-width: 1; vector-effect: non-scaling-stroke; }
.sec-label {
  position: absolute; top: -16px; transform: translateX(3px); font-size: 10px; color: var(--faint);
  white-space: nowrap; max-width: 90px; overflow: hidden; text-overflow: ellipsis;
}
.pt {
  position: absolute; width: 7px; height: 7px; margin: -3.5px 0 0 -3.5px; padding: 0; border: none;
  border-radius: 50%; background: var(--ink); cursor: pointer;
}
.pt.low { width: 10px; height: 10px; margin: -5px 0 0 -5px; }
.pt:hover { outline: 3px solid var(--line-strong); }
.axis { display: flex; justify-content: space-between; font-size: 10px; color: var(--faint); }

.eyebrow { margin-top: 10px; }
.loops { position: relative; }
.loop {
  position: absolute; height: 6px; padding: 0; border: none; border-radius: 3px;
  background: var(--muted-2); cursor: pointer; opacity: .75;
}
.loop.open { background: repeating-linear-gradient(90deg, var(--red) 0 6px, transparent 6px 9px); opacity: 1; }
.loop:hover { opacity: 1; outline: 2px solid var(--line-strong); }
</style>
