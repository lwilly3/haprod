<script setup lang="ts">
/**
 * Les recherches d'images lancées depuis les beats, dans la file à côté du chat : elles tournent sans la popup.
 * Ouvrir une recherche rouvre la popup de son beat, sur les images trouvées.
 */
import { useI18n } from "vue-i18n";
import { tcd, type Beat, type ImageJob } from "./types";

defineProps<{ jobs: { beat: Beat; job: ImageJob }[] }>();
const emit = defineEmits<{ open: [string]; stop: [string]; dismiss: [string] }>();
const { t } = useI18n();

const active = (j: ImageJob) => j.status === "queued" || j.status === "running";
function state(j: ImageJob): string {
  if (j.status === "running") return j.activity || t("editing.imageSearch.running");
  if (j.status === "done") return t("editing.imageSearch.found", j.found);
  return t(`editing.tasks.${j.status}`);
}
</script>

<template>
  <div class="queue">
    <div v-for="{ beat, job } in jobs" :key="beat.id" class="row" :class="job.status" :title="job.error || job.query" @click="emit('open', beat.id)">
      <span class="st mono">{{ state(job) }}</span>
      <span class="title">{{ job.query }}</span>
      <span class="scope mono">{{ t("editing.imageSearch.scope", { tc: tcd(beat.at) }) }}</span>
      <button v-if="active(job)" class="x-btn" :title="t('common.stop')" @click.stop="emit('stop', beat.id)">■</button>
      <button v-else class="x-btn" :title="t('editing.imageSearch.dismiss')" @click.stop="emit('dismiss', beat.id)">×</button>
    </div>
  </div>
</template>

<style scoped>
.queue { max-height: 30%; overflow-y: auto; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; flex-shrink: 0; }
.row {
  display: grid; grid-template-columns: auto minmax(0, 1fr) auto; grid-template-areas: "st title x" "st scope x";
  align-items: center; column-gap: 8px; padding: 6px 10px; cursor: pointer; border-left: 2px solid transparent;
}
.row + .row { border-top: 1px solid var(--line-soft); }
.row:hover { background: var(--bg-soft); }
.row.done { border-left-color: #2A9D8F; }
.st { grid-area: st; font-size: 10.5px; color: var(--faint); max-width: 90px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.running .st { color: #7C5CE0; }
.done .st { color: #1F7A6F; }
.error .st { color: var(--red-ink); }
.title { grid-area: title; font-size: 12.5px; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.scope { grid-area: scope; font-size: 10.5px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.x-btn { grid-area: x; }
</style>
