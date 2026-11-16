<script setup lang="ts">
/**
 * Réglages, en onglets : le profil de la chaîne (donné à Claude dans toutes les étapes d'écriture),
 * les services (publication YouTube, transcription) et l'interface.
 */
import { computed, onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import Seg from "../components/Seg.vue";
import { LOCALES, setLocale, type Locale } from "../i18n";
import { api, del, post, putJson } from "../lib/api";
import { usePolling, usePref } from "../lib/composables";
import { setChannelLanguage } from "../lib/content";
import { languageName } from "../lib/format";
import { toast } from "../lib/toast";
import { upload } from "../lib/upload";

type Key = "name" | "identity" | "pitch" | "audience" | "tone" | "formats" | "avoid" | "videos";
type YoutubeChannel = { id: string; title: string; handle: string; url: string; thumbnail: string | null; followers: number | null };
type Found = YoutubeChannel & { description: string };
type Channel = Record<Key, string> & { youtube: YoutubeChannel | null; language: string };

/** Les langues de chaîne que les prompts savent nommer (settings/service.py, LANGUAGES). */
const CHANNEL_LANGUAGES = ["fr", "en", "es", "de", "it", "pt"] as const;

const FIELDS: { key: Exclude<Key, "name">; rows?: number }[] = [
  { key: "identity" }, { key: "pitch" }, { key: "audience" }, { key: "tone" }, { key: "formats" }, { key: "avoid" },
  { key: "videos", rows: 8 },
];

const { t, locale } = useI18n();

/** L'onglet est dans l'URL (/settings/services…) : on peut y renvoyer depuis une autre page. */
const TABS = ["channel", "publish", "services", "interface"] as const;
type Tab = (typeof TABS)[number];
const route = useRoute();
const router = useRouter();
const tab = computed<Tab>(() => (TABS as readonly string[]).includes(route.params.tab as string) ? route.params.tab as Tab : "channel");
const selectTab = (k: Tab) => router.replace(k === "channel" ? "/settings" : `/settings/${k}`);

/** La langue de l'interface : une préférence du navigateur, pas du profil de la chaîne. */
const uiLocale = computed<Locale>({ get: () => locale.value as Locale, set: (l) => setLocale(l) });
const localeOptions = Object.entries(LOCALES) as [Locale, string][];
const channelLanguages = computed(() => CHANNEL_LANGUAGES.map((c) => [c, languageName(c) ?? c] as [string, string]));

const form = reactive({ youtube: null } as Channel);
const saved = ref("");
const loaded = ref(false);
const busy = ref(false);

const dirty = computed(() => loaded.value && JSON.stringify(form) !== saved.value);

function receive(c: Channel) {
  Object.assign(form, c);
  saved.value = JSON.stringify(form);
}

onMounted(async () => {
  try {
    receive(await api<Channel>("/api/settings/channel"));
    loaded.value = true;
  } catch (e) {
    toast((e as Error).message, true);
  }
});

async function save() {
  busy.value = true;
  try {
    receive(await putJson<Channel>("/api/settings/channel", form));
    setChannelLanguage(form.language);
    toast(t("settings.saved"));
  } catch (e) {
    toast((e as Error).message, true);
  } finally {
    busy.value = false;
  }
}

// --- Recherche de la chaîne sur YouTube (yt-dlp côté API : ~2 s par recherche) ---

const results = ref<Found[]>([]);
const searching = ref(false);
const searchError = ref("");
const open = ref(false);
let timer: ReturnType<typeof setTimeout> | undefined;
let seq = 0;

function onNameInput() {
  clearTimeout(timer);
  const q = form.name.trim();
  if (q.length < 2) {
    seq++;
    results.value = [];
    searching.value = false;
    open.value = false;
    return;
  }
  timer = setTimeout(() => search(q), 450);
}

async function search(q: string) {
  const mine = ++seq;
  searching.value = true;
  searchError.value = "";
  open.value = true;
  try {
    const found = await api<Found[]>(`/api/settings/channels/search?q=${encodeURIComponent(q)}`);
    if (mine === seq) results.value = found;
  } catch (e) {
    if (mine === seq) searchError.value = (e as Error).message;
  } finally {
    if (mine === seq) searching.value = false;
  }
}

function pick(c: Found) {
  const { description: _, ...youtube } = c;
  form.youtube = youtube;
  form.name = c.title;
  // la description de la chaîne : un point de départ pour le positionnement, s'il est vide
  if (!form.pitch.trim() && c.description.trim()) form.pitch = c.description.trim();
  seq++;
  open.value = false;
  results.value = [];
}

function closeSoon() {
  // laisse le temps au clic sur un résultat d'arriver
  setTimeout(() => (open.value = false), 150);
}

// --- Description par défaut : le bloc commun à toutes les descriptions (liens, outils, réseaux) ---

const publish = reactive({ description: "" });
const publishSaved = ref<string | null>(null);
const publishBusy = ref(false);
const publishDirty = computed(() => publishSaved.value !== null && publish.description !== publishSaved.value);

onMounted(async () => {
  try {
    Object.assign(publish, await api<typeof publish>("/api/settings/publish"));
    publishSaved.value = publish.description;
  } catch (e) {
    toast((e as Error).message, true);
  }
});

async function savePublish() {
  publishBusy.value = true;
  try {
    Object.assign(publish, await putJson<typeof publish>("/api/settings/publish", publish));
    publishSaved.value = publish.description;
    toast(t("settings.saved"));
  } catch (e) {
    toast((e as Error).message, true);
  } finally {
    publishBusy.value = false;
  }
}

// --- Compte YouTube : publication par l'API (étape Upload) ---

type YoutubeAccount = {
  client: boolean; connected: boolean; connecting: boolean; error: string | null;
  channel: { id: string; title: string; thumbnail: string | null } | null;
};
const account = ref<YoutubeAccount | null>(null);
const clientInput = ref<HTMLInputElement>();

usePolling(async () => {
  account.value = await api<YoutubeAccount>("/api/settings/youtube");
  return account.value.connecting ? 1500 : 15000;
});

async function youtube(run: () => Promise<YoutubeAccount>) {
  try {
    account.value = await run();
  } catch (e) {
    toast((e as Error).message, true);
  }
}
async function sendClient(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0];
  (e.target as HTMLInputElement).value = "";
  if (file) await youtube(() => upload<YoutubeAccount>("/api/settings/youtube/client", [file], "file"));
}
const connectYoutube = () => youtube(() => post<YoutubeAccount>("/api/settings/youtube/connect"));
const cancelYoutube = () => youtube(() => post<YoutubeAccount>("/api/settings/youtube/cancel"));
const disconnectYoutube = () => youtube(() => del<YoutubeAccount>("/api/settings/youtube"));

