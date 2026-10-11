<script setup lang="ts">
/** Case à cocher carrée, avec son libellé (slot) cliquable. */
defineProps<{ disabled?: boolean }>();
const model = defineModel<boolean>({ required: true });
</script>

<template>
  <button type="button" class="check" :class="{ on: model }" :disabled="disabled" role="checkbox" :aria-checked="model"
    @click.stop="model = !model">
    <span class="box">{{ model ? "✓" : "" }}</span>
    <span v-if="$slots.default" class="label"><slot /></span>
  </button>
</template>

<style scoped>
.check { display: inline-flex; align-items: center; gap: 8px; border: none; background: none; padding: 0; font-size: 13px; cursor: pointer; color: var(--ink); }
.check:disabled { cursor: default; opacity: .45; }
.box {
  width: 16px; height: 16px; flex-shrink: 0; border-radius: 3px; border: 1px solid var(--dash); background: #fff;
  color: #fff; font-size: 10px; display: flex; align-items: center; justify-content: center;
}
.check.on .box { background: var(--ink); border-color: var(--ink); }
</style>
