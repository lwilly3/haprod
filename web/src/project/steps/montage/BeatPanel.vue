<script setup lang="ts">
/**
 * À la place de l'inspecteur : le beat du storyboard sélectionné sur la timeline (posé à la main, ou proposé). On y
 * change son type, on réécrit sa consigne (« on montre »), on lui donne son image, puis on lance ce qu'il faut : créer l'animation, poser
 * le zoom ou le B-roll, ou en parler à Daryl. Les réglages fins restent à l'étape Storyboard.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import BeatImage from "./BeatImage.vue";
import type { ImageTab } from "./BeatImageModal.vue";
import { BEAT_TYPES, isImage, needsAnim, tcd, TYPE_COLOR, type AnimState, type Beat, type BeatType, type Visual } from "./types";

const props = defineProps<{ beat: Beat; anims: Record<string, AnimState>; visuals: Visual[]; places: string[]; imagePopup: ImageTab | null }>();
const emit = defineEmits<{
  /** une retouche du beat ; `delay` : regroupe les frappes */
  change: [(b: Beat) => void, number?];
  create: [string]; stop: [string]; remove: [string]; ask: [string]; seek: [number]; close: [];
  /** le média d'un B-roll ("" : aucun), ou les images d'un motion ; peut-être tout juste importés */
  image: [string]; images: [string[]]; imagePopup: [ImageTab | null];
}>();
const { t: tr } = useI18n();

const anim = computed(() => props.anims[props.beat.id]);
const live = computed(() => ["queued", "running"].includes(anim.value?.status ?? ""));
/** zoom et B-roll vidéo se posent tels quels ; un B-roll sans média attend le sien */
const placeable = computed(() => props.beat.type === "zoom" || (props.beat.type === "broll" && !!props.beat.src && !isImage(props.beat.src)));

function setType(type: BeatType) {
  emit("change", (b) => {
    b.type = type;
    if (type === "zoom") b.zoom ??= { scale: 1.25, x: 0, y: 0, style: "smooth" };
    if (type === "broll") {
      b.src ??= "";
      b.search ??= "";
      if (!["full", "left", "right"].includes(b.place)) b.place = "full";
    }
  });
}
</script>

<template>
  <div class="beat-panel" :style="{ '--c': TYPE_COLOR[beat.type] }">
    <div class="head">
      <span class="eyebrow kind">{{ tr(`editing.storyboard.types.${beat.type}`) }}</span>
      <span class="mono time" @click="emit('seek', beat.at + 0.05)">{{ tcd(beat.at) }} → {{ tcd(beat.at + beat.dur) }}</span>
      <span class="spacer" />
      <button class="x-btn" :title="tr('editing.inspector.deselect')" @click="emit('close')">×</button>
    </div>

    <div class="types">
      <button v-for="k in BEAT_TYPES" :key="k" class="type" :class="{ on: beat.type === k }" :style="{ '--c': TYPE_COLOR[k] }"
        :disabled="live" @click="setType(k)">{{ tr(`editing.storyboard.types.${k}`) }}</button>
    </div>

    <p v-if="beat.says" class="says">« {{ beat.says }} »</p>
    <textarea class="input area" rows="4" :value="beat.show" :placeholder="tr(`editing.storyboard.showPh.${beat.type}`)"
      @input="emit('change', (b) => { b.show = ($event.target as HTMLTextAreaElement).value; }, 800)" />

    <label v-if="beat.type === 'motion' || (beat.type === 'broll' && isImage(beat.src))" class="f">
      {{ tr("editing.storyboard.place") }}
      <select :value="beat.place" @change="emit('change', (b) => { b.place = ($event.target as HTMLSelectElement).value; }, 150)">
        <option v-for="p in beat.type === 'broll' ? ['full', 'left', 'right'] : places" :key="p" :value="p">{{ tr(`editing.storyboard.places.${p}`) }}</option>
      </select>
    </label>

    <BeatImage v-if="beat.type === 'motion' || beat.type === 'broll'" :beat="beat" :visuals="visuals" :popup="imagePopup"
      @pick="(src) => emit('image', src)" @images="(srcs) => emit('images', srcs)" @popup="(t) => emit('imagePopup', t)" />

    <p v-if="anim?.status === 'error'" class="err">{{ tr("editing.anims.failed", { e: anim.error }) }}</p>
    <div class="row actions">
      <template v-if="live">
        <span class="mono state">{{ anim!.status === "queued" ? tr("editing.anims.queued") : `${tr("editing.anims.running")} · ${anim!.activity ?? ""}` }}</span>
        <button class="btn sm" @click="emit('stop', beat.id)">{{ tr("common.stop") }}</button>
      </template>
      <button v-else-if="needsAnim(beat)" class="btn sm dark" @click="emit('create', beat.id)">
        {{ anim ? tr("editing.anims.retry") : tr("editing.storyboard.create") }}
      </button>
      <button v-else-if="placeable" class="btn sm dark" @click="emit('create', beat.id)">{{ tr("editing.storyboard.place_") }}</button>
      <button class="btn sm" :title="tr('editing.beat.askTitle')" @click="emit('ask', beat.id)">{{ tr("editing.beat.ask") }}</button>
      <span class="spacer" />
      <button class="link-btn" @click="emit('remove', beat.id)">{{ tr("common.delete") }}</button>
    </div>
    <p class="hint">{{ tr("editing.beat.hint") }}</p>
  </div>
</template>

<style scoped>
.beat-panel { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.head { display: flex; align-items: center; gap: 10px; }
.kind { font-size: 10.5px; color: color-mix(in srgb, var(--c) 75%, #000); }
.time { font-size: 12px; color: var(--muted); cursor: pointer; }
.types { display: flex; flex-wrap: wrap; gap: 4px; }
.type { border: 1px solid var(--line-strong); border-radius: 3px; background: #fff; padding: 4px 8px; font-size: 12px; cursor: pointer; color: var(--ink-2); }
.type.on { border-color: var(--c); background: color-mix(in srgb, var(--c) 14%, #fff); color: color-mix(in srgb, var(--c) 70%, #000); font-weight: 600; }
.type:disabled { cursor: default; opacity: .6; }
.says { margin: 0; font-size: 12.5px; color: var(--muted); line-height: 1.45; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.input.area { height: auto; padding: 8px 10px; resize: vertical; font-family: inherit; font-size: 13.5px; line-height: 1.4; }
.f { display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; color: var(--muted); }
.row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.actions .link-btn { font-size: 12.5px; }
.state { font-size: 11.5px; color: #7C5CE0; }
.err { margin: 0; font-size: 12px; color: var(--red-ink); }
.hint { margin: 0; font-size: 12px; color: var(--faint); line-height: 1.5; }
</style>