// --- compte Claude : celui de Claude Code, connecté dans le navigateur ---

type ClaudeAccount = {
  loggedIn: boolean; authMethod?: string | null; email?: string | null;
  connecting: boolean; url: string | null; error: string | null;
};
const claudeAccount = ref<ClaudeAccount | null>(null);
const claudeCode = ref("");

usePolling(async () => {
  claudeAccount.value = await api<ClaudeAccount>("/api/settings/claude/account");
  return claudeAccount.value.connecting ? 1500 : 15000;
});

async function claude(run: () => Promise<ClaudeAccount>) {
  try {
    claudeAccount.value = await run();
  } catch (e) {
    toast((e as Error).message, true);
  }
}
const connectClaude = () => claude(() => post<ClaudeAccount>("/api/settings/claude/login"));
const cancelClaude = () => claude(() => post<ClaudeAccount>("/api/settings/claude/cancel"));
async function sendClaudeCode() {
  await claude(() => post<ClaudeAccount>("/api/settings/claude/code", { code: claudeCode.value }));
  claudeCode.value = "";
}
function disconnectClaude() {
  if (confirm(t("settings.claudeDisconnectConfirm"))) claude(() => del<ClaudeAccount>("/api/settings/claude/account"));
}

// --- compte ChatGPT : celui de Codex, qui génère les miniatures par l'abonnement ---

