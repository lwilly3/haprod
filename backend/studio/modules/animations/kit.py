"""
Le kit de motion design : la charte (style.css) et les animations type, copiées dans chaque projet.

Deux couches :
  kit/ (à côté de ce fichier)   la charte de base et les exemples livrés avec le studio
  data/kit/                     le design system de l'utilisateur (design.json) et les animations
                                qu'il a ajoutées au kit (reportées depuis une inspiration)

style.css est la charte de base dont on remplace les variables par celles du design system. Les
animations du kit n'emploient que ces variables : changer une couleur ou une police ne demande de
régénérer aucune animation. Une matière (kit/textures/<id>.css) peut s'y ajouter : elle change l'allure
des briques (.card, .node…) au-delà des couleurs, sans toucher aux animations non plus.
"""
import hashlib
import json
import re
import shutil
from pathlib import Path
from urllib.parse import quote_plus

from ...config import DATA_DIR

BUILTIN_DIR = Path(__file__).parent / "kit"
USER_DIR = DATA_DIR / "kit"
DESIGN_FILE = USER_DIR / "design.json"

COLORS = ("card", "card-2", "line", "text", "muted", "accent", "accent-ink")
FONTS = ("font", "mono")
# les graisses chargées : le texte des cartes, les étiquettes mono
WEIGHTS = {"font": "400;500;600;700", "mono": "400;500"}
FALLBACK = {"font": '"Inter", system-ui, sans-serif', "mono": "ui-monospace, monospace"}
# les matières : « lisse » est la charte telle quelle, les autres ajoutent kit/textures/<id>.css
TEXTURES = ("lisse", "papier")

# des ambiances complètes à choisir comme point de départ (le nom affiché est dans l'i18n, par id).
# Contrastes vérifiés sur le fond des cartes : texte ≥ 15:1, texte discret ≥ 5.5:1, accent ≥ 4.5:1.
PRESETS = (
    {"id": "atelier", "card": "#1a1512", "card-2": "#2b231e", "line": "#54463c", "text": "#f6ede3",
     "muted": "#b8a797", "accent": "#ee8435", "accent-ink": "#1a1512", "radius": 22,
     "font": "Space Grotesk", "mono": "JetBrains Mono", "texture": "lisse"},
    {"id": "nuit", "card": "#0f1420", "card-2": "#1a2233", "line": "#334058", "text": "#eef2fa",
     "muted": "#97a3ba", "accent": "#4ea8ff", "accent-ink": "#0b1020", "radius": 16,
     "font": "Inter Tight", "mono": "JetBrains Mono", "texture": "lisse"},
    {"id": "papier", "card": "#fcfaf5", "card-2": "#ddd0b8", "line": "#8a7f72", "text": "#1e1a16",
     "muted": "#675d52", "accent": "#bb3d24", "accent-ink": "#fff8f0", "radius": 0,
     "font": "Fraunces", "mono": "IBM Plex Mono", "texture": "papier"},
    {"id": "terminal", "card": "#0e1411", "card-2": "#18221d", "line": "#2f4239", "text": "#e6f2ea",
     "muted": "#8fa89a", "accent": "#3ddc97", "accent-ink": "#0b130f", "radius": 6,
     "font": "Manrope", "mono": "Space Mono", "texture": "lisse"},
    {"id": "neon", "card": "#16121f", "card-2": "#241d33", "line": "#433a5c", "text": "#f3eefc",
     "muted": "#a79cc0", "accent": "#c084fc", "accent-ink": "#16121f", "radius": 28,
     "font": "Sora", "mono": "DM Mono", "texture": "lisse"},
    {"id": "contraste", "card": "#0a0a0a", "card-2": "#1f1f1f", "line": "#3d3d3d", "text": "#ffffff",
     "muted": "#a3a3a3", "accent": "#ff4b3e", "accent-ink": "#0a0a0a", "radius": 0,
     "font": "Archivo", "mono": "IBM Plex Mono", "texture": "lisse"},
)

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_FAMILY = re.compile(r"^[A-Za-z0-9 ]{2,40}$")


def _base_css() -> str:
    return (BUILTIN_DIR / "style.css").read_text(encoding="utf-8")


