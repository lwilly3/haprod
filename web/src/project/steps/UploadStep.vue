<script setup lang="ts">
/**
 * Upload : chaque vidéo (la longue, les shorts) s'envoie à part sur YouTube par l'API, avec sa
 * visibilité (ou sa date de publication). Une vidéo ne part que si ses vérifications passent :
 * vignette, titre, chapitres, test A/B, rendu à jour. L'API ne crée pas le test A/B : une fois la
 * vidéo longue envoyée, ses variantes B et C restent affichées pour les poser dans YouTube Studio.
 */
import { computed } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { usePref } from "../../lib/composables";
import { mmss } from "../../lib/format";
import { toast } from "../../lib/toast";
import { store } from "../store";
import type { Visibility } from "../types";
import { checkLabel, missing, thumbUrl, uploading, usePublish, VISIBILITY, type Video } from "./publish/usePublish";

const project = computed(() => store.project!);
const router = useRouter();
const { t } = useI18n();
const P = usePublish(project);
const selId = usePref<string>(`publish.sel.${project.value.id}`, "long");

const sent = computed(() => P.videos.value.filter((v) => v.upload?.status === "done").length);
const blocked = computed(() => P.videos.value.filter((v) => missing(v).length && v.upload?.status !== "done").length);
const allSent = computed(() => !!P.videos.value.length && sent.value === P.videos.value.length);

function fix(v: Video) {
  const bad = missing(v);
  if (!bad.length) return;
  selId.value = v.id;
  router.push(`/p/${project.value.id}/${bad[0].fix}`);
}

function state(v: Video): { label: string; tone: "" | "done" | "red" } {
  const u = v.upload;
  if (!u || u.status === "cancelled") return { label: "", tone: "" };
  if (u.status === "error") return { label: t("upload.error"), tone: "red" };
  if (u.status === "done") return { label: v.pub.vis === "scheduled" ? t("upload.scheduled") : t("upload.sent"), tone: "done" };
  return { label: u.status === "queued" ? t("upload.queued") : t("upload.sending", { n: Math.round(u.progress * 100) }), tone: "" };
}

const done = (v: Video) => v.upload?.status === "done";

// la vidéo longue envoyée avec un test A/B : ses variantes B et C restent à poser à la main
const abLeft = computed(() => {
  const v = P.videos.value.find((x) => x.kind === "long");
  if (!v || !done(v) || !v.meta.ab_on || !v.meta.ab?.length) return null;
  return {
    studio: v.upload?.video_id ? `https://studio.youtube.com/video/${v.upload.video_id}/edit` : null,
    variants: v.meta.ab.map((a, i) => ({ ...a, l: "BC"[i], img: thumbUrl(project.value, a.thumb) })),
  };
});
async function copyTitle(title: string) {
  await navigator.clipboard.writeText(title);
  toast(t("upload.ab.copied"));
}
const visLabel = (vis: Visibility) => { const key = VISIBILITY.find(([k]) => k === vis)?.[1]; return key ? t(key) : vis; };
</script>