type ChatgptAccount = { installed: boolean; loggedIn: boolean; connecting: boolean; url: string | null; error: string | null };
const chatgptAccount = ref<ChatgptAccount | null>(null);

usePolling(async () => {
  chatgptAccount.value = await api<ChatgptAccount>("/api/settings/chatgpt/account");
  return chatgptAccount.value.connecting ? 1500 : 15000;
});

async function chatgpt(run: () => Promise<ChatgptAccount>) {
  try {
    chatgptAccount.value = await run();
  } catch (e) {
    toast((e as Error).message, true);
  }
}
const connectChatgpt = () => chatgpt(() => post<ChatgptAccount>("/api/settings/chatgpt/login"));
const cancelChatgpt = () => chatgpt(() => post<ChatgptAccount>("/api/settings/chatgpt/cancel"));
function disconnectChatgpt() {
  if (confirm(t("settings.chatgptDisconnectConfirm"))) chatgpt(() => del<ChatgptAccount>("/api/settings/chatgpt/account"));
}

// --- modèle de Claude : un choix pour les tours courts, un pour le travail d'agent ---

type ClaudeLevel = "light" | "heavy";
type ClaudeModels = Record<ClaudeLevel, string>;

const claudeModels = ref<ClaudeModels | null>(null);
const claudeOptions = computed(() => ["", "haiku", "sonnet", "opus"]
  .map((m) => [m, m ? t(`settings.claudeModels.${m}`) : t("settings.claudeDefault")] as [string, string]));

async function setClaudeModel(level: ClaudeLevel, model: string) {
  try {
    claudeModels.value = await putJson<ClaudeModels>("/api/settings/claude", { ...claudeModels.value, [level]: model });
  } catch (err) {
    toast((err as Error).message, true);
  }
}

onMounted(async () => {
  try {
    claudeModels.value = await api<ClaudeModels>("/api/settings/claude");
  } catch (e) {
    toast((e as Error).message, true);
  }
});

// --- moteur de transcription : Whisper en local, ou une API (clé gardée côté serveur) ---

type Engine = "whisper" | "elevenlabs" | "gladia";
type Transcription = { engine: Engine; keys: Partial<Record<Engine, string>> };

const transcription = ref<Transcription | null>(null);
/** Le moteur affiché : un moteur sans clé s'affiche le temps de la saisir, sans être enregistré. */
const engineShown = ref<Engine>("whisper");
const engineKey = ref("");
const engineOptions = computed(() => (["whisper", "elevenlabs", "gladia"] as Engine[])
  .map((e) => [e, t(`settings.engines.${e}.label`)] as [Engine, string]));
const engine = computed<Engine>({
  get: () => engineShown.value,
  set: (e) => {
    engineShown.value = e;
    engineKey.value = "";
    if (e === "whisper" || transcription.value?.keys[e]) saveEngine(e);
  },
});

async function saveEngine(e: Engine, key = "") {
  try {
    transcription.value = await putJson<Transcription>("/api/settings/transcription", { engine: e, key });
    engineShown.value = transcription.value.engine;
    engineKey.value = "";
  } catch (err) {
    toast((err as Error).message, true);
  }
}

async function forgetKey(e: Engine) {
  transcription.value = await del<Transcription>(`/api/settings/transcription/keys/${e}`);
  engineShown.value = e;
}

onMounted(async () => {
  try {
    transcription.value = await api<Transcription>("/api/settings/transcription");
    engineShown.value = transcription.value.engine;
  } catch (e) {
    toast((e as Error).message, true);
  }
});

