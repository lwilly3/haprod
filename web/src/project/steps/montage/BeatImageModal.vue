<script setup lang="ts">
/**
 * Choisir les images d'un beat sans passer par Médias : parmi les médias déjà là, en les important (fichier,
 * glisser-déposer, capture collée, adresse web), ou en les faisant chercher par Daryl à partir de la consigne du beat.
 * Une image importée est rangée dans les images du projet. Un motion en prend plusieurs (`multi` : la popup reste
 * ouverte, chaque choix s'ajoute) ; un B-roll un seul média (le choix ferme la popup).
 */
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import Modal from "../../../components/Modal.vue";
import { toast } from "../../../lib/toast";
import { upload } from "../../../lib/upload";
import ImagesTab from "../../media/ImagesTab.vue";
import { store } from "../../store";
import { isImage, type Beat, type Visual } from "./types";

export type ImageTab = "media" | "import" | "search";
const TABS: ImageTab[] = ["media", "import", "search"];

/** `tab` : l'onglet à l'ouverture (la recherche, rouverte depuis la file) */
const props = defineProps<{ beat: Beat; visuals: Visual[]; multi: boolean; selected: string[]; tab?: ImageTab }>();
const emit = defineEmits<{
  /** un seul média : le choix */
  pick: [string];
  /** plusieurs : une image cochée ou décochée, des images ajoutées */
  toggle: [string]; add: [string[]];
  close: [];
}>();
const { t: tr } = useI18n();

/** un motion n'intègre qu'une image ; un B-roll montre aussi une vidéo */
const choices = computed(() => props.visuals.filter((v) => props.beat.type === "broll" || v.kind === "image"));
const tab = ref<ImageTab>(props.tab ?? (choices.value.length ? "media" : "import"));
const shortName = (name: string) => name.replace(/\.[^.]+$/, "");

const busy = ref(false);
const over = ref(false);
const link = ref("");
const fileInput = ref<HTMLInputElement>();

async function importImage(file: File | null, url = "") {
  if (busy.value) return;
  if (file && !isImage(file.name)) return toast(tr("editing.beat.image.notImage"), true);
  busy.value = true;
  try {
    const { src } = await upload<{ src: string }>(`/api/projects/${store.project!.id}/assets/image`,
      file ? [file] : [], "file", file ? {} : { url });
    choose([src]);
    if (props.multi) toast(tr("editing.beat.image.added"));
    link.value = "";
  } catch (e) {
    toast((e as Error).message, true);
  } finally {
    busy.value = false;
  }
}

function onPick(e: Event) {
  const el = e.target as HTMLInputElement;
  if (el.files?.[0]) importImage(el.files[0]);
  el.value = "";
}
function onDrop(e: DragEvent) {
  over.value = false;
  const file = e.dataTransfer?.files?.[0];
  if (file) return importImage(file);
  // une image glissée depuis une page web arrive comme une adresse
  const url = e.dataTransfer?.getData("text/uri-list") || e.dataTransfer?.getData("text/plain");
  if (url?.startsWith("http")) importImage(null, url.trim());
}
/** une capture collée (Ctrl+V), où que soit le curseur dans la popup */
function onPaste(e: ClipboardEvent) {
  const file = [...(e.clipboardData?.files ?? [])].find((f) => f.type.startsWith("image/"));
  if (!file) return;
  e.preventDefault();
  importImage(new File([file], `capture-${Date.now()}.${file.type.split("/")[1] || "png"}`, { type: file.type }));
}
onMounted(() => window.addEventListener("paste", onPaste));
onUnmounted(() => window.removeEventListener("paste", onPaste));

function addLink() {
  const url = link.value.trim();
  if (url) importImage(null, url);
}
/** des images importées ou trouvées */
function choose(srcs: string[]) {
  if (!srcs.length) return;
  if (props.multi) emit("add", srcs);
  else emit("pick", srcs[0]);
}
function click(src: string) {
  if (props.multi) emit("toggle", src);
  else emit("pick", src);
}
</script>

