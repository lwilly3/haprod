<script setup lang="ts">
/**
 * Le style du projet : le design system avec lequel Daryl écrit les motions. Au départ, celui du kit ; on
 * peut en changer ici. Les motions écrits ensuite le prennent, ceux déjà faits gardent le leur (et leur rendu).
 */
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import Modal from "../../../components/Modal.vue";
import ThemeSwatch from "../../../components/ThemeSwatch.vue";
import { api, putJson } from "../../../lib/api";
import { toast } from "../../../lib/toast";

type Design = Record<string, string | number>;
interface StyleView { style: Design; kit: Design; presets: Design[] }

const props = defineProps<{ pid: string }>();
const { t } = useI18n();
const view = ref<StyleView | null>(null);
const open = ref(false);

onMounted(async () => {
  view.value = await api<StyleView>(`/api/projects/${props.pid}/montage/style`);
});

// le design system du kit en tête, puis les ambiances ; un choix est actif si tous ses réglages le sont
const options = computed(() => view.value
  ? [{ id: "kit", label: t("editing.style.kit"), theme: view.value.kit },
     ...view.value.presets.map((p) => ({ id: String(p.id), label: t(`library.design.presets.${p.id}`), theme: p }))]
  : []);
const active = (theme: Design) => !!view.value && Object.entries(theme)
  .every(([k, v]) => k === "id" || view.value!.style[k] === v);
const current = computed(() => options.value.find((o) => active(o.theme))?.label ?? t("editing.style.custom"));

async function pick(theme: Design) {
  try {
    view.value = await putJson<StyleView>(`/api/projects/${props.pid}/montage/style`, theme);
    open.value = false;
  } catch (e) {
    toast((e as Error).message, true);
  }
}
</script>

<template>
  <button v-if="view" class="btn sm current" :title="t('editing.style.title')" @click="open = true">
    <ThemeSwatch :theme="view.style" class="mini" />
    {{ t("editing.style.label") }} · {{ current }}
  </button>
  <Modal v-if="open && view" :title="t('editing.style.title')" width="560px" height="400px" @close="open = false">
    <p class="hint">{{ t("editing.style.hint") }}</p>
    <div class="list">
      <button v-for="o in options" :key="o.id" class="option" :class="{ active: active(o.theme) }" @click="pick(o.theme)">
        <ThemeSwatch :theme="o.theme" />
        <span>{{ o.label }}</span>
      </button>
    </div>
  </Modal>
</template>

<style scoped>
.current { display: inline-flex; align-items: center; gap: 8px; }
.mini { width: 26px; height: 18px; font-size: 9px; }
.mini :deep(i) { width: 5px; height: 5px; right: 2px; bottom: 2px; }
.hint { margin: 0 0 12px; font-size: 13px; color: var(--muted); }
.list { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.option { display: flex; align-items: center; gap: 10px; padding: 6px 10px 6px 6px; border: 1px solid var(--line); border-radius: 6px; background: none; font-size: 13px; color: var(--muted); cursor: pointer; text-align: left; }
.option:hover { border-color: var(--line-strong); }
.option.active { border-color: var(--ink); color: var(--ink); font-weight: 500; }
</style>
