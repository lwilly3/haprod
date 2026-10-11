<script setup lang="ts">
/**
 * Une variante dans le récap du haut : son image retenue, son nom, son titre associé, et de quoi la retenir
 * pour l'A/B test (elle prend alors une lettre). Cliquer dessus l'ouvre dans l'éditeur.
 */
import { useI18n } from "vue-i18n";
import type { Thumb } from "../../types";

defineProps<{
  thumb: Thumb; src: string | null; editing: boolean; busy: boolean; letter: string | null; titleChoices: string[];
}>();
defineEmits<{ select: []; title: [value: string]; pick: [] }>();
const { t } = useI18n();
</script>

<template>
  <div class="variant">
    <div class="thumb" :class="{ on: editing, hatch: !src }" @click="$emit('select')">
      <img v-if="src" :src="src" alt="">
      <span v-else-if="!busy" class="todo">{{ t("thumbnail.tile.todo") }}</span>
      <span class="badges">
        <span v-if="letter" class="badge ab">{{ letter }}</span>
        <span class="badge">{{ thumb.v }}</span>
        <span v-if="busy" class="badge dark">{{ t("thumbnail.generating") }}</span>
      </span>
      <span v-if="editing" class="editing">{{ t("thumbnail.tile.editing") }}</span>
    </div>
    <div class="foot">
      <select class="input soft" :value="thumb.title ?? ''" :title="thumb.title" @change="$emit('title', ($event.target as HTMLSelectElement).value)">
        <option v-if="!thumb.title" value="" disabled>{{ titleChoices.length ? t("thumbnail.tile.pickTitle") : t("thumbnail.tile.noTitle") }}</option>
        <option v-if="thumb.title && !titleChoices.includes(thumb.title)" :value="thumb.title">{{ t("thumbnail.tile.notKept", { title: thumb.title }) }}</option>
        <option v-for="title in titleChoices" :key="title" :value="title">{{ title }}</option>
      </select>
      <button class="btn h34" @click="$emit('pick')">
        {{ thumb.pick ? t("common.remove") : t("thumbnail.tile.keep") }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.variant { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.thumb { position: relative; aspect-ratio: 16 / 9; border-radius: 4px; cursor: pointer; outline-offset: 3px; overflow: hidden; }
.thumb.on { outline: 2px solid var(--ink); }
.thumb img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.todo { position: absolute; inset: 0; display: grid; place-items: center; font-size: 13px; color: var(--muted); }
/* en bas à gauche : le texte des vignettes est le plus souvent en haut */
.badges { position: absolute; left: 8px; bottom: 8px; display: flex; gap: 4px; }
.badge {
  font-family: var(--mono); font-size: 11px; padding: 3px 7px; border-radius: 3px;
  background: rgba(255, 255, 255, .92); color: var(--muted);
}
.badge.ab { background: var(--red); color: #fff; font-weight: 700; }
.badge.dark { background: var(--ink); color: #fff; }
.editing {
  position: absolute; right: 8px; bottom: 8px; font-size: 11px; padding: 3px 7px; border-radius: 3px;
  background: var(--ink); color: #fff;
}
.foot { display: flex; gap: 6px; }
.foot .input { flex: 1; height: 34px; padding: 0 6px; font-size: 13px; border-radius: 3px; min-width: 0; text-overflow: ellipsis; }
.h34 { height: 34px; padding: 0 12px; font-size: 13px; flex-shrink: 0; }
</style>
