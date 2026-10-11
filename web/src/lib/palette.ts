/**
 * Des thèmes tirés d'une image de tournage : les neutres prennent la teinte d'ambiance de la pièce,
 * l'accent une des couleurs franches de l'image (un logo, une lampe, un néon). Une variante par
 * couleur franche trouvée, à choisir. Rien que les couleurs : polices et arrondi ne bougent pas.
 */
export type Theme = Record<string, string>;
type Rgb = [number, number, number];

const SIDE = 240; // l'image est réduite avant l'analyse : la couleur d'ensemble suffit
const BINS = 24; // tranches de teinte de 15°

export async function themesFromImage(file: File, max = 3): Promise<Theme[]> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, SIDE / Math.max(bitmap.width, bitmap.height));
  const w = Math.max(1, Math.round(bitmap.width * scale));
  const h = Math.max(1, Math.round(bitmap.height * scale));
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
  ctx.drawImage(bitmap, 0, 0, w, h);
  bitmap.close();
  const data = ctx.getImageData(0, 0, w, h).data;

  // la teinte d'ambiance : moyenne circulaire des teintes, pondérée par la saturation
  let x = 0, y = 0, satSum = 0;
  const vivid: Rgb[][] = Array.from({ length: BINS }, () => []);
  const count = data.length / 4;
  for (let i = 0; i < data.length; i += 4) {
    const rgb: Rgb = [data[i], data[i + 1], data[i + 2]];
    const [hue, s, l] = toHsl(rgb);
    x += Math.cos(hue * 2 * Math.PI) * s;
    y += Math.sin(hue * 2 * Math.PI) * s;
    satSum += s;
    // une couleur franche : saturée, ni sombre ni brûlée
    const hi = Math.max(...rgb), lo = Math.min(...rgb);
    if (hi > 90 && (hi - lo) / hi > 0.45 && l < 0.85) vivid[Math.floor(hue * BINS) % BINS].push(rgb);
  }
  const ambient = (Math.atan2(y, x) / (2 * Math.PI) + 1) % 1;
  const tint = Math.min(0.18, (satSum / count) * 0.6);

  const card = toHex([ambient, tint, 0.085]);
  const neutrals = {
    card,
    "card-2": toHex([ambient, tint, 0.15]),
    line: toHex([ambient, tint * 0.9, 0.28]),
    text: toHex([ambient, Math.min(0.35, tint * 2), 0.94]),
    muted: toHex([ambient, tint, 0.65]),
  };

  // les accents : les tranches de teinte les plus présentes, assez éloignées les unes des autres
  const picked: number[] = [];
  const order = vivid.map((px, bin) => ({ px, bin })).sort((a, b) => b.px.length - a.px.length);
  for (const { px, bin } of order) {
    if (picked.length >= max || px.length < count * 0.002) break;
    if (picked.some((p) => Math.min(Math.abs(p - bin), BINS - Math.abs(p - bin)) < 2)) continue;
    picked.push(bin);
  }
  const accents = picked.map((bin) => accent(representative(vivid[bin]), card));
  if (!accents.length) accents.push(accent([ambient, 0.75, 0.6], card));

  return accents.map((a) => ({
    ...neutrals,
    accent: a,
    "accent-ink": contrast(a, card) >= 4.5 ? card : "#ffffff",
  }));
}

/** La couleur d'une tranche : la moyenne de son tiers le plus saturé (le logo, pas son ombre). */
function representative(px: Rgb[]): [number, number, number] {
  const sat = ([r, g, b]: Rgb) => (Math.max(r, g, b) - Math.min(r, g, b)) / Math.max(r, g, b, 1);
  const top = [...px].sort((a, b) => sat(b) - sat(a)).slice(0, Math.max(1, Math.floor(px.length / 3)));
  const mean = [0, 1, 2].map((i) => top.reduce((s, p) => s + p[i], 0) / top.length) as Rgb;
  return toHsl(mean);
}

/** Un accent qui tient sur le fond des cartes : franc, clair, au moins 4.5:1 de contraste. */
function accent([hue, s, l]: [number, number, number], card: string): string {
  let light = Math.min(0.68, Math.max(0.55, l));
  let hex = toHex([hue, Math.max(0.7, s), light]);
  while (contrast(hex, card) < 4.5 && light < 0.85) {
    light += 0.02;
    hex = toHex([hue, Math.max(0.7, s), light]);
  }
  return hex;
}

function toHsl([r, g, b]: Rgb): [number, number, number] {
  r /= 255; g /= 255; b /= 255;
  const hi = Math.max(r, g, b), lo = Math.min(r, g, b), l = (hi + lo) / 2, d = hi - lo;
  if (!d) return [0, 0, l];
  const s = d / (1 - Math.abs(2 * l - 1));
  const h = hi === r ? ((g - b) / d + 6) % 6 : hi === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h / 6, s, l];
}

function toHex([h, s, l]: [number, number, number]): string {
  const k = (n: number) => (n + h * 12) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1));
  return "#" + [f(0), f(8), f(4)].map((v) => Math.round(v * 255).toString(16).padStart(2, "0")).join("");
}

function luminance(hex: string): number {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (hi + 0.05) / (lo + 0.05);
}