def _root_var(css: str, name: str) -> str | None:
    m = re.search(rf"--{re.escape(name)}:\s*([^;]+);", css)
    return m.group(1).strip() if m else None


def defaults() -> dict:
    """Le design system de la charte de base : {couleur: #hex, radius: px, font, mono, texture}."""
    css = _base_css()
    out = {k: _root_var(css, k) for k in COLORS}
    out["radius"] = int(re.sub(r"\D", "", _root_var(css, "radius") or "22") or 22)
    for k in FONTS:
        out[k] = (_root_var(css, k) or "").split(",")[0].strip().strip('"')
    out["texture"] = TEXTURES[0]
    return out


def design() -> dict:
    saved = json.loads(DESIGN_FILE.read_text(encoding="utf-8")) if DESIGN_FILE.is_file() else {}
    return {**defaults(), **saved}


def save_design(values: dict) -> dict:
    """Enregistre ce qui est valide, ignore le reste ; rend le design system complet."""
    out = design()
    for k in COLORS:
        if isinstance(values.get(k), str) and _HEX.match(values[k]):
            out[k] = values[k].lower()
    if isinstance(values.get("radius"), (int, float)):
        out["radius"] = max(0, min(80, int(values["radius"])))
    for k in FONTS:
        if isinstance(values.get(k), str) and _FAMILY.match(values[k].strip()):
            out[k] = values[k].strip()
    if values.get("texture") in TEXTURES:
        out["texture"] = values["texture"]
    USER_DIR.mkdir(parents=True, exist_ok=True)
    DESIGN_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def style_css() -> str:
    """La charte de base, avec les variables et les polices du design system, puis sa matière."""
    d = design()
    css = _base_css()
    families = "&".join(f"family={quote_plus(d[k])}:wght@{WEIGHTS[k]}" for k in FONTS)
    css = re.sub(r'@import url\("https://fonts\.googleapis\.com/[^"]*"\);',
                 f'@import url("https://fonts.googleapis.com/css2?{families}&display=block");', css, count=1)
    values = {k: d[k] for k in COLORS} | {"radius": f"{d['radius']}px"}
    values |= {k: f'"{d[k]}", {FALLBACK[k]}' for k in FONTS}
    for k, v in values.items():
        css = re.sub(rf"(--{re.escape(k)}:\s*)[^;]+;", lambda m, v=v: f"{m.group(1)}{v};", css, count=1)
    texture = BUILTIN_DIR / "textures" / f"{d['texture']}.css"
    if texture.is_file():
        css += texture.read_text(encoding="utf-8")
    return css


def version() -> str:
    """L'empreinte de la charte générée : elle change à chaque réglage du design system."""
    return hashlib.sha1(style_css().encode()).hexdigest()[:10]


def examples() -> list[Path]:
    """Les animations du kit : celles livrées avec le studio, puis celles de l'utilisateur (qui
    remplacent une livrée du même nom)."""
    by_name = {p.name: p for p in BUILTIN_DIR.glob("exemple-*.html")}
    by_name |= {p.name: p for p in USER_DIR.glob("exemple-*.html")}
    return [by_name[n] for n in sorted(by_name)]


def is_mine(path: Path) -> bool:
    return path.parent == USER_DIR


def example(name: str) -> Path | None:
    return next((p for p in examples() if p.name == Path(name).name), None)


def remove(name: str) -> None:
    path = USER_DIR / Path(name).name
    if not path.is_file() or not path.name.startswith("exemple-"):
        raise ValueError("animation inconnue")
    path.unlink()


def install(directory: Path, *, keep_style: bool = False) -> None:
    """Copie la charte et les animations du kit dans un dossier de travail (style.css, exemples/).
    `keep_style` : garder la charte déjà présente (celle avec laquelle le projet a été monté)."""
    (directory / "exemples").mkdir(parents=True, exist_ok=True)
    if not (keep_style and (directory / "style.css").is_file()):
        (directory / "style.css").write_text(style_css(), encoding="utf-8")
    for path in examples():
        shutil.copy2(path, directory / "exemples" / path.name)
