import { locale, t } from "../i18n";

/** 00:01:23 (ou 00:01:23.456) */
export function tc(sec: number, withMs = false): string {
  const ms = Math.round(sec * 1000);
  const h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60, s = Math.floor(ms / 1000) % 60;
  const base = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return withMs ? `${base}.${String(ms % 1000).padStart(3, "0")}` : base;
}

/** "1:30", "01:02:03.5", "90" → secondes (null si illisible) */
export function parseTc(text: string): number | null {
  const parts = text.trim().replace(",", ".").split(":");
  if (parts.length > 3 || parts.some((p) => !/^\d+(\.\d+)?$/.test(p))) return null;
  return parts.reduce((acc, p) => acc * 60 + Number(p), 0);
}

/** 3 min 07, 42 s */
export function duration(sec: number | null | undefined): string {
  if (sec == null) return "";
  const m = Math.floor(sec / 60), s = Math.round(sec % 60);
  return m ? t("format.minSec", { m, s: String(s).padStart(2, "0") }) : t("format.sec", { s });
}

/** « Français », « Anglais »… dans la langue de l'interface (null si le code est inconnu). */
export function languageName(code: string): string | null {
  try {
    const name = new Intl.DisplayNames([locale()], { type: "language" }).of(code);
    return name && name !== code ? name.charAt(0).toUpperCase() + name.slice(1) : null;
  } catch {
    return null;
  }
}

/** Nom d'une langue par son code, lu au rendu : LANGUAGES[code] ?? code. */
export const LANGUAGES: Readonly<Record<string, string>> = new Proxy({}, {
  get: (_, code) => (typeof code === "string" ? languageName(code) ?? undefined : undefined),
});

/** 04:07 (minutes:secondes, les heures comptées en minutes) */
export function mmss(sec: number | null | undefined): string {
  const t = Math.max(0, Math.round(sec ?? 0));
  return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
}

/** 4:07 */
export function mss(sec: number | null | undefined): string {
  const t = Math.max(0, Math.round(sec ?? 0));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
}

/** 4:07.3 (au dixième de seconde) */
export function mssd(sec: number | null | undefined): string {
  const d = Math.max(0, Math.round((sec ?? 0) * 10));
  return `${Math.floor(d / 600)}:${((d % 600) / 10).toFixed(1).padStart(4, "0")}`;
}

/** « 2,4 Go », « 180 Mo », « 12 Ko » */
export function bytes(n: number): string {
  const units = ["kb", "mb", "gb", "tb"] as const;
  let v = n / 1024, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  const digits = v < 10 && i >= 2 ? 1 : 0;
  return t(`format.${units[i]}`, { n: v.toLocaleString(locale(), { maximumFractionDigits: digits }) });
}

/** « 14 oct. » */
export function shortDate(epoch: number): string {
  return new Date(epoch * 1000).toLocaleDateString(locale(), { day: "numeric", month: "short" });
}
