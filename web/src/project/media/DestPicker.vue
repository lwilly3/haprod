<script setup lang="ts">
/** Où ranger ce qu'on récupère : les assets du projet (catégorie imposée), ou les assets communs (catégorie au choix). */
import { useI18n } from "vue-i18n";
import { CATEGORY_IDS, categoryLabel } from "./categories";
import CheckBox from "./CheckBox.vue";

defineProps<{ projectCategory: string }>();
const common = defineModel<boolean>("common", { required: true });
const category = defineModel<string>("category", { required: true });
const { t } = useI18n();
</script>

<template>
  <div class="dest">
    <CheckBox v-model="common">{{ t("sourcing.dest.library") }}</CheckBox>
    <select v-if="common" v-model="category" class="select">
      <option v-for="key in CATEGORY_IDS" :key="key" :value="key">{{ categoryLabel(key) }}</option>
    </select>
    <span v-else class="mono faint to">{{ t("sourcing.dest.project", { cat: categoryLabel(projectCategory) }) }}</span>
  </div>
</template>

<style scoped>
.dest { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.select { height: 30px; border: 1px solid var(--line-strong); border-radius: 4px; background: #fff; font-size: 13px; padding: 0 6px; cursor: pointer; }
.to { font-size: 12px; }
</style>
