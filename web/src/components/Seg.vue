<script setup lang="ts" generic="T extends string">
/** Choix exclusif en ligne (segmented control) : options [valeur, libellé] ou simples libellés. */
const props = defineProps<{ options: readonly (T | readonly [T, string])[]; size?: "sm" | "md" }>();
const model = defineModel<T>({ required: true });
const items = () => props.options.map((o) => (Array.isArray(o) ? o : [o, o]) as [T, string]);
</script>

<template>
  <div class="seg" :class="size ?? 'md'">
    <button v-for="[v, label] in items()" :key="v" type="button" :class="{ on: v === model }" @click="model = v">
      {{ label }}
    </button>
  </div>
</template>

<style scoped>
.seg { display: inline-flex; flex-wrap: wrap; align-self: flex-start; border: 1px solid var(--line-strong); border-radius: 4px; overflow: hidden; }
.seg button { border: none; background: #fff; color: var(--ink-2); cursor: pointer; white-space: nowrap; }
.seg.md button { padding: 7px 12px; font-size: 13px; }
.seg.sm button { padding: 6px 10px; font-size: 12.5px; }
.seg button.on { background: var(--ink); color: #fff; }
</style>
