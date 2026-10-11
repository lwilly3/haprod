<script setup lang="ts">
/**
 * La file des demandes faites à Daryl, dans l'ordre : chacune avec son état et sa portée (sélection ou image en
 * pause). Ouvrir une demande montre sa conversation, où on peut la reprendre, et va à sa portée dans la timeline.
 */
import { useI18n } from "vue-i18n";
import { tcd, type MontageTask, type Selection } from "./types";

defineProps<{ tasks: MontageTask[]; current: string | null; describe: (s: Selection) => string }>();
const emit = defineEmits<{ open: [MontageTask]; stop: [string]; close: [string] }>();

const { t } = useI18n();
const first = (task: MontageTask) => task.messages.find((m) => m.role === "user");
const active = (task: MontageTask) => task.status === "queued" || task.status === "running";
</script>

<template>
  <div class="queue">
    <div v-for="task in tasks" :key="task.id" class="row" :class="[task.status, { on: task.id === current }]" @click="emit('open', task)">
      <span class="st mono">{{ task.status === "running" && task.activity ? task.activity : t(`editing.tasks.${task.status}`) }}</span>
      <span class="title">{{ first(task)?.text }}</span>
      <span v-if="first(task)?.selection" class="scope mono">{{ describe(first(task)!.selection!) }}</span>
      <span v-else-if="first(task)?.frame != null" class="scope mono">{{ t("editing.chat.frameRef", { tc: tcd(first(task)!.frame!) }) }}</span>
      <button v-if="active(task)" class="x-btn" :title="t(task.status === 'queued' ? 'editing.tasks.unqueue' : 'common.stop')"
        @click.stop="emit('stop', task.id)">■</button>
      <button v-else class="x-btn" :title="t('editing.tasks.close')" @click.stop="emit('close', task.id)">×</button>
    </div>
  </div>
</template>

<style scoped>
.queue { max-height: 34%; overflow-y: auto; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; flex-shrink: 0; }
.row {
  display: grid; grid-template-columns: auto minmax(0, 1fr) auto; grid-template-areas: "st title x" "st scope x";
  align-items: center; column-gap: 8px; padding: 6px 10px; cursor: pointer; border-left: 2px solid transparent;
}
.row + .row { border-top: 1px solid var(--line-soft); }
.row:hover { background: var(--bg-soft); }
.row.on { background: var(--bg-soft); border-left-color: var(--red); }
.st { grid-area: st; font-size: 10.5px; color: var(--faint); max-width: 90px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.running .st { color: #7C5CE0; }
.error .st { color: var(--red-ink); }
.title { grid-area: title; font-size: 12.5px; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.scope { grid-area: scope; font-size: 10.5px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.x-btn { grid-area: x; }
</style>
