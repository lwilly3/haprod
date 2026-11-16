<script setup lang="ts">
/**
 * La bibliothèque commune à tous les projets : B-roll, musique, sound design, images, et les animations type.
 * Un clic montre une image ou une vidéo en grand ; un son se joue sur place.
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import AnimationPreview from "../components/AnimationPreview.vue";
import MediaLightbox from "../components/MediaLightbox.vue";
import Thumb from "../components/Thumb.vue";
import TransitionGallery from "../components/TransitionGallery.vue";
import { api, del, post } from "../lib/api";
import { duration as fmtDuration } from "../lib/format";
import { toast } from "../lib/toast";
import { droppedFiles, upload } from "../lib/upload";
import { close } from "../project/store";
import KitDesign from "./library/KitDesign.vue";
import { useKitAdapt } from "./library/useKitAdapt";

interface Credit { title: string; creator: string; license: string; url: string; required: boolean; line: string }
interface Item { credit?: Credit | null; name: string; rel: string; category: string; type: string; project: string | null; description: string; gain_db: number | null; duration: number | null; kind: string }
interface Animation {
  name: string; id: string; title: string; description: string; format: "youtube" | "short"; tier: string;
  duration: number | null; hero: number | null; url: string;
  /** une animation du kit ajoutée par l'utilisateur (on peut la retirer) */
  mine?: boolean;
}
/** un style de cartes importé d'editing-os */
interface AnimStyle { id: string; name: string; inspiration: string; count: number }

/** l'onglet des animations type : des compositions, pas des fichiers déposés */
const ANIMATIONS = "animations";
/** l'onglet des transitions du montage : une galerie, rien à déposer */
const TRANSITIONS = "transitions";

const { t, te } = useI18n();
const categories = ref<Record<string, string>>({});
const items = ref<Item[]>([]);
const animations = ref<Animation[]>([]);
const styles = ref<AnimStyle[]>([]);
/** "kit" (les animations type du studio) ou l'id d'un style d'editing-os */
const animSource = ref("kit");
/** les cartes des styles déjà ouverts */
const styleCards = ref<Record<string, Animation[]>>({});
/** l'animation survolée, qui se joue */
const playing = ref<string | null>(null);
/** "all" ou la clé d'une catégorie */
const tab = ref("all");
const over = ref(false);
const uploading = ref<number | null>(null);

onMounted(async () => {
  close();
  const data = await api<{ categories: Record<string, string>; items: Item[] }>("/api/projects/library");
  categories.value = data.categories;
  items.value = data.items;
  const anims = await api<{ items: Animation[]; styles: AnimStyle[] }>("/api/projects/library/animations");
  animations.value = anims.items;
  styles.value = anims.styles;
  adapt.refresh();
});

// --- sons libres de droits, cherchés en ligne (Openverse : Freesound, Jamendo) -------------------

interface FreeSound {
  id: string; title: string; creator: string; license: string; url: string; preview: string;
  duration: number | null; required: boolean; source: string;
}
/** les onglets où la recherche en ligne existe (backend free_audio.FILTERS) */
const FREE_TABS = ["sfx", "musique"];
const freeQuery = ref("");
const freeResults = ref<FreeSound[] | null>(null);
const freeBusy = ref(false);
/** les sons en cours d'ajout, et ceux déjà ajoutés depuis cette recherche */
const freeAdding = ref<string[]>([]);
const freeAdded = ref<string[]>([]);

async function searchFree() {
  if (!category.value || !freeQuery.value.trim() || freeBusy.value) return;
  freeBusy.value = true;
  stopSound();
  try {
    const q = new URLSearchParams({ category: category.value, q: freeQuery.value.trim() });
    freeResults.value = (await api<{ items: FreeSound[] }>(`/api/projects/library/free?${q}`)).items;
  } catch (e) {
    toast((e as Error).message, true);
  } finally {
    freeBusy.value = false;
  }
}

async function addFree(x: FreeSound) {
  if (!category.value || freeAdding.value.includes(x.id)) return;
  freeAdding.value = [...freeAdding.value, x.id];
  try {
    items.value = (await post<{ items: Item[] }>("/api/projects/library/free", { category: category.value, id: x.id })).items;
    freeAdded.value = [...freeAdded.value, x.id];
    toast(t("library.free.added", { title: x.title }));
  } catch (e) {
    toast((e as Error).message, true);
  } finally {
    freeAdding.value = freeAdding.value.filter((id) => id !== x.id);
  }
}

