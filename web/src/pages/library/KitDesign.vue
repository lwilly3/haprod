<script setup lang="ts">
/**
 * Le design system du kit : couleurs, arrondi, polices, matière. Chaque réglage régénère style.css, que
 * toutes les animations du kit lisent : aucune animation n'est à refaire.
 * Point de départ au choix : une ambiance toute faite, ou les couleurs d'une image de tournage.
 */
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { api, putJson } from "../../lib/api";
import { themesFromImage } from "../../lib/palette";
import { toast } from "../../lib/toast";

type Design = Record<string, string | number>;
interface DesignView { design: Design; defaults: Design; colors: string[]; fonts: string[]; textures: string[]; presets: Design[] }

const emit = defineEmits<{ saved: [] }>();
const { t } = useI18n();
const view = ref<DesignView | null>(null);

onMounted(async () => {
  view.value = await api<DesignView>("/api/projects/library/kit/design");
});

async function save(values: Design) {
  try {
    view.value = await putJson<DesignView>("/api/projects/library/kit/design", values);
    emit("saved");
  } catch (e) {
    toast((e as Error).message, true);
  }
}

const set = (key: string, value: string | number) => save({ [key]: value });
const changed = (key: string) => view.value && view.value.design[key] !== view.value.defaults[key];

// la charte de base en tête des ambiances ; une ambiance est active si tous ses réglages le sont
const presets = computed<Design[]>(() => view.value ? [{ ...view.value.defaults, id: "base" }, ...view.value.presets] : []);
const swatch = (p: Design) => ({
  background: String(p.card), borderColor: String(p.line), color: String(p.text),
  borderRadius: p.radius === undefined ? undefined : `${Math.min(Number(p.radius), 12)}px`,
});
const active = (values: Design) => !!view.value && Object.entries(values)
  .every(([k, v]) => k === "id" || view.value!.design[k] === v);

// les thèmes tirés d'une photo : proposés, appliqués seulement quand on en choisit un
const photo = ref<HTMLInputElement | null>(null);
const fromPhoto = ref<Design[]>([]);
async function readPhoto(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  try {
    fromPhoto.value = await themesFromImage(file);
  } catch {
    toast(t("library.design.photoFailed"), true);
  }
}
</script>

<template>
  <div v-if="view" class="design">
    <div class="head">
      <span class="eyebrow">{{ t("library.design.title") }}</span>
      <span class="muted hint">{{ t("library.design.hint") }}</span>
      <span class="spacer" />
    </div>
    <div class="themes">
      <button v-for="p in presets" :key="p.id" class="theme" :class="{ active: active(p) }" @click="save(p)">
        <span class="swatch" :style="swatch(p)">
          Aa<i :style="{ background: String(p.accent) }" />
        </span>
        <span>{{ t(`library.design.presets.${p.id}`) }}</span>
      </button>
      <button class="theme photo" @click="photo?.click()">
        <span class="swatch add">+</span>
        <span>{{ t("library.design.fromPhoto") }}</span>
      </button>
      <input ref="photo" type="file" accept="image/*" hidden @change="readPhoto">
    </div>
    <div v-if="fromPhoto.length" class="themes">
      <span class="muted hint">{{ t("library.design.photoHint") }}</span>
      <button v-for="(p, i) in fromPhoto" :key="i" class="theme" :class="{ active: active(p) }" @click="save(p)">
        <span class="swatch" :style="swatch(p)">
          Aa<i :style="{ background: String(p.accent) }" />
        </span>
        <span>{{ t("library.design.photoTheme", { n: i + 1 }) }}</span>
      </button>
    </div>
    <div class="fields">
      <label v-for="k in view.colors" :key="k" class="field" :class="{ changed: changed(k) }">
        <input type="color" :value="view.design[k]" @change="set(k, ($event.target as HTMLInputElement).value)">
        <span>{{ t(`library.design.tokens.${k}`) }}</span>
      </label>
      <label class="field" :class="{ changed: changed('radius') }">
        <input type="range" min="0" max="48" :value="view.design.radius" @change="set('radius', Number(($event.target as HTMLInputElement).value))">
        <span>{{ t("library.design.tokens.radius") }} · {{ view.design.radius }} px</span>
      </label>
      <label v-for="k in view.fonts" :key="k" class="field font" :class="{ changed: changed(k) }">
        <input class="input" :value="view.design[k]" list="kit-fonts" @change="set(k, ($event.target as HTMLInputElement).value)">
        <span>{{ t(`library.design.tokens.${k}`) }}</span>
      </label>
      <label class="field" :class="{ changed: changed('texture') }">
        <select class="input" :value="view.design.texture" @change="set('texture', ($event.target as HTMLSelectElement).value)">
          <option v-for="k in view.textures" :key="k" :value="k">{{ t(`library.design.textures.${k}`) }}</option>
        </select>
        <span>{{ t("library.design.tokens.texture") }}</span>
      </label>
    </div>
    <!-- des polices Google courantes ; n'importe quel nom de Google Fonts marche -->
    <datalist id="kit-fonts">
      <option v-for="f in ['Space Grotesk', 'Inter', 'Inter Tight', 'Manrope', 'DM Sans', 'Outfit', 'Sora', 'Poppins', 'Montserrat', 'Archivo', 'Bricolage Grotesque', 'Instrument Serif', 'Fraunces', 'JetBrains Mono', 'IBM Plex Mono', 'Space Mono', 'DM Mono']" :key="f" :value="f" />
    </datalist>
  </div>
</template>

<style scoped>
.design { display: flex; flex-direction: column; gap: 12px; padding: 16px; border: 1px solid var(--line); border-radius: 6px; }
.head { display: flex; align-items: baseline; gap: 12px; }
.hint { font-size: 13px; }
.themes { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.theme { display: flex; align-items: center; gap: 8px; padding: 4px 10px 4px 4px; border: 1px solid var(--line); border-radius: 6px; background: none; font-size: 13px; color: var(--muted); cursor: pointer; }
.theme:hover { border-color: var(--line-strong); }
.theme.active { border-color: var(--ink); color: var(--ink); font-weight: 500; }
.swatch { position: relative; display: grid; place-items: center; width: 44px; height: 30px; border: 1px solid; font-size: 13px; font-weight: 600; }
.swatch i { position: absolute; right: 4px; bottom: 4px; width: 8px; height: 8px; border-radius: 50%; }
.swatch.add { border: 1px dashed var(--line-strong); border-radius: 4px; color: var(--muted); font-size: 16px; font-weight: 400; }
.fields { display: flex; flex-wrap: wrap; gap: 10px 22px; align-items: center; }
.field { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); cursor: pointer; }
.field.changed span { color: var(--ink); font-weight: 500; }
.field input[type="color"] { width: 30px; height: 30px; padding: 0; border: 1px solid var(--line-strong); border-radius: 4px; background: none; cursor: pointer; }
.field input[type="range"] { width: 110px; }
.field.font .input { width: 170px; height: 32px; }
.field select.input { height: 32px; }
</style>
