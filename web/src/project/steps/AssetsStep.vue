<script setup lang="ts">
/** Assets : ce qu'il faut pour le montage — extraits YouTube, images trouvées par Claude, captures des sources du script. */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { usePref } from "../../lib/composables";
import { store } from "../store";
import DocTab from "./assets/DocTab.vue";
import ImagesTab from "./assets/ImagesTab.vue";
import YoutubeTab from "./assets/YoutubeTab.vue";

type Tab = "youtube" | "images" | "doc";
const tab = usePref<Tab>("assets.tab", "youtube");
const project = computed(() => store.project!);
const { t } = useI18n();

const tabs = computed<[Tab, string, number | null][]>(() => [
  ["youtube", t("sourcing.tabs.youtube"), project.value.assets.videos.length || null],
  ["images", t("sourcing.tabs.images"), null],
  ["doc", t("sourcing.tabs.doc"), project.value.research.length || null],
]);
</script>

<template>
  <div class="assets">
    <div class="tabs">
      <button v-for="[k, label, n] in tabs" :key="k" :class="{ on: k === tab }" @click="tab = k">
        {{ label }}<span v-if="n" class="n">{{ n }}</span>
      </button>
    </div>
    <YoutubeTab v-if="tab === 'youtube'" />
    <ImagesTab v-else-if="tab === 'images'" />
    <DocTab v-else />
  </div>
</template>

<style scoped>
.assets { padding: 20px 32px 40px; display: flex; flex-direction: column; gap: 22px; }
</style>