/** Écoute un résultat sans le télécharger : l'extrait est lu depuis sa source. */
function toggleFree(x: FreeSound): void {
  const el = player.value!;
  const key = `free:${x.id}`;
  if (sound.value === key) {
    el.pause();
    sound.value = null;
    return;
  }
  el.src = x.preview;
  el.play().catch((e) => e.name !== "AbortError" && toast(e.message, true));
  sound.value = key;
}

// --- le kit : design system, inspirations reportées --------------------------------------------

/** change à chaque réglage du design system : les aperçus du kit se rechargent avec la nouvelle charte */
const kitVersion = ref(0);
const previewUrl = (a: Animation) => (animSource.value === "kit" ? `${a.url}?v=${kitVersion.value}` : a.url);

async function reloadKit() {
  animations.value = (await api<{ items: Animation[] }>("/api/projects/library/animations")).items;
}

const adapt = useKitAdapt(
  (j) => {
    reloadKit();
    toast(t("library.adaptDone", { name: j.result?.name.replace(/^exemple-|\.html$/g, "") ?? j.title }));
    if (j.result?.hard_colors.length) toast(t("library.adaptHardColors", { colors: j.result.hard_colors.join(" ") }), true);
  },
  (j) => toast(j.error || t("library.adaptFailed"), true),
);

function toKit(a: Animation) {
  adapt.start(animSource.value, a.name).catch((e) => toast((e as Error).message, true));
}

async function removeFromKit(a: Animation) {
  try {
    animations.value = (await del<{ items: Animation[] }>(`/api/projects/library/animations/${encodeURIComponent(a.name)}`)).items;
  } catch (e) {
    toast((e as Error).message, true);
  }
}

async function pickSource(id: string) {
  animSource.value = id;
  if (id === "kit" || styleCards.value[id]) return;
  try {
    styleCards.value[id] = (await api<{ items: Animation[] }>(`/api/projects/library/animations/styles/${encodeURIComponent(id)}`)).items;
  } catch (e) {
    toast((e as Error).message, true);
  }
}

const style = computed(() => styles.value.find((s) => s.id === animSource.value));
/** les animations affichées, par type de carte (plein écran, surcouche, transition…) */
const animGroups = computed(() => {
  const list = animSource.value === "kit" ? animations.value : styleCards.value[animSource.value] ?? [];
  const groups = new Map<string, Animation[]>();
  for (const a of list) groups.set(a.tier, [...(groups.get(a.tier) ?? []), a]);
  return [...groups].map(([tier, items]) => ({ tier, items }));
});

// --- la description d'un fichier, que lit Daryl ---------------------------------------------

async function describe(x: Item, e: Event) {
  const value = (e.target as HTMLInputElement).value.trim();
  if (value === x.description) return;
  try {
    items.value = (await post<{ items: Item[] }>("/api/projects/library/describe", { rel: x.rel, description: value })).items;
  } catch (err) {
    toast((err as Error).message, true);
  }
}

/** Le volume (dB) auquel poser un son au montage ; vide : le défaut du studio. */
async function setGain(x: Item, e: Event) {
  const raw = (e.target as HTMLInputElement).value.trim().replace(",", ".");
  const value = raw === "" ? null : Number(raw);
  if (value != null && !Number.isFinite(value)) return;
  if (value === x.gain_db) return;
  try {
    items.value = (await post<{ items: Item[] }>("/api/projects/library/gain", { rel: x.rel, gain_db: value })).items;
  } catch (err) {
    toast((err as Error).message, true);
  }
}

/** Le libellé d'une catégorie dans la langue de l'interface, sinon celui de l'API. */
const label = (k: string, fallback = categories.value[k] ?? k) => (te(`library.categories.${k}`) ? t(`library.categories.${k}`) : fallback);
const tabs = computed(() => ["all", ...Object.keys(categories.value), ANIMATIONS, TRANSITIONS]);
const shown = computed(() => (tab.value === "all" ? items.value : items.value.filter((x) => x.category === tab.value)));
const category = computed(() => (tab.value === "all" ? undefined : tab.value));

async function onDrop(e: DragEvent) {
  over.value = false;
  const files = droppedFiles(e);
  if (!files.length) return;
  if (!category.value) {
    toast(t("library.pickTabFirst"), true);
    return;
  }
  uploading.value = 0;
  try {
    items.value = (await upload<{ items: Item[] }>("/api/projects/library/upload", files, "files", { category: category.value },
      (f) => (uploading.value = Math.round(f * 100)))).items;
    toast(t("library.filesAdded", files.length));
  } catch (err) {
    toast((err as Error).message, true);
  } finally {
    uploading.value = null;
  }
}

