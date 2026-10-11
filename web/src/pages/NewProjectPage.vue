<script setup lang="ts">
/** Nouveau projet (à partir d'une idée ou d'une vidéo déjà tournée), ou modification du brief. */
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import Seg from "../components/Seg.vue";
import { mmss } from "../lib/format";
import { toast } from "../lib/toast";
import { droppedFiles, upload } from "../lib/upload";
import { DURATIONS } from "../project/steps";
import { createProject, flush, open, receive, store, update } from "../project/store";
import type { Brief, Project } from "../project/types";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const editId = computed(() => (typeof route.params.pid === "string" ? route.params.pid : null));

type Mode = "idea" | "video";
const mode = ref<Mode>("idea");
const form = reactive({ idea: "", dir: "", links: [] as string[], link: "", notes: "", name: "", dur: "10–20 min" as string });
const error = ref(false);
const busy = ref(false);

// vidéo déjà tournée : choisie ici, envoyée une fois le projet créé
const video = ref<File | null>(null);
const videoDuration = ref<number | null>(null);
const uploadPct = ref<number | null>(null);
const over = ref(false);
const fileInput = ref<HTMLInputElement>();

watch(editId, async (id) => {
  if (!id) return;
  await open(id);
  const p = store.project!;
  Object.assign(form, { ...p.brief, links: [...p.brief.links], link: "", name: p.title });
}, { immediate: true });

const isEdit = computed(() => !!editId.value);
const videoMode = computed(() => mode.value === "video" && !isEdit.value);

function deduce(idea: string): string {
  const first = idea.trim().split(/[.:!?\n]/)[0].trim();
  if (!first) return "";
  const c = first.length > 60 ? first.slice(0, 60).replace(/\s+\S*$/, "") + "…" : first;
  return c.charAt(0).toUpperCase() + c.slice(1);
}

const namePlaceholder = computed(() => videoMode.value
  ? (video.value?.name.replace(/\.[^.]+$/, "") || t("brief.videoName"))
  : deduce(form.idea) || t("brief.nameFromIdea"));
const nameHint = computed(() => {
  if (form.name.trim() || videoMode.value) return "";
  const d = deduce(form.idea);
  return d ? t("brief.nameWillBe", { name: d }) : t("brief.nameOptional");
});
const canSubmit = computed(() => (videoMode.value ? !!video.value : !!form.idea.trim()));

function addLink() {
  const l = form.link.trim();
  if (!l) return;
  form.links.push(l);
  form.link = "";
}

function pickVideo(file: File | undefined) {
  if (!file) return;
  video.value = file;
  error.value = false;
  videoDuration.value = null;
  // la durée, lue par le navigateur sans attendre l'envoi
  const probe = document.createElement("video");
  probe.preload = "metadata";
  probe.src = URL.createObjectURL(file);
  probe.onloadedmetadata = () => {
    videoDuration.value = probe.duration;
    URL.revokeObjectURL(probe.src);
  };
}

function onDrop(e: DragEvent) {
  over.value = false;
  pickVideo(droppedFiles(e)[0]);
}

function brief(): Brief {
  const links = form.link.trim() ? [...form.links, form.link.trim()] : form.links;
  return { idea: form.idea.trim(), dir: form.dir.trim(), dur: form.dur, notes: form.notes.trim(), links };
}

async function submit() {
  if (!canSubmit.value) {
    error.value = true;
    return;
  }
  busy.value = true;
  try {
    if (isEdit.value) {
      update({ brief: brief(), title: form.name.trim() || deduce(form.idea) });
      await flush();
      toast(t("brief.updated"));
      router.push(`/p/${editId.value}/angle`);
    } else if (videoMode.value) {
      const p = await createProject({ mode: "video", title: form.name.trim() || namePlaceholder.value, brief: { dur: form.dur } });
      uploadPct.value = 0;
      receive(await upload<Project>(`/api/projects/${p.id}/source/upload`, [video.value!], "file", {},
        (f) => (uploadPct.value = Math.round(f * 100))));
      toast(t("brief.created"));
      router.push(`/p/${p.id}/transcript`);
    } else {
      const p = await createProject({ mode: "idea", title: form.name.trim(), brief: brief() });
      toast(t("brief.created"));
      router.push(`/p/${p.id}/angle`);
    }
  } catch (e) {
    toast((e as Error).message, true);
  } finally {
    busy.value = false;
    uploadPct.value = null;
  }
}

function cancel() {
  router.push(isEdit.value ? `/p/${editId.value}/angle` : "/");
}
</script>

