<script setup lang="ts">
/**
 * Une popup centrée sur un fond assombri : un clic à côté ou Échap la ferme.
 * Avec le slot `nav`, une colonne grise à gauche (les rubriques) ; le slot par défaut défile sous l'en-tête.
 */
import { onMounted, onUnmounted } from "vue";
import { useI18n } from "vue-i18n";

withDefaults(defineProps<{ title?: string; width?: string; height?: string }>(), { title: "", width: "1120px", height: "760px" });
const emit = defineEmits<{ close: [] }>();
const { t } = useI18n();

function onKey(e: KeyboardEvent) {
  if (e.key === "Escape") emit("close");
}
onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <div class="overlay" @click.self="emit('close')">
    <div class="modal" :class="{ 'with-nav': $slots.nav }" :style="{ maxWidth: width, height: `min(${height}, 100%)` }" role="dialog" aria-modal="true">
      <aside v-if="$slots.nav" class="nav"><slot name="nav" /></aside>
      <div class="main">
        <div class="head">
          <span class="title">{{ title }}</span>
          <slot name="head" />
          <span class="spacer" />
          <button class="close" @click="emit('close')">{{ t("common.close") }} ×</button>
        </div>
        <div class="body"><slot /></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed; inset: 0; z-index: 40; background: rgba(24, 25, 27, .32);
  display: flex; align-items: center; justify-content: center; padding: 32px;
}
.modal {
  width: 100%; background: #fff; border-radius: 6px; box-shadow: 0 24px 64px rgba(0, 0, 0, .22);
  display: grid; grid-template-columns: minmax(0, 1fr); overflow: hidden;
}
.modal.with-nav { grid-template-columns: 220px minmax(0, 1fr); }
.nav { display: flex; flex-direction: column; gap: 2px; padding: 20px 12px; background: #F7F7F5; border-right: 1px solid var(--line); min-height: 0; }
.main { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.head { display: flex; align-items: center; gap: 12px; padding: 16px 24px; border-bottom: 1px solid var(--line); }
.title { font-size: 15px; font-weight: 600; }
.close { border: none; background: none; padding: 0; font-size: 13px; color: var(--muted); cursor: pointer; }
.close:hover { color: var(--ink); }
.body { flex: 1; overflow: auto; padding: 20px 24px 28px; display: flex; flex-direction: column; gap: 18px; }
</style>