function reveal(rel: string) {
  post("/api/projects/library/reveal", { rel }).catch((e) => toast(e.message, true));
}

const fileUrl = (rel: string) => `/api/projects/library/file/${rel.split("/").map(encodeURIComponent).join("/")}`;

// --- le fichier en grand ---------------------------------------------------------------

type Entry = Item & { url: string };
const zoom = ref<Entry | null>(null);
/** Les images et vidéos de l'onglet, dans l'ordre : ← → passent de l'une à l'autre. */
const zoomable = computed<Entry[]>(() => shown.value.filter((x) => x.kind === "Images" || x.kind === "Vidéo").map((x) => ({ ...x, url: fileUrl(x.rel) })));

// --- les sons, joués sur place -------------------------------------------------------------

const player = ref<HTMLAudioElement | null>(null);
/** le son en cours de lecture */
const sound = ref<string | null>(null);

function toggle(x: Item): void {
  const el = player.value!;
  if (sound.value === x.rel) {
    el.pause();
    sound.value = null;
    return;
  }
  el.src = fileUrl(x.rel);
  // passer vite d’un son à l’autre interrompt la lecture précédente : ce n’est pas une erreur
  el.play().catch((e) => e.name !== "AbortError" && toast(e.message, true));
  sound.value = x.rel;
}

function stopSound(): void {
  player.value?.pause();
  sound.value = null;
}

onBeforeUnmount(stopSound);

function onClick(x: Item): void {
  if (x.kind === "Audio") return toggle(x);
  const z = zoomable.value.find((e) => e.rel === x.rel);
  if (!z) return reveal(x.rel);
  stopSound();
  zoom.value = z;
}
</script>