<template>
  <div class="page">
    <div class="form">
      <div class="intro">
        <span class="h1">{{ isEdit ? t("brief.editTitle") : t("brief.newTitle") }}</span>
        <span class="muted">{{ videoMode ? t("brief.introVideo") : t("brief.introIdea") }}</span>
      </div>

      <Seg v-if="!isEdit" v-model="mode" :options="[['idea', t('brief.modeIdea')], ['video', t('brief.modeVideo')]]" />

      <div v-if="videoMode" class="field">
        <label>{{ t("brief.video") }} <span class="req">*</span></label>
        <input ref="fileInput" type="file" accept="video/*,.mov,.mp4,.mxf,.mkv" hidden @change="pickVideo(($event.target as HTMLInputElement).files?.[0])">
        <div v-if="uploadPct != null" class="video-up">
          <span class="mono">{{ video?.name }} · {{ uploadPct }} %</span>
          <div class="progress"><div :style="{ width: uploadPct + '%' }" /></div>
        </div>
        <div v-else-if="video" class="video-done">
          <span class="mono name">{{ video.name }}</span>
          <span class="muted">{{ videoDuration != null ? mmss(videoDuration) : "" }}</span>
          <button class="x-btn" @click="video = null">×</button>
        </div>
        <div v-else class="video-pick" :class="{ over, err: error }" @click="fileInput?.click()"
          @dragover.prevent="over = true" @dragleave="over = false" @drop.prevent="onDrop">
          <span class="big">{{ t("brief.dropVideo") }}</span>
          <span class="muted small">{{ t("brief.videoHint") }}</span>
        </div>
        <span v-if="error" class="err-text">{{ t("brief.videoRequired") }}</span>
      </div>

      <template v-else>
        <div class="field">
          <label>{{ t("brief.idea") }} <span class="req">*</span></label>
          <textarea v-model="form.idea" class="textarea idea" :class="{ err: error }" :placeholder="t('brief.ideaPlaceholder')"
            @input="error = false" />
          <span v-if="error" class="err-text">{{ t("brief.ideaRequired") }}</span>
        </div>
        <div class="field">
          <label>{{ t("brief.direction") }}</label>
          <textarea v-model="form.dir" class="textarea" :placeholder="t('brief.directionPlaceholder')" />
        </div>
        <div class="field">
          <label>{{ t("brief.links") }}</label>
          <div v-if="form.links.length" class="links">
            <div v-for="(l, i) in form.links" :key="i" class="link">
              <span class="type">{{ /^https?:/.test(l) ? t("brief.link") : t("brief.note") }}</span>
              <span class="l">{{ l }}</span>
              <button class="x-btn" @click="form.links.splice(i, 1)">×</button>
            </div>
          </div>
          <div class="row">
            <input v-model="form.link" class="input" :placeholder="t('brief.linkPlaceholder')" @keydown.enter="addLink">
            <button class="btn lg" @click="addLink">{{ t("common.add") }}</button>
          </div>
        </div>
        <div class="field">
          <label>{{ t("brief.notes") }}</label>
          <textarea v-model="form.notes" class="textarea" :placeholder="t('brief.notesPlaceholder')" />
        </div>
      </template>

      <div class="field">
        <label>{{ t("brief.name") }}</label>
        <input v-model="form.name" class="input name-input" :placeholder="namePlaceholder">
        <span v-if="nameHint" class="hint">{{ nameHint }}</span>
      </div>

      <div v-if="!videoMode" class="field">
        <label>{{ t("brief.targetDuration") }}</label>
        <Seg v-model="form.dur" :options="DURATIONS" />
      </div>

      <div class="submit">
        <button class="btn xl" :class="canSubmit ? 'red' : 'off'" :disabled="busy" @click="submit">
          {{ isEdit ? t("brief.saveBrief") : busy ? t("brief.creating") : t("brief.create") }}
        </button>
        <button class="btn xl cancel" @click="cancel">{{ t("common.cancel") }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { flex: 1; overflow: auto; padding: 32px 40px 56px; }
.form { max-width: 720px; display: flex; flex-direction: column; gap: 26px; }
.intro { display: flex; flex-direction: column; gap: 6px; font-size: 14px; line-height: 1.5; }
.h1 { font-size: 26px; font-weight: 600; letter-spacing: -0.015em; }
.field { display: flex; flex-direction: column; gap: 8px; }
.field label { font-size: 13.5px; font-weight: 600; }
.req { color: var(--red); }
.textarea { min-height: 76px; font-size: 14.5px; }
.textarea.idea { min-height: 96px; font-size: 15px; }
.textarea.err, .video-pick.err { border-color: var(--red); }
.err-text { font-size: 12.5px; color: var(--red-dark); }
.hint { font-size: 12.5px; color: var(--faint); }
.name-input { height: 42px; font-size: 15px; }
.row { display: flex; gap: 6px; }
.row .input { flex: 1; height: 40px; }
.links { display: flex; flex-direction: column; border: 1px solid var(--line); border-radius: 4px; }
.link { display: flex; align-items: center; gap: 12px; padding: 9px 12px; border-bottom: 1px solid var(--bg-soft); font-size: 13.5px; }
.link .type { font-family: var(--mono); font-size: 10.5px; color: var(--faint); width: 34px; }
.link .l { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.video-pick {
  display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 36px 20px;
  border: 1px dashed #A9AAA6; border-radius: 4px; cursor: pointer; text-align: center;
}
.video-pick:hover, .video-pick.over { background: var(--bg-softer); border-color: var(--ink); }
.video-pick .big { font-size: 14.5px; font-weight: 600; }
.small { font-size: 12.5px; }
.video-up { display: flex; flex-direction: column; gap: 8px; padding: 16px; border: 1px solid var(--line-strong); border-radius: 4px; font-size: 12.5px; color: var(--muted); }
.video-done { display: flex; align-items: center; gap: 12px; padding: 12px 14px; border: 1px solid var(--line-strong); border-radius: 4px; font-size: 12.5px; }
.video-done .name { flex: 1; }
.submit { display: flex; gap: 10px; padding-top: 8px; border-top: 1px solid var(--line-soft); }
.btn.off { background: var(--toggle-off); border-color: var(--toggle-off); color: #fff; }
.cancel { font-size: 14px; font-weight: 400; padding: 0 18px; }
</style>
