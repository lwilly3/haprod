<script setup lang="ts">
/** Croix de suppression en deux temps : un premier clic demande confirmation, le second supprime. */
import { onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{ label?: string; title?: string }>();
const { t } = useI18n();
const emit = defineEmits<{ confirm: [] }>();

const armed = ref(false);
let timer: ReturnType<typeof setTimeout> | undefined;

function click() {
  clearTimeout(timer);
  if (armed.value) {
    armed.value = false;
    emit("confirm");
    return;
  }
  armed.value = true;
  // sans second clic, la croix revient
  timer = setTimeout(() => (armed.value = false), 3000);
}

onUnmounted(() => clearTimeout(timer));
</script>

<template>
  <button type="button" :class="armed ? 'armed' : 'x-btn'" :title="armed ? '' : props.title ?? t('common.delete')" @click.stop="click" @blur="armed = false">
    {{ armed ? props.label ?? t("format.confirmDelete") : "×" }}
  </button>
</template>

<style scoped>
.armed {
  height: 22px; padding: 0 8px; border: none; border-radius: 3px; background: var(--red); color: #fff;
  font-size: 12px; line-height: 1; cursor: pointer; white-space: nowrap;
}
</style>