<template>
  <div class="page">
    <span class="h1">{{ t("library.title") }}</span>
    <div class="tabs">
      <button v-for="k in tabs" :key="k" :class="{ on: k === tab }" @click="tab = k; stopSound()">{{ k === "all" ? t("common.all") : k === ANIMATIONS ? t("library.animations") : k === TRANSITIONS ? t("transitions.title") : label(k) }}</button>
    </div>
    <div v-if="tab === TRANSITIONS" class="transitions">
      <span class="muted hint">{{ t("transitions.hint") }}</span>
      <TransitionGallery />
    </div>
    <div v-else-if="tab === ANIMATIONS" class="anim-layout">
      <nav class="sources">
        <button class="source" :class="{ on: animSource === 'kit' }" @click="pickSource('kit')">
          <span class="source-name">{{ t("library.myKit") }}</span><span class="n">{{ animations.length }}</span>
        </button>
        <template v-if="styles.length">
          <span class="eyebrow sources-head">{{ t("library.inspirations") }}</span>
          <button v-for="s in styles" :key="s.id" class="source" :class="{ on: animSource === s.id }" :title="s.inspiration" @click="pickSource(s.id)">
            <span class="source-name">{{ s.name }}</span><span class="n">{{ s.count }}</span>
          </button>
        </template>
      </nav>
      <div class="anim-main">
        <span class="muted hint">{{ style ? style.inspiration : t("library.animationsHint") }}</span>
        <KitDesign v-if="animSource === 'kit'" @saved="kitVersion++" />
        <section v-for="g in animGroups" :key="g.tier" class="anim-group">
          <span v-if="g.tier !== 'kit'" class="eyebrow">{{ te(`library.tiers.${g.tier}`) ? t(`library.tiers.${g.tier}`) : g.tier }} · {{ g.items.length }}</span>
          <div class="grid">
            <div v-for="a in g.items" :key="a.name" class="anim-card" @mouseenter="playing = a.name" @mouseleave="playing = null">
              <AnimationPreview :src="previewUrl(a)" :id="a.id" :format="a.format" :hero="a.hero" :playing="playing === a.name" />
              <div class="anim-meta">
                <span class="anim-name">{{ a.title }}</span>
                <span class="mono faint dur">{{ a.duration ? fmtDuration(a.duration) : "" }}</span>
                <span class="spacer" />
                <button v-if="animSource !== 'kit'" class="link-btn" :disabled="adapt.running(a.name)" @click="toKit(a)">
                  {{ adapt.running(a.name) ? t("library.adapting") : t("library.toKit") }}
                </button>
                <button v-else-if="a.mine" class="link-btn" @click="removeFromKit(a)">{{ t("common.remove") }}</button>
              </div>
              <span class="muted anim-desc">{{ a.description }}</span>
            </div>
          </div>
        </section>
        <span v-if="!animGroups.length" class="nothing">{{ t("common.nothingYet") }}</span>
      </div>
    </div>
    <template v-else>
      <div class="drop-zone" :class="{ over }" @dragover.prevent="over = true" @dragleave="over = false" @drop.prevent="onDrop">
        <template v-if="uploading != null">{{ t("library.uploading", { pct: uploading }) }}</template>
        <template v-else-if="category">{{ t("library.dropInto", { tab: label(category) }) }}</template>
        <template v-else>{{ t("library.pickTab") }}</template>
      </div>
      <div v-if="category && FREE_TABS.includes(category)" class="free">
        <div class="free-bar">
          <input v-model="freeQuery" class="input" :placeholder="t(`library.free.placeholder.${category}`)" @keydown.enter="searchFree">
          <button class="btn dark" :disabled="!freeQuery.trim() || freeBusy" @click="searchFree">{{ freeBusy ? t("library.free.searching") : t("library.free.search") }}</button>
          <button v-if="freeResults" class="link-btn" @click="freeResults = null; stopSound()">{{ t("common.close") }}</button>
        </div>
        <span class="muted hint">{{ t("library.free.hint") }}</span>
        <div v-if="freeResults" class="free-list">
          <div v-for="x in freeResults" :key="x.id" class="free-row" :class="{ playing: sound === `free:${x.id}` }">
            <button class="play" :title="sound === `free:${x.id}` ? t('common.pause') : t('common.play')" @click="toggleFree(x)">{{ sound === `free:${x.id}` ? "❚❚" : "▶" }}</button>
            <span class="name" :title="x.title">{{ x.title }}</span>
            <a class="muted" :href="x.url" target="_blank" rel="noopener" :title="t('library.free.openSource')">{{ x.creator }}</a>
            <span class="license" :class="{ credit: x.required }" :title="x.required ? t('library.free.creditRequired') : t('library.free.noCredit')">{{ x.license }}</span>
            <span class="mono r dur">{{ x.duration ? fmtDuration(x.duration) : "" }}</span>
            <button class="btn" :disabled="freeAdding.includes(x.id) || freeAdded.includes(x.id)" @click="addFree(x)">
              {{ freeAdded.includes(x.id) ? t("library.free.inLibrary") : freeAdding.includes(x.id) ? t("library.free.adding") : t("library.free.add") }}
            </button>
          </div>
          <span v-if="!freeResults.length" class="nothing">{{ t("library.free.none") }}</span>
        </div>
      </div>
      <div class="table">
        <div class="row head eyebrow"><span /><span>{{ t("common.name") }}</span><span>{{ t("library.description") }}</span><span>{{ t("library.gain") }}</span><span>{{ t("common.type") }}</span><span>{{ t("common.project") }}</span><span class="r">{{ t("common.duration") }}</span></div>
        <div v-for="x in shown" :key="x.rel" class="row" :class="{ playing: sound === x.rel }" :title="x.kind === 'Audio' ? undefined : t('common.open')" @click="onClick(x)">
          <button v-if="x.kind === 'Audio'" class="play" :title="sound === x.rel ? t('common.pause') : t('common.play')">{{ sound === x.rel ? "❚❚" : "▶" }}</button>
          <Thumb v-else :src="fileUrl(x.rel)" :kind="x.kind" :name="x.name" />
          <span class="name">{{ x.name }}<span v-if="x.credit" class="credit-line" :title="x.credit.line"> · {{ x.credit.creator }} · {{ x.credit.license }}</span></span>
          <input
            class="desc" :value="x.description" :placeholder="t('library.describe')" :title="x.description"
            @click.stop @keydown.enter="($event.target as HTMLInputElement).blur()" @change="describe(x, $event)"
          >
          <span v-if="x.kind === 'Audio'" class="gain" :title="t('library.gainHint')" @click.stop>
            <input class="desc mono" :value="x.gain_db ?? ''" :placeholder="t('library.gainDefault')"
              @keydown.enter="($event.target as HTMLInputElement).blur()" @change="setGain(x, $event)"> dB
          </span>
          <span v-else />
          <span class="muted">{{ label(x.category, x.type) }}</span>
          <span class="muted">{{ x.project ?? "—" }}</span>
          <span class="mono r dur">{{ x.duration ? fmtDuration(x.duration) : "" }}</span>
        </div>
        <span v-if="!shown.length" class="nothing">{{ t("common.nothingYet") }}</span>
      </div>
      <MediaLightbox v-model="zoom" :items="zoomable">
        <template #actions="{ item }"><button class="link-btn" @click="reveal(item.rel)">{{ t("common.showInExplorer") }}</button></template>
      </MediaLightbox>
    </template>
    <audio ref="player" @ended="sound = null" />
  </div>
