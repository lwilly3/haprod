/**
 * Les quelques textes que le studio écrit lui-même dans le contenu (script, description YouTube) :
 * dans la langue de la chaîne (Réglages), pas dans celle de l'interface.
 */
import { ref } from "vue";
import { api } from "./api";

const TEXTS = {
  fr: { credits: "Crédits audio :", chapters: "Chapitres", fullVideo: "Vidéo complète :", part: "Partie", newPart: "Nouvelle partie" },
  en: { credits: "Audio credits:", chapters: "Chapters", fullVideo: "Full video:", part: "Part", newPart: "New part" },
  es: { credits: "Créditos de audio:", chapters: "Capítulos", fullVideo: "Vídeo completo:", part: "Parte", newPart: "Nueva parte" },
  de: { credits: "Audio credits:", chapters: "Kapitel", fullVideo: "Ganzes Video:", part: "Teil", newPart: "Neuer Teil" },
  it: { credits: "Audio credits:", chapters: "Capitoli", fullVideo: "Video completo:", part: "Parte", newPart: "Nuova parte" },
  pt: { credits: "Audio credits:", chapters: "Capítulos", fullVideo: "Vídeo completo:", part: "Parte", newPart: "Nova parte" },
};
type Lang = keyof typeof TEXTS;

const language = ref<Lang>("en");
let loading: Promise<void> | null = null;

/** Charge la langue de la chaîne (une fois par session) ; à appeler au montage du composant. */
export function loadChannelLanguage(): Promise<void> {
  loading ??= api<{ language: string }>("/api/settings/channel")
    .then((c) => { if (c.language in TEXTS) language.value = c.language as Lang; })
    .catch(() => { loading = null; });
  return loading;
}

/** Après un enregistrement des réglages. */
export function setChannelLanguage(l: string) {
  if (l in TEXTS) language.value = l as Lang;
}

export function contentText(key: keyof typeof TEXTS.fr): string {
  return TEXTS[language.value][key];
}

/** Le même texte dans toutes les langues : pour reconnaître ce qui a déjà été inséré. */
export function contentTextAll(key: keyof typeof TEXTS.fr): string[] {
  return Object.values(TEXTS).map((t) => t[key]);
}