// --- ytwatch et l'analyse de la chaîne par Claude ---

type Ytwatch = { connected: boolean; url: string; token_hint: string };
type Proposal = Partial<Record<Key, string>> & { message?: string };
type Analysis = { id: string; status: string; error: string | null; activity: string | null; result: Proposal | null };

const ytwatch = ref<Ytwatch | null>(null);
const token = ref("");
const analysis = ref<Analysis | null>(null);
// les propositions déjà acceptées ou écartées, par analyse
const handled = usePref<Record<string, string[]>>("settings.handled", {});

const running = computed(() => !!analysis.value && !["done", "error", "cancelled"].includes(analysis.value.status));

function proposal(key: Key | "message"): string {
  const a = analysis.value;
  if (!a || a.status !== "done" || !a.result) return "";
  const text = (a.result[key] ?? "").trim();
  if (!text || (handled.value[a.id] ?? []).includes(key)) return "";
  return key !== "message" && text === form[key].trim() ? "" : text;
}

function settle(key: Key | "message", accept: boolean) {
  const a = analysis.value!;
  if (accept && key !== "message") form[key] = a.result![key]!.trim();
  handled.value = { [a.id]: [...(handled.value[a.id] ?? []), key] };
}

onMounted(async () => {
  try {
    ytwatch.value = await api<Ytwatch>("/api/settings/ytwatch");
  } catch (e) {
    toast((e as Error).message, true);
  }
});

usePolling(async () => {
  analysis.value = await api<Analysis | null>("/api/settings/analysis");
  return running.value ? 1500 : 10000;
});

async function connect() {
  try {
    ytwatch.value = await putJson<Ytwatch>("/api/settings/ytwatch", { url: ytwatch.value?.url ?? "", token: token.value });
    token.value = "";
    toast(t("settings.ytwatchConnected"));
  } catch (e) {
    toast((e as Error).message, true);
  }
}

async function disconnect() {
  ytwatch.value = await del<Ytwatch>("/api/settings/ytwatch");
}

async function analyse() {
  try {
    analysis.value = await post<Analysis>("/api/settings/analysis");
  } catch (e) {
    toast((e as Error).message, true);
  }
}

async function cancelAnalysis() {
  analysis.value = await post<Analysis>("/api/settings/analysis/cancel");
}

function followers(n: number | null): string {
  if (n == null) return "";
  const v = n >= 1e6 ? `${(n / 1e6).toLocaleString(locale.value, { maximumFractionDigits: 1 })} M`
    : n >= 1e3 ? `${(n / 1e3).toLocaleString(locale.value, { maximumFractionDigits: 1 })} k` : String(n);
  return t("settings.followers", { v }, n);
}
</script>