<template>
  <div class="screen">
    <div v-if="P.account.value && !P.account.value.connected" class="banner">
      {{ t("upload.notConnected") }}
      <RouterLink to="/settings/services">{{ t("upload.connect") }}</RouterLink>
    </div>
    <div v-else-if="P.account.value?.channel" class="summary">
      <span>{{ t("upload.summary", { sent, n: P.videos.value.length }) }}{{ blocked ? t("upload.blocked", { n: blocked }) : "" }}</span>
      <span class="spacer" />
      <span class="mono faint small">{{ t("upload.onChannel", { channel: P.account.value.channel.title }) }}</span>
    </div>

    <div v-if="!P.data.value" class="eyebrow">{{ t("common.loading") }}</div>
    <template v-else>
      <div class="row head mono">
        <span /><span>{{ t("upload.col.video") }}</span><span>{{ t("upload.col.checks") }}</span><span>{{ t("upload.col.visibility") }}</span><span class="right">{{ t("upload.col.upload") }}</span>
      </div>
      <div v-for="v in P.videos.value" :key="v.id" class="row">
        <div class="th">
          <img v-if="v.kind === 'long' && thumbUrl(project, v.meta.thumb)" :src="thumbUrl(project, v.meta.thumb)!" alt="" class="img wide">
          <div v-else class="img hatch" :class="v.kind === 'long' ? 'wide' : 'tall'" />
        </div>
        <div class="vid">
          <span class="mono faint small">{{ v.name }} · {{ v.format }} · {{ mmss(v.duration) }}</span>
          <span class="title">{{ v.meta.title }}</span>
        </div>
        <div class="checks">
          <template v-if="done(v)"><span class="ok">—</span></template>
          <template v-else>
            <span :class="missing(v).length ? 'red' : 'ok'">{{ missing(v).length ? t("upload.toFix", { n: missing(v).length }) : t("upload.ready") }}</span>
            <button v-if="missing(v).length" class="fix" :title="t('upload.fix', { check: checkLabel(missing(v)[0].k) })" @click="fix(v)">
              {{ missing(v).map((c) => checkLabel(c.k)).join(", ") }}</button>
          </template>
        </div>
        <div class="vis">
          <span v-if="done(v) || uploading(v.upload)" class="small muted">{{ visLabel(v.pub.vis) }}{{ v.pub.vis === "scheduled" && v.pub.sched ? t("upload.schedAt", { date: v.pub.sched.split("T")[0], time: v.pub.sched.split("T")[1] ?? "" }) : "" }}</span>
          <template v-else>
            <select class="select" :value="v.pub.vis" @change="P.setPub(v.id, { vis: ($event.target as HTMLSelectElement).value as Visibility })">
              <option v-for="[k, label] in VISIBILITY" :key="k" :value="k">{{ t(label) }}</option>
            </select>
            <input v-if="v.pub.vis === 'scheduled'" type="datetime-local" class="input when" :value="v.pub.sched"
              @change="P.setPub(v.id, { sched: ($event.target as HTMLInputElement).value })">
          </template>
        </div>
        <div class="send">
          <template v-if="uploading(v.upload)">
            <span class="mono small">{{ state(v).label }}</span>
            <div class="track"><div :style="{ width: `${(v.upload?.progress ?? 0) * 100}%` }" /></div>
            <button class="link-btn small" @click="P.stop(v.id)">{{ t("common.stop") }}</button>
          </template>
          <template v-else-if="done(v)">
            <span class="mono small done">{{ state(v).label }}</span>
            <a v-if="v.upload?.url" :href="v.upload.url" target="_blank" rel="noopener" class="small">{{ t("upload.viewOnYoutube") }}</a>
            <span v-if="v.upload?.warning" class="small red" :title="v.upload.warning">{{ t("upload.thumbManual") }}</span>
          </template>
          <template v-else>
            <span v-if="state(v).tone === 'red'" class="small red" :title="v.upload?.error ?? ''">{{ t("upload.failed", { error: v.upload?.error }) }}</span>
            <button class="btn sm" :class="missing(v).length || !P.account.value?.connected ? '' : 'red'"
              :disabled="!!missing(v).length || !P.account.value?.connected" @click="P.start(v.id)">
              {{ v.pub.vis === "scheduled" ? t("upload.schedule") : state(v).tone === "red" ? t("common.retry") : t("common.send") }}</button>
          </template>
        </div>
      </div>

      <section v-if="abLeft" class="ab">
        <div class="ab-head">
          <span>{{ t("upload.ab.todo") }}</span>
          <span class="spacer" />
          <a v-if="abLeft.studio" :href="abLeft.studio" target="_blank" rel="noopener" class="small">{{ t("upload.ab.openStudio") }}</a>
        </div>
        <div v-for="a in abLeft.variants" :key="a.l" class="ab-row">
          <span class="badge mono">{{ a.l }}</span>
          <a v-if="a.img" :href="a.img" download><img :src="a.img" alt="" class="img wide" :title="t('upload.ab.download')"></a>
          <div v-else class="img wide hatch" />
          <span class="title">{{ a.title }}</span>
          <button class="link-btn small" @click="copyTitle(a.title)">{{ t("upload.ab.copy") }}</button>
          <a v-if="a.img" :href="a.img" download class="small">{{ t("upload.ab.download") }}</a>
        </div>
      </section>

      <p v-if="allSent" class="end">{{ t("upload.allSent") }}</p>
      <p v-else-if="P.account.value?.connected" class="note">
        {{ t("upload.auditNote") }}
      </p>
    </template>
  </div>
</template>

<style scoped>
.screen { padding: 20px 32px 40px; display: flex; flex-direction: column; gap: 14px; max-width: 1080px; }
.banner { padding: 12px 14px; border: 1px solid var(--red); border-radius: 4px; font-size: 13.5px; color: var(--red-dark); display: flex; gap: 12px; }
.summary { display: flex; align-items: center; gap: 12px; font-size: 13.5px; color: var(--muted); }
.spacer { flex: 1; }
.small { font-size: 12px; }
.red { color: var(--red-ink); }
.row {
  display: grid; grid-template-columns: 72px minmax(0, 1fr) 150px 180px 170px; gap: 14px;
  padding: 12px 0; border-bottom: 1px solid var(--line-soft); align-items: center;
}
.row.head { padding: 8px 0; font-size: 10.5px; color: var(--faint); text-transform: uppercase; letter-spacing: .05em; border-bottom-color: var(--line); }
.right { text-align: right; }
.th { display: flex; justify-content: center; }
.img { height: 40px; border-radius: 2px; object-fit: cover; display: block; }
.img.wide { width: 71px; }
.img.tall { width: 22px; }
.vid { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.title { font-size: 14px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.checks { display: flex; flex-direction: column; gap: 2px; font-size: 13px; min-width: 0; }
.ok { color: var(--ink); }
.fix {
  border: none; background: none; padding: 0; text-align: left; font-size: 12.5px; color: var(--red-ink); text-decoration: underline;
  cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.vis { display: flex; flex-direction: column; gap: 6px; }
.select { height: 30px; border: 1px solid var(--line-strong); border-radius: 4px; background: #fff; font-size: 13px; padding: 0 6px; }
.when { height: 30px; font-size: 12.5px; padding: 0 6px; }
.send { display: flex; flex-direction: column; gap: 6px; align-items: flex-end; text-align: right; }
.send .done { color: var(--ink); }
.track { height: 3px; width: 100%; background: var(--line-soft); }
.track > div { height: 3px; background: var(--red); transition: width .4s; }
.ab { display: flex; flex-direction: column; gap: 8px; padding: 14px 16px; border: 1px solid var(--red); border-radius: 4px; }
.ab-head { display: flex; align-items: baseline; gap: 12px; font-size: 13.5px; color: var(--red-dark); }
.ab-row { display: grid; grid-template-columns: 22px 71px minmax(0, 1fr) auto auto; gap: 14px; align-items: center; }
.badge { width: 20px; height: 20px; border-radius: 2px; background: var(--red); color: #fff; font-size: 11px; font-weight: 700; display: grid; place-items: center; }
.end, .note { margin: 6px 0 0; font-size: 13.5px; color: var(--muted); line-height: 1.5; }
.note { font-size: 12.5px; color: var(--muted-2); }
</style>
