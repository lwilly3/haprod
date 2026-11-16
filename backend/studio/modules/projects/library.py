"""
Les fichiers d'un projet rangés par catégorie (Ressources), et la bibliothèque commune
à tous les projets (B-roll, musique, sound design, images, logos, personnes, lieux).

Les assets récupérés (étape Assets) vont soit dans le projet (assets/<catégorie>/), soit
dans la bibliothèque (<catégorie>/) : même clé de catégorie des deux côtés.

La bibliothèque est un dossier par catégorie dans data/library/ ; index.json y retient
de quel projet vient chaque fichier.
"""
import json
import re
from pathlib import Path
from urllib.parse import quote

from ...config import DATA_DIR
from ..animations import kit
from . import media, service

LIBRARY_DIR = DATA_DIR / "library"
LIBRARY_INDEX = LIBRARY_DIR / "index.json"
CATEGORIES = {"broll": "B-roll", "musique": "Musique", "sfx": "Sound design", "images": "Images",
              "logos": "Logos", "personnes": "Personnes", "lieux": "Lieux",
              # l'étape Vignette : les photos de l'auteur et les vignettes qui servent de modèle de style
              "portraits": "Mes portraits", "vignettes": "Vignettes"}

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".psd"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".aif", ".aiff"}
VIDEO_EXT = {f".{e}" for e in service.VIDEO_EXTENSIONS}
TIMED = AUDIO_EXT | VIDEO_EXT

_durations: dict[tuple[str, float], float | None] = {}


def duration(path: Path) -> float | None:
    """Durée d'un média, mise en cache tant que le fichier ne change pas."""
    if path.suffix.lower() not in TIMED:
        return None
    key = (str(path), path.stat().st_mtime)
    if key not in _durations:
        _durations[key] = media.probe(path).get("duration")
    return _durations[key]


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return "Images"
    if ext in AUDIO_EXT:
        return "Audio"
    if ext in VIDEO_EXT:
        return "Vidéo"
    return "Documents"


def _files(folder: Path) -> list[Path]:
    return sorted((p for p in folder.iterdir() if p.is_file()), key=lambda p: p.name.lower()) if folder.is_dir() else []


def resources(project: dict) -> list[dict]:
    """Groupes {k, items: [{name, rel, kind, duration}]} : ce que contient le dossier du projet."""
    root = service.project_dir(project["id"])

    def item(path: Path, label: str | None = None) -> dict:
        return {"name": label or path.name, "rel": path.relative_to(root).as_posix() if root in path.parents else str(path),
                "kind": kind_of(path), "duration": duration(path), "size": path.stat().st_size}

    script_dir = root / service.SCRIPT_DIR
    script = [item(script_dir / n) for n in (service.SCRIPT_FILE, service.NOTES_FILE, service.DOCUMENTATION_FILE,
                                              service.BRIEF_FILE) if (script_dir / n).is_file()]
    # un rush peut être hors du dossier du projet : l'interface le lit par son id
    rushes = [{**item(Path(r["path"])), "rush": r["id"]} for r in project["rushes"] if Path(r["path"]).is_file()]
    exports = [item(p) for p in _files(root / service.DERUSH_DIR) if p.suffix in (".mp4", ".xml")]
    source = project.get("source") or {}
    sources = [item(Path(source["path"]))] if source.get("path") and Path(source["path"]).is_file() else []
    transcripts = [item(p) for p in _files(root / service.TRANSCRIPTS_DIR)]
    added = [item(p) for p in _files(root / service.RESOURCES_DIR)]
    assets = [item(p) for key in CATEGORIES for p in _files(root / service.ASSETS_DIR / key)]
    vignettes = [item(p) for p in _files(root / service.VIGNETTES_DIR)]
    groups = [("Script", script), ("Rushes", rushes), ("Dérush", exports), ("Vidéo source", sources),
              ("Transcripts", transcripts), ("Vignettes", vignettes), ("Assets", assets), ("Fichiers ajoutés", added)]
    return [{"k": k, "items": items} for k, items in groups]


# les catégories de la bibliothèque qui illustrent une vidéo (pas la musique ni ce qui sert à la vignette)
VISUAL_CATEGORIES = ("broll", "images", "logos", "personnes", "lieux")


