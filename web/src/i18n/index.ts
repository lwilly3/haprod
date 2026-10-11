import { createI18n } from "vue-i18n";

export type Locale = "en" | "fr";
export const LOCALES: Record<Locale, string> = { en: "English", fr: "Français" };

type Messages = { [key: string]: string | Messages };

// un fichier par espace de noms : locales/<langue>/<ns>.ts → messages[langue][ns]
const files = import.meta.glob<{ default: Messages }>("./locales/*/*.ts", { eager: true });
const messages: Record<string, Messages> = {};
for (const [path, mod] of Object.entries(files)) {
  const [, lang, ns] = path.match(/\.\/locales\/(\w+)\/(\w+)\.ts$/)!;
  (messages[lang] ??= {})[ns] = mod.default;
}

function initial(): Locale {
  const saved = localStorage.getItem("studio.locale");
  if (saved === "en" || saved === "fr") return saved;
  return navigator.language.toLowerCase().startsWith("fr") ? "fr" : "en";
}

export const i18n = createI18n({
  legacy: false,
  locale: initial() as string,
  fallbackLocale: "en",
  messages,
  warnHtmlMessage: false,
});

/** Pour les modules .ts hors composants : à appeler au rendu, jamais au chargement du module. */
export const t = i18n.global.t;

export function locale(): Locale {
  return i18n.global.locale.value as Locale;
}

export function setLocale(l: Locale) {
  i18n.global.locale.value = l;
  localStorage.setItem("studio.locale", l);
  document.documentElement.lang = l;
}

document.documentElement.lang = locale();