<template>
  <div class="page">
    <div class="form">
      <span class="h1">{{ t("settings.title") }}</span>
      <div class="tabs">
        <button v-for="k in TABS" :key="k" :class="{ on: k === tab }" @click="selectTab(k)">
          {{ t(`settings.tabs.${k}`) }}<span v-if="k === 'channel' ? dirty : k === 'publish' && publishDirty" class="dot" :title="t('settings.unsaved')" />
        </button>
      </div>

      <template v-if="tab === 'channel'">
        <span class="muted intro">{{ t("settings.intro") }}</span>
        <template v-if="loaded">
          <div class="field">
            <label>{{ t("settings.channel") }}</label>
            <span class="hint">{{ t("settings.channelHint") }}</span>
            <div class="search">
              <input v-model="form.name" class="input name-input" :placeholder="t('settings.channelPlaceholder')"
                @input="onNameInput" @focus="results.length && (open = true)" @blur="closeSoon" @keydown.esc="open = false">
              <span v-if="searching" class="spinner in-input" />
              <div v-if="open && (searching || searchError || results.length || form.name.trim().length >= 2)" class="results">
                <div v-if="searchError" class="state err">{{ searchError }}</div>
                <div v-else-if="searching && !results.length" class="state">{{ t("settings.searching") }}</div>
                <div v-else-if="!results.length" class="state">{{ t("settings.noChannel") }}</div>
                <button v-for="c in results" :key="c.id" class="result" @mousedown.prevent="pick(c)">
                  <img v-if="c.thumbnail" :src="c.thumbnail" class="avatar" alt="" referrerpolicy="no-referrer">
                  <span v-else class="avatar hatch" />
                  <span class="meta">
                    <span class="t">{{ c.title }}</span>
                    <span class="s">{{ [c.handle, followers(c.followers)].filter(Boolean).join(" · ") }}</span>
                    <span v-if="c.description" class="d">{{ c.description }}</span>
                  </span>
                </button>
              </div>
            </div>
            <div v-if="form.youtube" class="linked">
              <img v-if="form.youtube.thumbnail" :src="form.youtube.thumbnail" class="avatar sm" alt="" referrerpolicy="no-referrer">
              <a :href="form.youtube.url" target="_blank" rel="noopener" class="l">{{ form.youtube.title }}</a>
              <span class="muted">{{ [form.youtube.handle, followers(form.youtube.followers)].filter(Boolean).join(" · ") }}</span>
              <button class="x-btn" :title="t('settings.unlink')" @click="form.youtube = null">×</button>
            </div>
          </div>

          <div class="field">
            <label>{{ t("settings.channelLanguage") }}</label>
            <span class="hint">{{ t("settings.channelLanguageHint") }}</span>
            <Seg v-model="form.language" :options="channelLanguages" />
          </div>

          <div class="field">
            <label>{{ t("settings.analysis") }}</label>
            <span class="hint">{{ t("settings.analysisHint") }}</span>
            <div v-if="ytwatch && !ytwatch.connected" class="row">
              <input v-model="token" type="password" class="input" :placeholder="t('settings.tokenPlaceholder')" @keydown.enter="connect">
              <button class="btn lg" :disabled="!token.trim()" @click="connect">{{ t("settings.connectYtwatch") }}</button>
            </div>
            <div v-else-if="ytwatch" class="analysis">
              <div class="row center">
                <span class="muted small">{{ t("settings.ytwatchConnected") }} · <span class="mono">{{ ytwatch.token_hint }}</span></span>
                <button class="link-btn small" @click="disconnect">{{ t("settings.disconnect") }}</button>
                <span class="spacer" />
                <template v-if="running">
                  <span class="spinner" />
                  <span class="muted small">{{ analysis?.activity ? t("settings.activity", { activity: analysis.activity }) : t("settings.waitingWorker") }}</span>
                  <button class="btn" @click="cancelAnalysis">{{ t("common.cancel") }}</button>
                </template>
                <button v-else class="btn lg dark" @click="analyse">{{ analysis?.status === "done" ? t("settings.rerunAnalysis") : t("settings.analyse") }}</button>
              </div>
              <div v-if="analysis?.status === 'error'" class="state err">{{ t("settings.analysisFailed", { error: analysis.error }) }}</div>
              <div v-if="!form.youtube && !running" class="state">{{ t("settings.pickChannelFirst") }}</div>
              <div v-if="proposal('message')" class="proposal">
                <div class="p-head"><span class="eyebrow">{{ t("settings.takeaway") }}</span>
                  <button class="x-btn" :title="t('settings.hide')" @click="settle('message', false)">×</button></div>
                <p>{{ proposal("message") }}</p>
              </div>
            </div>
          </div>


          <div v-for="f in FIELDS" :key="f.key" class="field">
            <label>{{ t(`settings.fields.${f.key}.label`) }}</label>
            <span class="hint">{{ t(`settings.fields.${f.key}.hint`) }}</span>
            <textarea v-model="form[f.key]" class="textarea" :rows="f.rows ?? 3" :placeholder="t(`settings.fields.${f.key}.placeholder`)" />
            <div v-if="proposal(f.key)" class="proposal">
              <div class="p-head">
                <span class="eyebrow">{{ t("settings.proposal") }}</span>
                <span class="spacer" />
                <button class="btn" @click="settle(f.key, false)">{{ t("common.dismiss") }}</button>
                <button class="btn dark" @click="settle(f.key, true)">{{ form[f.key].trim() ? t("settings.replace") : t("settings.use") }}</button>
              </div>
              <p>{{ proposal(f.key) }}</p>
            </div>
          </div>

          <div class="submit">
            <button class="btn xl" :class="dirty ? 'red' : 'off'" :disabled="busy || !dirty" @click="save">
              {{ busy ? t("common.saving") : dirty ? t("common.save") : t("settings.savedState") }}
            </button>
          </div>
        </template>
      </template>

      <template v-else-if="tab === 'publish'">
        <div v-if="publishSaved !== null" class="field">
          <label>{{ t("settings.defaultDescription") }}</label>
          <span class="hint">{{ t("settings.defaultDescriptionHint") }}</span>
          <textarea v-model="publish.description" class="textarea" rows="14" :placeholder="t('settings.defaultDescriptionPlaceholder')" />
        </div>
        <div v-if="publishSaved !== null" class="submit">
          <button class="btn xl" :class="publishDirty ? 'red' : 'off'" :disabled="publishBusy || !publishDirty" @click="savePublish">
            {{ publishBusy ? t("common.saving") : publishDirty ? t("common.save") : t("settings.savedState") }}
          </button>
        </div>
      </template>

      <template v-else-if="tab === 'services'">
        <div class="field">
          <label>{{ t("settings.account") }}</label>
          <span class="hint">{{ t("settings.accountHint") }}</span>
          <input ref="clientInput" type="file" accept=".json,application/json" hidden @change="sendClient">
          <div v-if="account?.connected && account.channel" class="linked">
            <img v-if="account.channel.thumbnail" :src="account.channel.thumbnail" class="avatar sm" alt="" referrerpolicy="no-referrer">
            <span class="l">{{ account.channel.title }}</span>
            <span class="muted">{{ t("settings.connected") }}</span>
            <span class="spacer" />
            <button class="link-btn small" @click="disconnectYoutube">{{ t("settings.disconnect") }}</button>
          </div>
          <div v-else-if="account" class="row center">
            <button class="btn" @click="clientInput?.click()">{{ account.client ? t("settings.replaceClient") : t("settings.dropClient") }}</button>
            <template v-if="account.connecting">
              <span class="spinner" />
              <span class="muted small">{{ t("settings.finishGoogle") }}</span>
              <button class="btn" @click="cancelYoutube">{{ t("common.cancel") }}</button>
            </template>
            <button v-else class="btn lg dark" :disabled="!account.client" @click="connectYoutube">{{ t("settings.connectYoutube") }}</button>
          </div>
          <div v-if="account?.error && !account.connected" class="state err">{{ t("settings.connectFailed", { error: account.error }) }}</div>
        </div>

        <div v-if="claudeAccount" class="field">
          <label>{{ t("settings.claudeAccount") }}</label>
          <span class="hint">{{ t("settings.claudeAccountHint") }}</span>
          <div v-if="claudeAccount.loggedIn" class="row center">
            <span class="state ok">{{ t("settings.claudeConnected", { who: claudeAccount.email || claudeAccount.authMethod || "Claude" }) }}</span>
            <button class="link-btn small" @click="disconnectClaude">{{ t("settings.disconnect") }}</button>
          </div>
          <template v-else-if="claudeAccount.connecting">
            <div class="row center">
              <span class="spinner" />
              <span class="muted small">{{ t("settings.claudeFinish") }}</span>
              <a v-if="claudeAccount.url" class="link-btn small" :href="claudeAccount.url" target="_blank" rel="noopener">{{ t("settings.claudeOpenPage") }}</a>
              <button class="btn" @click="cancelClaude">{{ t("common.cancel") }}</button>
            </div>
            <div class="row">
              <input v-model="claudeCode" class="input" :placeholder="t('settings.claudeCodePlaceholder')"
                @keydown.enter="claudeCode.trim() && sendClaudeCode()">
              <button class="btn lg" :disabled="!claudeCode.trim()" @click="sendClaudeCode">{{ t("settings.claudeSendCode") }}</button>
            </div>
          </template>
          <div v-else class="row center">
            <button class="btn lg dark" @click="connectClaude">{{ t("settings.claudeConnect") }}</button>
          </div>
          <div v-if="claudeAccount.error && !claudeAccount.loggedIn" class="state err">{{ t("settings.connectFailed", { error: claudeAccount.error }) }}</div>
        </div>

        <div v-if="chatgptAccount" class="field">
          <label>{{ t("settings.chatgptAccount") }}</label>
          <span class="hint">{{ t("settings.chatgptAccountHint") }}</span>
          <span v-if="!chatgptAccount.installed" class="muted small">{{ t("settings.chatgptMissing") }}</span>
          <div v-else-if="chatgptAccount.loggedIn" class="row center">
            <span class="state ok">{{ t("settings.chatgptConnected") }}</span>
            <button class="link-btn small" @click="disconnectChatgpt">{{ t("settings.disconnect") }}</button>
          </div>
          <div v-else-if="chatgptAccount.connecting" class="row center">
            <span class="spinner" />
            <span class="muted small">{{ t("settings.chatgptFinish") }}</span>
            <a v-if="chatgptAccount.url" class="link-btn small" :href="chatgptAccount.url" target="_blank" rel="noopener">{{ t("settings.claudeOpenPage") }}</a>
            <button class="btn" @click="cancelChatgpt">{{ t("common.cancel") }}</button>
          </div>
          <div v-else class="row center">
            <button class="btn lg dark" @click="connectChatgpt">{{ t("settings.chatgptConnect") }}</button>
          </div>
          <div v-if="chatgptAccount.error && !chatgptAccount.loggedIn" class="state err">{{ t("settings.connectFailed", { error: chatgptAccount.error }) }}</div>
        </div>

        <div v-if="claudeModels" class="field">
          <label>{{ t("settings.claudeLight") }}</label>
          <span class="hint">{{ t("settings.claudeLightHint") }}</span>
          <Seg :model-value="claudeModels.light" :options="claudeOptions" @update:model-value="setClaudeModel('light', $event)" />
        </div>
        <div v-if="claudeModels" class="field">
          <label>{{ t("settings.claudeHeavy") }}</label>
          <span class="hint">{{ t("settings.claudeHeavyHint") }}</span>
          <Seg :model-value="claudeModels.heavy" :options="claudeOptions" @update:model-value="setClaudeModel('heavy', $event)" />
        </div>

        <div v-if="transcription" class="field">
          <label>{{ t("settings.transcription") }}</label>
          <Seg v-model="engine" :options="engineOptions" />
          <span v-if="engine === 'whisper'" class="muted small">{{ t("settings.engines.whisper.hint") }}</span>
          <template v-if="engine !== 'whisper'">
            <div v-if="transcription.keys[engine]" class="row center">
              <span class="muted small">{{ t("settings.keySaved") }} · <span class="mono">{{ transcription.keys[engine] }}</span></span>
              <button class="link-btn small" @click="forgetKey(engine)">{{ t("settings.forgetKey") }}</button>
            </div>
            <div v-else class="row">
              <input v-model="engineKey" type="password" class="input" :placeholder="t(`settings.engines.${engine}.placeholder`)"
                @keydown.enter="engineKey.trim() && saveEngine(engine, engineKey)">
              <button class="btn lg" :disabled="!engineKey.trim()" @click="saveEngine(engine, engineKey)">{{ t("settings.useEngine") }}</button>
            </div>
            <span v-if="transcription.engine !== engine" class="state err">{{ t("settings.engineInactive") }}</span>
          </template>
        </div>
      </template>

      <template v-else>
        <div class="field">
          <label>{{ t("settings.language") }}</label>
          <span class="hint">{{ t("settings.languageHint") }}</span>
          <Seg v-model="uiLocale" :options="localeOptions" />
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.page { flex: 1; overflow: auto; padding: 32px 40px 56px; }
.form { max-width: 720px; display: flex; flex-direction: column; gap: 26px; }
.intro { font-size: 14px; line-height: 1.5; margin-top: -8px; }
.tabs { margin-top: -12px; }
.tabs .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--red); align-self: center; }
.h1 { font-size: 26px; font-weight: 600; letter-spacing: -0.015em; }
.field { display: flex; flex-direction: column; gap: 8px; }
.field label { font-size: 13.5px; font-weight: 600; }
.hint { font-size: 12.5px; color: var(--faint); margin-top: -4px; }
.textarea { min-height: 76px; font-size: 14.5px; }
.name-input { height: 42px; font-size: 15px; width: 100%; padding-right: 36px; }
.submit { display: flex; gap: 10px; padding-top: 8px; border-top: 1px solid var(--line-soft); }
.btn.off { background: var(--toggle-off); border-color: var(--toggle-off); color: #fff; }

.search { position: relative; }
.spinner {
  display: inline-block; width: 12px; height: 12px; border-radius: 50%;
  border: 2px solid var(--line); border-top-color: var(--red); animation: spin 1s linear infinite;
}
.spinner.in-input { position: absolute; right: 14px; top: 15px; }
@keyframes spin { to { transform: rotate(360deg); } }
.results {
  position: absolute; top: calc(100% + 4px); left: 0; right: 0; z-index: 30; background: #fff;
  border: 1px solid var(--line-strong); border-radius: 4px; box-shadow: 0 12px 32px rgba(0, 0, 0, .12);
  padding: 4px; display: flex; flex-direction: column; max-height: 420px; overflow-y: auto;
}
.state { padding: 10px 12px; font-size: 13px; color: var(--muted); }
.state.err { color: var(--red-dark); }
.result {
  display: flex; align-items: flex-start; gap: 12px; padding: 8px 10px; border: none; background: transparent;
  border-radius: 3px; cursor: pointer; text-align: left; width: 100%;
}
.result:hover { background: var(--bg-soft); }
.avatar { width: 36px; height: 36px; border-radius: 50%; flex-shrink: 0; object-fit: cover; }
.avatar.sm { width: 22px; height: 22px; }
.meta { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.meta .t { font-size: 13.5px; font-weight: 600; }
.meta .s { font-size: 12px; color: var(--faint); }
.meta .d { font-size: 12px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.linked { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border: 1px solid var(--line); border-radius: 4px; font-size: 13px; }
.linked .l { font-weight: 600; color: var(--ink); }
.linked .muted { flex: 1; font-size: 12px; }

.row { display: flex; gap: 6px; }
.row .input { flex: 1; height: 40px; }
.row.center { align-items: center; gap: 10px; }
.small { font-size: 12.5px; }
.analysis { display: flex; flex-direction: column; gap: 10px; padding: 12px 14px; border: 1px solid var(--line); border-radius: 4px; }
.analysis .state { padding: 0; }
.proposal { display: flex; flex-direction: column; gap: 8px; padding: 12px 14px; background: var(--bg-soft); border: 1px dashed var(--dash); border-radius: 4px; }
.proposal .p-head { display: flex; align-items: center; gap: 6px; }
.proposal .p-head .eyebrow { flex: 1; }
.proposal p { margin: 0; font-size: 13.5px; line-height: 1.55; white-space: pre-wrap; }
</style>