def visuals(project: dict) -> list[dict]:
    """Les images et vidéos qu'on peut poser sur un plan : assets et fichiers ajoutés du projet, puis la
    bibliothèque. Chacune {label, url, name, kind, duration} ; `label` la désigne pour Claude, `url` comme
    le panneau Médias du script."""
    pid = project["id"]
    enc = lambda rel: "/".join(quote(part) for part in rel.split("/"))  # noqa: E731
    out = [{"label": f"projet/{x['rel']}", "url": f"/api/projects/{pid}/files/{enc(x['rel'])}", "name": x["name"],
            "kind": x["kind"], "duration": x["duration"]}
           for g in resources(project) if g["k"] in ("Assets", "Fichiers ajoutés")
           for x in g["items"] if x["kind"] in ("Vidéo", "Images")]
    out += [{"label": f"bibliothèque/{x['rel']}", "url": f"/api/projects/library/file/{enc(x['rel'])}",
             "name": x["name"], "kind": x["kind"], "duration": x["duration"]}
            for x in library() if x["category"] in VISUAL_CATEGORIES and x["kind"] in ("Vidéo", "Images")]
    return out


# --- Bibliothèque commune ---------------------------------------------------------------

def _index() -> dict:
    return json.loads(LIBRARY_INDEX.read_text(encoding="utf-8")) if LIBRARY_INDEX.is_file() else {}


def _save_index(index: dict) -> None:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    LIBRARY_INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


def remember_origin(rel: str, project_title: str | None) -> None:
    """Un fichier (re)déposé : sa provenance, et une description à réécrire."""
    index = _index()
    index[rel] = {"project": project_title}
    _save_index(index)


def remember_credit(rel: str, credit: dict, description: str) -> None:
    """Un son libre de droits venu d'Internet (free_audio) : son auteur et sa licence, pour le citer."""
    index = _index()
    index[rel] = {"project": None, "description": description, "credit": credit}
    _save_index(index)


def find_credit(category: str, url: str) -> str | None:
    """Le fichier de la bibliothèque déjà téléchargé depuis cette page d'origine, s'il est encore là."""
    for rel, entry in _index().items():
        if url and rel.startswith(f"{category}/") and ((entry or {}).get("credit") or {}).get("url") == url \
                and (LIBRARY_DIR / rel).is_file():
            return rel
    return None


def credit_of(src: str) -> dict | None:
    """Le crédit d'un média de la timeline (« library/sfx/x.mp3 » ou sa copie « assets/sfx/x.mp3 »),
    retrouvé dans la bibliothèque par catégorie et nom, comme gain_of."""
    parts = src.split("/")
    if len(parts) < 3 or parts[0] not in ("library", service.ASSETS_DIR):
        return None
    return (_index().get(f"{parts[-2]}/{parts[-1]}") or {}).get("credit")


def describe(rel: str, description: str) -> None:
    """Ce que montre ou fait un fichier, et quand s'en servir : c'est ce que lit Daryl pour le choisir."""
    if not (LIBRARY_DIR / rel).is_file() or rel.split("/")[0] not in CATEGORIES:
        raise ValueError("fichier inconnu")
    index = _index()
    index.setdefault(rel, {"project": None})["description"] = description.strip()
    _save_index(index)


def descriptions() -> dict[str, str]:
    """{rel: description} des fichiers décrits."""
    return {rel: e["description"] for rel, e in _index().items() if (e or {}).get("description")}


GAIN_RANGE = (-60.0, 12.0)


def set_gain(rel: str, gain_db: float | None) -> None:
    """Le volume (dB) auquel poser ce son ou cette musique au montage ; None : le défaut du studio."""
    path = LIBRARY_DIR / rel
    if not path.is_file() or rel.split("/")[0] not in CATEGORIES or path.suffix.lower() not in AUDIO_EXT:
        raise ValueError("fichier inconnu")
    index = _index()
    entry = index.setdefault(rel, {"project": None})
    if gain_db is None:
        entry.pop("gain_db", None)
    else:
        entry["gain_db"] = round(max(GAIN_RANGE[0], min(float(gain_db), GAIN_RANGE[1])), 1)
    _save_index(index)


def gains() -> dict[str, float]:
    """{rel: gain_db} des fichiers qui ont un volume par défaut."""
    return {rel: e["gain_db"] for rel, e in _index().items() if isinstance((e or {}).get("gain_db"), (int, float))}


def gain_of(src: str, known: dict[str, float] | None = None) -> float | None:
    """Le volume par défaut d'un média de la timeline (« library/sfx/x.wav » ou sa copie « assets/sfx/x.wav »),
    retrouvé dans la bibliothèque par catégorie et nom."""
    parts = src.split("/")
    if len(parts) < 3 or parts[0] not in ("library", service.ASSETS_DIR):
        return None
    return (gains() if known is None else known).get(f"{parts[-2]}/{parts[-1]}")


def library() -> list[dict]:
    index = _index()
    items = []
    for key, label in CATEGORIES.items():
        for path in _files(LIBRARY_DIR / key):
            rel = f"{key}/{path.name}"
            entry = index.get(rel) or {}
            items.append({"name": path.name, "rel": rel, "category": key, "type": label,
                          "project": entry.get("project"), "description": entry.get("description", ""),
                          "gain_db": entry.get("gain_db"), "duration": duration(path), "kind": kind_of(path),
                          "credit": entry.get("credit")})
    return items


