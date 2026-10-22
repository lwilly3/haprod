<script setup lang="ts">
/**
 * Les médias d'un beat, sur une ligne : un motion intègre autant d'images et de vidéos qu'il faut (une capture à
 * surligner, un portrait, des logos, un extrait…), en vignettes côte à côte qui défilent en largeur ; un B-roll montre
 * son média. Le choix (médias, import, vidéo YouTube, recherche par Daryl) se fait dans une popup.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import BeatImageModal, { type ImageTab } from "./BeatImageModal.vue";
import { beatImages, type Beat, type Visual } from "./types";

/** `popup` : la popup ouverte, sur cet onglet (tenue par le montage, qui la rouvre depuis la file des recherches) */
const props = defineProps<{ beat: Beat; visuals: Visual[]; popup: ImageTab | null }>();
const emit = defineEmits<{
  /** B-roll : le média choisi ("" : aucun) */
  pick: [string];
  /** motion : ses images, dans l'ordre */
  images: [string[]];
  /** ouvrir la popup (sur son premier onglet), ou la fermer */
  popup: [ImageTab | null];
}>();
const { t: tr } = useI18n();

/** la popup s'ouvre sur les médias s'il y en a à choisir, sinon sur l'import */
const firstTab = (): ImageTab => props.visuals.length ? "media" : "import";
const open = computed({ get: () => !!props.popup, set: (v: boolean) => emit("popup", v ? (props.popup ?? firstTab()) : null) });
const multi = computed(() => props.beat.type === "motion");
const images = computed(() => beatImages(props.beat));
const visual = (src?: string) => props.visuals.find((v) => v.src === src);
const current = computed(() => visual(props.beat.src));
const shortName = (name: string) => name.replace(/\.[^.]+$/, "");
const nameOf = (src: string) => shortName(visual(src)?.name ?? src.split("/").pop() ?? src);

function pick(src: string) {
  open.value = false;
  emit("pick", src);
}
function toggle(src: string) {
  emit("images", images.value.includes(src) ? images.value.filter((x) => x !== src) : [...images.value, src]);
}
function add(srcs: string[]) {
  emit("images", [...images.value, ...srcs.filter((s) => !images.value.includes(s))]);
}
</script>

<template>
  <div class="beat-image">
    <span class="lbl">
      {{ multi ? tr("editing.beat.image.label") : tr("editing.storyboard.broll.media") }}
      <template v-if="multi && images.length"> · {{ images.length }}</template>
    </span>

    <template v-if="multi">
      <div v-if="images.length" class="strip">
        <div v-for="src in images" :key="src" class="tile hatch" :title="nameOf(src)">
          <img v-if="visual(src)?.kind !== 'video'" :src="visual(src)?.url" :alt="nameOf(src)" loading="lazy">
          <template v-else>
            <video :src="`${visual(src)!.url}#t=1`" preload="metadata" muted playsinline />
            <span class="mono play">▶</span>
          </template>
          <button class="rm" :title="tr('editing.beat.image.remove')" @click="toggle(src)">×</button>
        </div>
        <button class="tile add" :title="tr('editing.beat.image.addImages')" @click="open = true">+</button>
      </div>
      <button v-else class="link-btn start" @click="open = true">+ {{ tr("editing.beat.image.addImages") }}</button>
    </template>

    <template v-else>
      <div v-if="current" class="cur">
        <span class="thumb hatch" @click="open = true">
          <img v-if="current.kind === 'image'" :src="current.url" :alt="current.name">
          <span v-else class="mono">▶</span>
        </span>
        <span class="name" :title="current.name">{{ shortName(current.name) }}</span>
        <button class="link-btn" @click="open = true">{{ tr("editing.beat.image.change") }}</button>
        <button class="x-btn" :title="tr('editing.beat.image.remove')" @click="emit('pick', '')">×</button>
      </div>
      <button v-else class="link-btn start" @click="open = true">+ {{ tr("editing.beat.image.addBroll") }}</button>
    </template>

    <BeatImageModal v-if="popup" :tab="popup" :beat="beat" :visuals="visuals" :multi="multi" :selected="multi ? images : beat.src ? [beat.src] : []"
      @pick="pick" @toggle="toggle" @add="add" @close="open = false" />
  </div>
</template>

<style scoped>
.beat-image { display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; color: var(--muted); min-width: 0; }
/* les vignettes côte à côte : au-delà de la largeur du panneau, elles défilent */
.strip { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 2px; scrollbar-width: thin; }
.tile { position: relative; flex: 0 0 64px; height: 44px; border-radius: 3px; overflow: hidden; display: flex; align-items: center; justify-content: center; }
.tile img, .tile video { width: 100%; height: 100%; object-fit: cover; }
.play { position: absolute; font-size: 13px; color: #fff; text-shadow: 0 1px 3px rgba(0, 0, 0, .6); pointer-events: none; }
.rm {
  position: absolute; top: 2px; right: 2px; width: 16px; height: 16px; padding: 0; border: none; border-radius: 50%;
  background: rgba(24, 25, 27, .7); color: #fff; font-size: 12px; line-height: 16px; cursor: pointer; opacity: 0;
}
.tile:hover .rm, .rm:focus-visible { opacity: 1; }
.tile.add { border: 1px dashed var(--line-strong); background: #fff; color: var(--muted); font-size: 18px; cursor: pointer; }
.tile.add:hover { border-color: var(--ink); color: var(--ink); }
.cur { display: flex; align-items: center; gap: 10px; min-width: 0; }
.thumb { width: 56px; height: 36px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; overflow: hidden; border-radius: 3px; cursor: pointer; }
.thumb img { width: 100%; height: 100%; object-fit: cover; }
.name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink-2); font-size: 13px; }
.link-btn { font-size: 12.5px; }
.start { align-self: flex-start; }
</style>
