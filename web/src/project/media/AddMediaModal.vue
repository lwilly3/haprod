<script lang="ts">
export type AddTab = "files" | "youtube" | "images" | "doc";
export const ADD_TABS: readonly AddTab[] = ["files", "youtube", "images", "doc"];
</script>

<script setup lang="ts">
/** « Ajouter des médias » : fichiers de l'ordinateur, extraits YouTube, images trouvées par Claude, captures des sources du script. */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import Modal from "../../components/Modal.vue";
import DocTab from "./DocTab.vue";
import ImagesTab from "./ImagesTab.vue";
import YoutubeTab from "./YoutubeTab.vue";

const tab = defineModel<AddTab>("tab", { required: true });
defineProps<{ uploading: number | null }>();
const emit = defineEmits<{ close: []; files: [files: File[]]; added: [] }>();
const { t } = useI18n();

const title = computed(() => t(`media.add.tabs.${tab.value}.label`));

const over = ref(false);
const input = ref<HTMLInputElement>();

function send(list: FileList | null | undefined) {
  const files = Array.from(list ?? []);
  if (files.length) emit("files", files);
}

function onDrop(e: DragEvent) {
  over.value = false;
  send(e.dataTransfer?.files);
}

function onPick(e: Event) {
  const el = e.target as HTMLInputElement;
  send(el.files);
  el.value = "";
}
</script>

<template>
  <Modal :title="title" @close="emit('close')">
    <template #nav>
      <span class="nav-title">{{ t("media.add.title") }}</span>
      <button v-for="k in ADD_TABS" :key="k" class="src" :class="{ on: k === tab }" @click="tab = k">
        <span class="label">{{ t(`media.add.tabs.${k}.label`) }}</span>
        <span class="desc">{{ t(`media.add.tabs.${k}.desc`) }}</span>
      </button>
      <span class="spacer" />
      <span class="foot">{{ t("media.add.foot") }}</span>
    </template>

    <template v-if="tab === 'files'">
      <div class="drop-zone files" :class="{ over }" @click="input?.click()"
        @dragover.prevent="over = true" @dragleave="over = false" @drop.prevent="onDrop">
        <template v-if="uploading != null">{{ t("media.uploading", { pct: uploading }) }}</template>
        <template v-else>{{ t("media.add.drop") }}</template>
      </div>
      <input ref="input" type="file" multiple hidden @change="onPick">
    </template>
    <YoutubeTab v-else-if="tab === 'youtube'" />
    <ImagesTab v-else-if="tab === 'images'" @added="emit('added')" />
    <DocTab v-else />
  </Modal>
</template>

<style scoped>
.nav-title { font-size: 15px; font-weight: 600; padding: 0 10px 14px; }
.src {
  display: flex; flex-direction: column; gap: 2px; padding: 9px 10px; border: none; border-radius: 4px;
  background: transparent; text-align: left; cursor: pointer;
}
.src:hover { background: var(--hover); }
.src.on { background: #fff; }
.src .label { font-size: 13.5px; font-weight: 450; color: var(--ink); }
.src.on .label { font-weight: 600; }
.src .desc { font-size: 12px; color: var(--muted-2); line-height: 1.35; }
.foot { font-size: 12px; color: var(--faint); padding: 0 10px; line-height: 1.4; }
.files { padding: 36px 18px; }
</style>
