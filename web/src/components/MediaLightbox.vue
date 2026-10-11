<script setup lang="ts" generic="T extends { url: string; name: string; kind: string; duration: number | null }">
/** Un fichier en grand : l'image, la vidéo ou le son. ← → passent d'un fichier de la liste à l'autre, Échap ferme. */
import { computed, onBeforeUnmount, onMounted } from "vue";
import { useI18n } from "vue-i18n";
import { duration as fmtDuration } from "../lib/format";

/** `items` : les fichiers entre lesquels on navigue, dans l'ordre */
const props = defineProps<{ items: T[] }>();
const current = defineModel<T | null>({ required: true });
defineSlots<{ meta?: (p: { item: T }) => unknown; actions?: (p: { item: T }) => unknown }>();

const { t } = useI18n();

const at = computed(() => (current.value ? props.items.findIndex((x) => x.url === current.value!.url) : -1));

function step(d: number): void {
  const next = props.items[at.value + d];
  if (next) current.value = next;
}

function onKey(e: KeyboardEvent): void {
  if (!current.value) return;
  if (e.key === "Escape") current.value = null;
  else if (e.key === "ArrowLeft") step(-1);
  else if (e.key === "ArrowRight") step(1);
  else return;
  e.preventDefault();
}

onMounted(() => document.addEventListener("keydown", onKey));
onBeforeUnmount(() => document.removeEventListener("keydown", onKey));

// le navigateur n'affiche pas les .psd
const viewable = (x: T) => x.kind !== "Images" || !/\.psd$/i.test(x.name);
</script>

<template>
  <Teleport to="body">
    <template v-if="current">
      <div class="backdrop" @click="current = null" />
      <div class="lightbox">
        <img v-if="current.kind === 'Images' && viewable(current)" :src="current.url" alt="">
        <video v-else-if="current.kind === 'Vidéo'" :key="current.url" :src="current.url" controls autoplay />
        <audio v-else-if="current.kind === 'Audio'" :key="current.url" :src="current.url" controls autoplay />
        <div v-else class="none hatch">{{ t("common.noPreview") }}</div>
        <div class="foot">
          <button class="link-btn" :disabled="at <= 0" @click="step(-1)">←</button>
          <span class="zname" :title="current.name">{{ current.name }}</span>
          <span class="mono faint">
            {{ current.duration ? fmtDuration(current.duration) : current.kind }}<slot name="meta" :item="current" />
          </span>
          <button class="link-btn" :disabled="at < 0 || at >= items.length - 1" @click="step(1)">→</button>
          <slot name="actions" :item="current" />
          <a class="link-btn" :href="current.url" target="_blank" rel="noopener">{{ t("common.open") }}</a>
          <button class="btn sm" @click="current = null">{{ t("common.close") }}</button>
        </div>
      </div>
    </template>
  </Teleport>
</template>

<style scoped>
.backdrop { position: fixed; inset: 0; z-index: 40; background: rgba(24, 25, 27, .7); }
.lightbox {
  position: fixed; z-index: 41; top: 50%; left: 50%; transform: translate(-50%, -50%); width: min(1400px, 92vw);
  background: #fff; border-radius: 6px; box-shadow: 0 16px 48px rgba(0, 0, 0, .3); padding: 14px;
  display: flex; flex-direction: column; gap: 12px;
}
.lightbox img, .lightbox video { width: 100%; max-height: calc(92vh - 90px); object-fit: contain; display: block; border-radius: 4px; background: #111; }
.lightbox audio { width: 100%; }
.lightbox .none { height: 240px; display: flex; align-items: center; justify-content: center; color: var(--muted); font-size: 13px; }
.foot { display: flex; align-items: center; gap: 12px; font-size: 12.5px; min-width: 0; }
.foot :deep(.link-btn) { font-size: 13px; }
.foot button.link-btn { font-size: 16px; }
.zname { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
.faint { color: var(--faint); white-space: nowrap; }
</style>