</template>

<style scoped>
.page { flex: 1; overflow: auto; padding: 32px 40px; display: flex; flex-direction: column; gap: 20px; }
.h1 { font-size: 24px; font-weight: 600; letter-spacing: -0.015em; }
.drop-zone { padding: 18px; }
.free { display: flex; flex-direction: column; gap: 8px; }
.free-bar { display: flex; gap: 8px; align-items: center; }
.free-bar .input { flex: 1; max-width: 520px; }
.free-list { display: flex; flex-direction: column; border: 1px solid var(--line-soft); border-radius: 6px; padding: 0 12px; max-height: 420px; overflow: auto; }
.free-row { display: grid; grid-template-columns: 40px minmax(0, 1.6fr) minmax(0, 1fr) 110px 60px 150px; gap: 14px; align-items: center; padding: 7px 0; border-top: 1px solid var(--line-soft); font-size: 13.5px; }
.free-row:first-child { border-top: 0; }
.free-row .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.license { font-size: 11.5px; padding: 2px 6px; border-radius: 4px; border: 1px solid var(--line-soft); text-align: center; white-space: nowrap; }
.license.credit { border-color: #D8C68E; background: #F4E9C8; color: var(--ink); }
.credit-line { color: var(--muted, #888); font-size: 12px; }
.table { display: flex; flex-direction: column; }
.row {
  display: grid; grid-template-columns: 72px minmax(0, 1fr) minmax(0, 1.6fr) 90px 120px minmax(0, 0.7fr) 70px; gap: 16px; align-items: center;
  padding: 8px 0; border-top: 1px solid var(--line-soft); font-size: 13.5px; cursor: pointer;
}
.row:hover:not(.head) { background: var(--bg-softer); }
.row.head { border-top: none; padding: 0 0 8px; cursor: default; }
.row.playing .name { font-weight: 500; }
.play {
  height: 40px; width: 72px; border: none; background: var(--bg-soft); color: var(--muted);
  font-size: 13px; cursor: pointer; display: flex; align-items: center; justify-content: center;
}
.row:hover .play, .row.playing .play { background: var(--ink); color: #fff; }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.r { text-align: right; }
.dur { font-size: 12px; }
.desc {
  min-width: 0; height: 30px; padding: 0 8px; border: 1px solid transparent; border-radius: 4px;
  background: transparent; font-size: 13px; color: var(--muted); text-overflow: ellipsis;
}
.desc:hover { border-color: var(--line-strong); background: #fff; }
.desc:focus { color: var(--ink); background: #fff; }
.desc::placeholder { color: var(--off); }
.gain { display: flex; align-items: center; gap: 4px; font-size: 12px; color: var(--muted); }
.gain .desc { width: 52px; text-align: right; }
.hint { font-size: 13.5px; }
.transitions { display: flex; flex-direction: column; gap: 16px; }
.anim-layout { display: flex; gap: 32px; align-items: flex-start; }
/* la liste des kits reste visible pendant qu'on fait défiler les cartes */
.sources { position: sticky; top: 0; width: 200px; flex: none; display: flex; flex-direction: column; gap: 2px; }
.sources-head { padding: 14px 10px 6px; }
.source {
  display: flex; align-items: baseline; gap: 8px; padding: 7px 10px; border: none; border-radius: 4px;
  background: none; font-size: 13.5px; color: var(--muted); text-align: left; cursor: pointer;
}
.source:hover { background: var(--bg-softer); color: var(--ink); }
.source.on { background: var(--bg-soft); color: var(--ink); font-weight: 500; }
.source-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.source .n { font-size: 11.5px; color: var(--faint); font-variant-numeric: tabular-nums; }
.anim-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 20px; }
.anim-group { display: flex; flex-direction: column; gap: 12px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 24px; }
.anim-card { display: flex; flex-direction: column; gap: 8px; }
.anim-meta { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.anim-name { font-size: 14px; font-weight: 600; }
.anim-name::first-letter { text-transform: uppercase; }
.anim-desc { font-size: 13px; line-height: 1.45; }
.nothing { padding: 14px 0; border-top: 1px solid var(--line-soft); font-size: 13.5px; color: var(--faint); }
</style>
