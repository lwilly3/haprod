<script setup lang="ts">
/**
 * Le choix d'une transition (ou d'une coupe franche) : un bouton qui dit la transition en place, et la
 * galerie dans une fenêtre, avec la durée. Échap ferme.
 */
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { approximate, fxLabel, loadTransitions, type Fx } from "../lib/transitions";
import TransitionGallery from "./TransitionGallery.vue";

const props = defineProps<{ title: string; disabled?: boolean; hint?: string }>();
const model = defineModel<Fx | null | undefined>({ required: true });
const { t } = useI18n();

const open = ref(false);
const range = ref<[number, number]>([0.2, 2]);
const fallback = ref(0.6);
onMounted(async () => {
  const c = await loadTransitions();
  range.value = c.dur;
  fallback.value = c.default_dur;
});

function pick(fx: string) {
  model.value = { fx, dur: model.value?.dur ?? fallback.value };
}
function setDur(e: Event) {
  if (model.value) model.value = { ...model.value, dur: Number((e.target as HTMLInputElement).value) };
}
function onKey(e: KeyboardEvent) {
  if (open.value && e.key === "Escape") { open.value = false; e.stopPropagation(); }
}
onMounted(() => document.addEventListener("keydown", onKey, true));
onBeforeUnmount(() => document.removeEventListener("keydown", onKey, true));
</script>

<template>
  <div class="picker">
    <span class="label">{{ title }}</span>
    <button type="button" class="btn sm current" :class="{ none: !model }" :disabled="disabled" @click="open = true">{{ fxLabel(model) }}</button>
    <Teleport to="body">
      <template v-if="open">
        <div class="backdrop" @click="open = false" />
        <div class="box">
          <div class="head">
            <span class="h">{{ title }}</span>
            <span class="spacer" />
            <button type="button" class="btn sm" :class="{ dark: !model }" @click="model = null">{{ t("transitions.cut") }}</button>
            <label v-if="model" class="dur">{{ t("transitions.duration") }} <b class="mono">{{ model.dur.toFixed(1) }} s</b>
              <input type="range" :min="range[0]" :max="range[1]" step="0.1" :value="model.dur" @input="setDur">
            </label>
            <button type="button" class="btn sm" @click="open = false">{{ t("common.close") }}</button>
          </div>
          <p v-if="props.hint" class="hint">{{ props.hint }}</p>
          <p v-if="model && approximate(model.fx)" class="hint">{{ t("transitions.approx") }}</p>
          <div class="scroll">
            <TransitionGallery :selected="model?.fx ?? null" pickable small @pick="pick" />
          </div>
        </div>
      </template>
    </Teleport>
  </div>
</template>

<style scoped>
.picker { display: flex; flex-direction: column; gap: 5px; }
.label { font-size: 12.5px; color: var(--muted); }
.current { align-self: flex-start; }
.current.none { color: var(--muted); }
.backdrop { position: fixed; inset: 0; background: rgba(20, 20, 22, .45); z-index: 90; }
.box {
  position: fixed; z-index: 91; left: 50%; top: 50%; transform: translate(-50%, -50%);
  width: min(920px, 92vw); max-height: 84vh; display: flex; flex-direction: column; gap: 10px;
  padding: 18px 20px; background: #fff; border-radius: 6px; box-shadow: 0 12px 40px rgba(0, 0, 0, .25);
  font-family: var(--sans); color: var(--ink);
}
.head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.h { font-size: 15px; font-weight: 600; }
.dur { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--muted); }
.dur input { width: 140px; }
.hint { margin: 0; font-size: 12.5px; color: var(--muted); }
.scroll { overflow: auto; min-height: 0; padding: 4px; }
</style>