<template>
  <Modal :title="tr(`editing.beat.image.tabs.${tab}`)" @close="emit('close')">
    <template #nav>
      <span class="nav-title">{{ beat.type === "broll" ? tr("editing.beat.image.titleBroll") : tr("editing.beat.image.title") }}</span>
      <button v-for="k in TABS" :key="k" class="src" :class="{ on: k === tab }" @click="tab = k">
        <span class="label">{{ tr(`editing.beat.image.tabs.${k}`) }}</span>
        <span class="desc">{{ tr(`editing.beat.image.tabsDesc.${k}`) }}</span>
      </button>
      <span class="spacer" />
      <template v-if="multi">
        <span class="mono count">{{ tr("editing.beat.image.chosen", selected.length) }}</span>
        <button class="btn dark md done" @click="emit('close')">{{ tr("editing.beat.image.done") }}</button>
      </template>
      <span class="foot">{{ tr("editing.beat.image.foot") }}</span>
    </template>

    <template v-if="tab === 'media'">
      <div v-if="!choices.length" class="dashed-box empty faint">{{ tr("editing.beat.image.noMedia") }}</div>
      <div v-for="w in ['projet', 'bibliothèque']" v-else :key="w" class="group">
        <template v-if="choices.some((x) => x.where === w)">
          <span class="eyebrow">{{ tr(`editing.storyboard.broll.where.${w === 'projet' ? 'project' : 'library'}`) }}</span>
          <div class="grid">
            <button v-for="v in choices.filter((x) => x.where === w)" :key="v.src" class="card" :class="{ on: selected.includes(v.src) }"
              :title="v.description || v.name" @click="click(v.src)">
              <span class="frame hatch">
                <span v-if="multi" class="check" :class="{ on: selected.includes(v.src) }">✓</span>
                <img v-if="v.kind === 'image'" :src="v.url" :alt="v.name" loading="lazy">
                <span v-else class="mono video">▶</span>
              </span>
              <span class="cap">{{ shortName(v.name) }}</span>
            </button>
          </div>
        </template>
      </div>
    </template>

    <div v-else-if="tab === 'import'" class="import">
      <div class="drop-zone" :class="{ over }" @click="fileInput?.click()"
        @dragover.prevent="over = true" @dragleave="over = false" @drop.prevent="onDrop">
        {{ busy ? tr("editing.beat.image.importing") : tr("editing.beat.image.drop") }}
      </div>
      <input ref="fileInput" type="file" accept="image/*" hidden @change="onPick">
      <label class="f">
        {{ tr("editing.beat.image.url") }}
        <span class="row">
          <input v-model="link" class="input soft link" :placeholder="tr('editing.beat.image.urlPh')" :disabled="busy" @keydown.enter="addLink">
          <button class="btn dark md" :disabled="busy || !link.trim()" @click="addLink">{{ tr("editing.beat.image.add") }}</button>
        </span>
      </label>
    </div>

    <ImagesTab v-else :beat="beat.id" :prefill="beat.show" @added="choose" />
  </Modal>
</template>

<style scoped>
.nav-title { font-size: 15px; font-weight: 600; padding: 0 10px 14px; }
.src { display: flex; flex-direction: column; gap: 2px; padding: 9px 10px; border: none; border-radius: 4px; background: transparent; text-align: left; cursor: pointer; }
.src:hover { background: var(--hover); }
.src.on { background: #fff; }
.src .label { font-size: 13.5px; font-weight: 450; color: var(--ink); }
.src.on .label { font-weight: 600; }
.src .desc { font-size: 12px; color: var(--muted-2); line-height: 1.35; }
.foot { font-size: 12px; color: var(--faint); padding: 0 10px; line-height: 1.4; }
.empty { padding: 48px 20px; text-align: center; font-size: 13px; }
.group { display: flex; flex-direction: column; gap: 10px; margin-bottom: 20px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }
.card { display: flex; flex-direction: column; gap: 4px; padding: 0; border: none; background: none; cursor: pointer; text-align: left; }
.frame { position: relative; aspect-ratio: 4/3; display: flex; align-items: center; justify-content: center; overflow: hidden; outline: 2px solid transparent; outline-offset: -2px; }
.card:hover .frame { outline-color: var(--line-strong); }
.card.on .frame { outline-color: var(--ink); }
.frame img { max-width: 100%; max-height: 100%; object-fit: contain; }
.check {
  position: absolute; top: 6px; left: 6px; width: 18px; height: 18px; border: 1px solid var(--line-strong); border-radius: 3px;
  background: #fff; color: transparent; font-size: 11px; line-height: 16px; text-align: center;
}
.check.on { background: var(--ink); border-color: var(--ink); color: #fff; }
.count { font-size: 12px; color: var(--muted); padding: 0 10px 8px; }
.done { margin: 0 10px 14px; }
.video { font-size: 22px; color: var(--muted); }
.cap { font-size: 12.5px; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.import { display: flex; flex-direction: column; gap: 22px; max-width: 640px; }
.drop-zone { padding: 56px 18px; }
.f { display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; color: var(--muted); }
.row { display: flex; gap: 8px; }
.link { flex: 1; min-width: 0; height: 34px; font-size: 13px; padding: 0 10px; }
</style>