def destination(pid: str, common: bool, category: str) -> tuple[Path, str]:
    """Le dossier où ranger un asset récupéré, et son libellé (« Projet · B-roll », « Communs · Logos »)."""
    if category not in CATEGORIES:
        raise ValueError("catégorie inconnue")
    if common:
        return library_folder(category), f"Communs · {CATEGORIES[category]}"
    folder = service.project_dir(pid) / service.ASSETS_DIR / category
    folder.mkdir(parents=True, exist_ok=True)
    return folder, f"Projet · {CATEGORIES[category]}"


def library_folder(category: str) -> Path:
    if category not in CATEGORIES:
        raise ValueError("catégorie inconnue")
    folder = LIBRARY_DIR / category
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# --- Animations types -------------------------------------------------------------------
# Les compositions de référence du kit (animations/kit.py), copiées dans chaque projet pour
# Daryl : la bibliothèque les montre en mouvement. Elles chargent la charte par « ../style.css ».

def _attr(html: str, name: str) -> str | None:
    m = re.search(rf'\b{name}="([^"]*)"', html)
    return m.group(1) if m else None


def animations() -> list[dict]:
    """Chaque animation du kit : {name, id, title, description, format, tier, duration, hero, url, mine}.
    La description est le commentaire d'en-tête du fichier, sans son préfixe « EXEMPLE (format …) : » ;
    `mine` : ajoutée par l'utilisateur (on peut la retirer)."""
    items = []
    for path in kit.examples():
        html = path.read_text(encoding="utf-8")
        comment = re.search(r"<!--(.*?)-->", html, re.S)
        text = " ".join(comment.group(1).split()) if comment else ""
        text = re.sub(r"^EXEMPLE\s*(\([^)]*\))?\s*:\s*", "", text)
        text = re.sub(r"\s*Temps 0 = [^.]*\.$", "", text)  # consigne pour Daryl, pas pour l'écran
        text = text[:1].upper() + text[1:]
        stage = re.search(r'<div[^>]*id="stage"[^>]*>', html)
        tag = stage.group(0) if stage else ""
        duration, hero = _attr(tag, "data-duration"), _attr(tag, "data-hero")
        items.append({"name": path.name, "id": _attr(tag, "data-composition-id") or path.stem,
                      "title": path.stem.removeprefix("exemple-").replace("-", " ").capitalize(), "description": text,
                      "format": "short" if 'class="short"' in tag else "youtube", "tier": "kit",
                      "duration": float(duration) if duration else None, "hero": float(hero) if hero else None,
                      "url": f"/api/projects/library/animations/exemples/{quote(path.name)}", "mine": kit.is_mine(path)})
    return items


def animation_file(name: str) -> Path | None:
    """Une animation du kit, sans sortir de ses dossiers."""
    return kit.example(name)


# --- Animations d'editing-os ------------------------------------------------------------
# Les 12 styles de cartes de la style-library d'editing-os, importés par
# backend/scripts/import_editing_os.py (contenu de tiers : dans data/, jamais dans le dépôt).

EDITING_OS_DIR = LIBRARY_DIR / "animations" / "editing-os"
_editing_os: tuple[float, dict] | None = None


def _editing_os_index() -> dict:
    """index.json de l'import, relu seulement s'il a changé (1 700 cartes)."""
    global _editing_os
    path = EDITING_OS_DIR / "index.json"
    if not path.is_file():
        return {"styles": [], "cards": {}}
    mtime = path.stat().st_mtime
    if not _editing_os or _editing_os[0] != mtime:
        _editing_os = (mtime, json.loads(path.read_text(encoding="utf-8")))
    return _editing_os[1]


def animation_styles() -> list[dict]:
    """Les styles importés : {id, name, inspiration, count}."""
    return _editing_os_index()["styles"]


def style_animations(style: str) -> list[dict] | None:
    """Les cartes d'un style, au format des exemples du kit (plus `key`, `purpose`, `slots`)."""
    cards = _editing_os_index()["cards"].get(style)
    if cards is None:
        return None
    return [{**c, "name": c["file"], "hero": None,
             "url": f"/api/projects/library/animations/editing-os/{quote(c['file'])}"} for c in cards]


def editing_os_file(rel: str) -> Path | None:
    """Un fichier de l'import (carte, charte, police), sans sortir du dossier."""
    root = EDITING_OS_DIR.resolve()
    path = (root / rel).resolve()
    return path if root in path.parents and path.is_file() else None
