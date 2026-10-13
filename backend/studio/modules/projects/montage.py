"""
Montage de la vidéo longue : la timeline de travail, éditée à la main dans l'interface et par
le monteur (Claude, depuis le chat), puis exportée en FCPXML pour DaVinci Resolve.

Tout vit dans le dossier du projet, que Resolve lit tel quel (chemins absolus) :

  montage/timeline.json        la timeline (ci-dessous), source de vérité
  montage/motion/<id>.html     les compositions de motion design (HyperFrames), écrites par Claude
  montage/motion/renders/      leur rendu en .mov ProRes 4444 avec transparence
  montage/<titre>.fcpxml       l'export pour Resolve, refait à chaque modification
  montage/.history/            les états précédents de timeline.json, pour annuler
  montage/.revs/               les dernières versions écrites, par empreinte (fusionner une retouche faite sur l'une)
  montage/daryl/<demande>/     la copie de travail de Daryl pendant un tour du chat (timeline.json, contexte.md,
                               insertions.json), fusionnée à la fin du tour avec la timeline, que le client continue
                               de monter à la main (merge) ; plusieurs demandes tournent à la fois
  montage/.cache/              forme d'onde et vignettes de la vidéo source
  assets/<catégorie>/          B-roll, musique, sons : un son de la bibliothèque y est copié
                               dès qu'il entre dans la timeline

timeline.json (temps de la timeline en secondes, sauf `in` / `out` : temps dans le média) :

    {
      "aroll":   [{"id", "src"?, "in", "out", "transition", "gain_db"?}], # la vidéo source, bout à bout ; transition avec le précédent
      "zooms":   [{"id", "at", "dur", "scale", "x", "y", "beat"?}], # zoom sur l'A-roll ; x, y : décalage du centre (fraction)
      "broll":   [{"id", "src", "at", "in", "out", "enter"?, "exit"?, "beat"?}], # plans de coupe, au-dessus de l'A-roll (muets)
      "motion":  [{"id", "at", "dur", "title", "kind", "idea", "enter"?, "exit"?, "beat"?}],  # motion design, au-dessus du B-roll
      "audio":   [{"id", "src", "at", "in", "out", "gain_db", "role": "sfx" | "music", "motion"?}],
      "texts":   [{"id", "at", "dur", "text", "x", "y", "size", "color", "angle"}],  # texte écrit à la main, au-dessus de tout
      "markers": [{"id", "t", "text", "kind": "chapter" | "note", "by": "user" | "ai", "done"}]
    }

`beat` : le beat du storyboard dont vient l'élément. `motion` d'un son : le motion dont il fait le sound design ; il
le suit quand on le déplace et il est remplacé quand Daryl réécrit les sons du motion (beat_anim.place_sounds).
`transition`, `enter`, `exit` : une transition de la bibliothèque {"fx", "dur"} (transitions.py), ou null / absent
pour une coupe franche.
`texts` : une note écrite par le client (corriger une phrase mal audible, préciser un mot), en écriture manuscrite ;
x, y : le centre du texte en fraction de l'image (0 à 1) ; size : la hauteur de la police en fraction de la hauteur
de l'image ; color : « #RRGGBB » ; angle : en degrés (négatif : penché vers le haut à droite).
`src` d'un clip de l'A-roll : absent pour la vidéo source, sinon un autre média inséré (un extrait, une archive)
qui passe avec son propre son. `gain_db` d'un clip de l'A-roll : son volume (absent : 0 dB).
`src` : chemin relatif au projet (« assets/broll/x.mp4 »), ou « library/<catégorie>/<fichier> »
pour un média de la bibliothèque commune (copié dans le projet à l'enregistrement).
"""
import functools
import hashlib
import html
import json
import os
import re
import shutil
import time
from array import array
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ...core import jobs
from ..animations import kit
from . import library, media, service, transitions
from . import timeline as tl

MONTAGE_DIR = "montage"
TIMELINE_FILE = "timeline.json"
# les clips que Daryl demande d'insérer dans l'A-roll (insert_aroll), appliqués dès qu'il écrit le fichier
INSERTIONS_FILE = "insertions.json"
MOTION_DIR = "motion"
RENDERS_DIR = "renders"
# la page qui rend un motion (montage_tasks._index) entre dans sa signature : à monter quand elle change,
# les motions déjà rendus se refont
MOTION_PAGE_VERSION = 2
# les médias posés dans les compositions, copiés à côté d'elles (le rendu ne lit que montage/motion/)
MEDIA_DIR = "media"
HISTORY_DIR = ".history"
CACHE_DIR = ".cache"
HISTORY_MAX = 60
# les copies de travail de Daryl, une par demande en cours (daryl/<demande>/) ; dans chacune, WORK_BASE : la timeline
# et les compositions au début du tour, ses insertions ; RESERVED_FILE : les ids de motion qui lui sont réservés
WORK_DIR = "daryl"
WORK_BASE = ".depart"
RESERVED_FILE = "ids.json"
RESERVED = 10
# les demandes faites à Daryl : une file par place, SLOTS demandes traitées à la fois (la première garde le nom
# d'avant, pour les demandes déjà en base)
TASK_SLOTS = 3
TASK_KINDS = ["project_montage"] + [f"project_montage_{i}" for i in range(1, TASK_SLOTS)]
REVS_DIR = ".revs"
REVS_MAX = 30
# une écriture de la timeline à la fois (l'API et le worker sont deux processus)
LOCK_FILE = ".lock"
LOCK_STALE = 15
# dans un état de l'historique : les décalages des beats du storyboard faits juste après (à défaire avec lui)
SHIFTS_FILE = "beats-shift.json"
TRACKS = ("aroll", "zooms", "broll", "motion", "audio", "texts", "markers")
PREFIX = {"aroll": "a", "zooms": "z", "broll": "b", "motion": "m", "audio": "s", "texts": "t", "markers": "k"}
# texte posé à la main : bornes de la taille (fraction de la hauteur de l'image) et de l'inclinaison (degrés)
TEXT_SIZE = (0.03, 0.25)
TEXT_ANGLE = 20
# zoom : montée et descente progressives aux bords
ZOOM_RAMP = 0.4
# forme d'onde : une valeur par 1/PEAKS_RATE s
PEAKS_RATE = 20
# vignettes de la vidéo source : au plus FILMSTRIP_MAX images, une toutes les `step` s
FILMSTRIP_MAX = 900
FILMSTRIP_COLS = 30
FILMSTRIP_HEIGHT = 72


def root(pid: str) -> Path:
    return service.project_dir(pid) / MONTAGE_DIR


def motion_dir(pid: str) -> Path:
    return root(pid) / MOTION_DIR


def _source(project: dict) -> dict | None:
    source = project.get("source") or {}
    return source if source.get("path") and not source.get("pending") and Path(source["path"]).is_file() else None


@functools.lru_cache(maxsize=32)
def _fps(path: str, duration: float | None) -> float:
    return media.probe(Path(path)).get("fps") or 25


def source_fps(source: dict) -> float:
    """Les images par seconde de la source (lues une fois par fichier) : le pas de l'image par image."""
    return _fps(source["path"], source.get("duration"))


def empty(project: dict) -> dict:
    """La timeline de départ : la vidéo source entière."""
    source = _source(project)
    duration = (source or {}).get("duration") or 0.0
    return {"aroll": [{"id": "a1", "in": 0.0, "out": round(duration, 3), "transition": None}] if duration else [],
            "zooms": [], "broll": [], "motion": [], "audio": [], "texts": [], "markers": []}


def prepare(pid: str) -> None:
    """Le dossier du montage, avec la charte et les exemples de motion design."""
    # la charte est celle du projet (au départ, le design system du kit) ; les exemples suivent le kit
    kit.install(motion_dir(pid), keep_style=True)


# la charte du projet (style.css), ou une ancienne figée sous son empreinte (style-<empreinte>.css)
STYLE_FILE = "style.css"
_STYLE_LINK = re.compile(rb'href="(style(?:-[0-9a-f]{10})?\.css)"')


def style(pid: str) -> dict:
    """Le style du projet : les réglages de sa charte."""
    path = motion_dir(pid) / STYLE_FILE
    return kit.design_of(path.read_text(encoding="utf-8")) if path.is_file() else kit.design()


def set_style(pid: str, values: dict) -> None:
    """
    Change le style du projet : les motions écrits ensuite le prennent. Ceux qui existent gardent le leur : la
    charte d'avant est figée sous son empreinte et ils la chargent désormais (leur rendu reste valable).
    """
    with _locked(pid):
        prepare(pid)
        folder, current = motion_dir(pid), motion_dir(pid) / STYLE_FILE
        old = current.read_text(encoding="utf-8")
        new = kit.style_css(kit.clean(values, style(pid)))
        if new == old:
            return
        frozen = f"style-{hashlib.sha1(old.encode()).hexdigest()[:10]}.css"
        if not (folder / frozen).is_file():
            (folder / frozen).write_text(old, encoding="utf-8")
        for comp in folder.glob("*.html"):
            raw = comp.read_bytes()
            if f'href="{STYLE_FILE}"'.encode() in raw:
                comp.write_bytes(raw.replace(f'href="{STYLE_FILE}"'.encode(), f'href="{frozen}"'.encode()))
        current.write_text(new, encoding="utf-8")


def load(pid: str) -> dict:
    path = root(pid) / TIMELINE_FILE
    if path.is_file():
        try:
            timeline = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
        else:
            # une ancienne timeline : la transition de l'A-roll était la durée d'un fondu
            for c in timeline.get("aroll") or []:
                c["transition"] = transitions.clean(c.get("transition"))
            # une timeline d'avant une piste (les textes) : la piste est vide
            for track in TRACKS:
                timeline.setdefault(track, [])
            return timeline
    return empty(service.load(pid))


# --- Nettoyage : ce qu'écrivent l'interface et Claude ---------------------------------------

def _num(value, default: float = 0.0) -> float:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return default


def _resolve_src(pid: str, src: str) -> str | None:
    """Chemin relatif au projet d'un média de la timeline ; un média de la bibliothèque est copié dans le projet."""
    src = (src or "").replace("\\", "/").strip().lstrip("/")
    if not src or ".." in src.split("/"):
        return None
    if src.startswith("library/"):
        _, category, name = (src.split("/", 2) + ["", ""])[:3]
        origin = library.LIBRARY_DIR / category / name
        if category not in library.CATEGORIES or not origin.is_file():
            return None
        dest = service.project_dir(pid) / service.ASSETS_DIR / category / name
        if not dest.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, dest)
        return f"{service.ASSETS_DIR}/{category}/{name}"
    return src if (service.project_dir(pid) / src).is_file() else None


def _ends(item: dict) -> dict:
    """L'entrée et la sortie d'un B-roll ou d'un motion, quand elles ne sont pas des coupes franches."""
    return {k: v for k in ("enter", "exit") if (v := transitions.clean(item.get(k)))}


def clean(pid: str, raw: dict, source_duration: float) -> dict:
    """Une timeline sûre : ids uniques, nombres, bornes, médias présents dans le projet."""
    out: dict = {t: [] for t in TRACKS}
    seen: set[str] = set()

    def ident(track: str, value) -> str:
        value = str(value or "")
        if not re.fullmatch(r"[\w-]{1,40}", value) or value in seen:
            n = 1
            while f"{PREFIX[track]}{n}" in seen:
                n += 1
            value = f"{PREFIX[track]}{n}"
        seen.add(value)
        return value

    durations: dict[str, float] = {}

    def length(src: str) -> float:
        if src not in durations:
            durations[src] = media.probe(service.project_dir(pid) / src).get("duration") or 0.0
        return durations[src]

    for c in raw.get("aroll") or []:
        # un clip inséré d'un autre média : borné par sa durée ; un média introuvable, le clip disparaît
        src = _resolve_src(pid, str(c["src"])) if c.get("src") else None
        if c.get("src") and not src:
            continue
        a, b = max(0.0, _num(c.get("in"))), min(_num(c.get("out")), (length(src) if src else source_duration) or 1e9)
        gain = max(-60.0, min(_num(c.get("gain_db")), 12.0))
        if b - a >= 0.04:
            out["aroll"].append({"id": ident("aroll", c.get("id")), **({"src": src} if src else {}), "in": a, "out": b,
                                 "transition": transitions.clean(c.get("transition")), **({"gain_db": gain} if gain else {})})
    total = sum(c["out"] - c["in"] for c in out["aroll"])

    for z in raw.get("zooms") or []:
        at, dur = max(0.0, _num(z.get("at"))), _num(z.get("dur"))
        if dur >= 0.2 and at < total:
            out["zooms"].append({"id": ident("zooms", z.get("id")), "at": at, "dur": min(dur, total - at),
                                 "scale": max(1.0, min(_num(z.get("scale"), 1.2), 3.0)),
                                 "x": max(-0.5, min(_num(z.get("x")), 0.5)), "y": max(-0.5, min(_num(z.get("y")), 0.5)),
                                 **({"beat": str(z["beat"])[:20]} if z.get("beat") else {})})

    for track in ("broll", "audio"):
        for item in raw.get(track) or []:
            src = _resolve_src(pid, item.get("src"))
            if not src:
                continue
            a = max(0.0, _num(item.get("in")))
            b = _num(item.get("out"), a + 3)
            limit = length(src)
            if limit:
                b = min(b, limit)
            at = max(0.0, _num(item.get("at")))
            if b - a < 0.04 or at >= total:
                continue
            entry = {"id": ident(track, item.get("id")), "src": src, "at": at, "in": a, "out": b}
            if track == "broll":
                entry.update(_ends(item))
            if track == "broll" and item.get("beat"):
                # le beat du storyboard dont il vient
                entry["beat"] = str(item["beat"])[:20]
            if track == "audio":
                entry["gain_db"] = max(-60.0, min(_num(item.get("gain_db")), 12.0))
                entry["role"] = "music" if item.get("role") == "music" else "sfx"
                if item.get("motion"):
                    entry["motion"] = str(item["motion"])[:20]
            out[track].append(entry)

    for m in raw.get("motion") or []:
        at, dur = max(0.0, _num(m.get("at"))), _num(m.get("dur"), 4)
        if dur >= 0.3 and at < total:
            out["motion"].append({"id": ident("motion", m.get("id")), "at": at, "dur": dur,
                                  "title": str(m.get("title") or "")[:120], "kind": str(m.get("kind") or "")[:60],
                                  "idea": str(m.get("idea") or "")[:600], **_ends(m),
                                  # le beat du storyboard dont il vient
                                  **({"beat": str(m["beat"])[:20]} if m.get("beat") else {})})

    for x in raw.get("texts") or []:
        at, dur = max(0.0, _num(x.get("at"))), _num(x.get("dur"), 3)
        text = str(x.get("text") or "").replace("\r", "")[:400]
        color = str(x.get("color") or "")
        if dur >= 0.2 and at < total:
            out["texts"].append({"id": ident("texts", x.get("id")), "at": at, "dur": min(dur, total - at), "text": text,
                                 "x": max(0.0, min(_num(x.get("x"), 0.5), 1.0)), "y": max(0.0, min(_num(x.get("y"), 0.8), 1.0)),
                                 "size": max(TEXT_SIZE[0], min(_num(x.get("size"), 0.075), TEXT_SIZE[1])),
                                 "color": color.upper() if re.fullmatch(r"#[0-9a-fA-F]{6}", color) else "#FFFFFF",
                                 "angle": max(-TEXT_ANGLE, min(_num(x.get("angle")), TEXT_ANGLE))})

    for k in raw.get("markers") or []:
        t = max(0.0, _num(k.get("t")))
        if t <= total:
            out["markers"].append({"id": ident("markers", k.get("id")), "t": t, "text": str(k.get("text") or "")[:300],
                                   "kind": "chapter" if k.get("kind") == "chapter" else "note",
                                   "by": "ai" if k.get("by") == "ai" else "user", "done": bool(k.get("done"))})

    for track in ("zooms", "broll", "motion", "audio", "texts"):
        out[track].sort(key=lambda x: x["at"])
    out["markers"].sort(key=lambda x: x["t"])
    return out


# --- Insérer un clip dans l'A-roll (comme ops.insertAroll dans l'interface) ----------------------

MIN_CUT = 0.1


def _new_id(timeline: dict, prefix: str) -> str:
    used = {x["id"] for track in TRACKS for x in timeline.get(track) or []}
    n = 1
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


def insert_aroll(timeline: dict, at: float, clip: dict) -> dict:
    """
    Insère dans l'A-roll, à l'instant `at` de la timeline, un clip d'un autre média ({src, in, out, gain_db?}) : coupe
    à `at` (ou sur la coupe toute proche), puis décale de sa durée tout ce qui suit. Un B-roll, un son ou un zoom à
    cheval est coupé en deux : sa suite reprend après le clip. Modifie `timeline` ; rend {id, at, length}.
    """
    aroll = timeline["aroll"]
    starts, cursor = [], 0.0
    for c in aroll:
        starts.append(cursor)
        cursor += c["out"] - c["in"]
    at = max(0.0, min(float(at), cursor))
    i = next((k for k, s in enumerate(starts) if abs(s - at) <= MIN_CUT), None)
    if i is not None:
        at = starts[i]
    elif at >= cursor - MIN_CUT:
        i, at = len(aroll), cursor
    else:
        k = max(n for n, s in enumerate(starts) if s <= at)
        c, cut = aroll[k], round(aroll[k]["in"] + at - starts[k], 3)
        aroll[k:k + 1] = [{**c, "out": cut}, {**c, "id": _new_id(timeline, PREFIX["aroll"]), "in": cut, "transition": None}]
        i = k + 1
    at = round(at, 3)
    length = round(clip["out"] - clip["in"], 3)
    for track in ("zooms", "broll", "audio"):
        items = []
        for x in timeline[track]:
            end = x["at"] + (x["dur"] if track == "zooms" else x["out"] - x["in"])
            if not x["at"] + MIN_CUT < at < end - MIN_CUT:
                items.append(x)
            elif track == "zooms":
                items += [{**x, "dur": round(at - x["at"], 3)},
                          {**x, "id": _new_id(timeline, PREFIX[track]), "at": at, "dur": round(end - at, 3)}]
            else:
                cut = round(x["in"] + at - x["at"], 3)
                items += [{**x, "out": cut}, {**x, "id": _new_id(timeline, PREFIX[track]), "at": at, "in": cut}]
        timeline[track] = items
    for track in ("zooms", "broll", "motion", "audio", "texts"):
        for x in timeline.get(track) or []:
            if x["at"] >= at:
                x["at"] = round(x["at"] + length, 3)
    for k in timeline["markers"]:
        if k["t"] >= at:
            k["t"] = round(k["t"] + length, 3)
    # la transition éventuelle était avec l'ancien voisin : le clip inséré arrive et repart en coupe franche
    if i < len(aroll):
        aroll[i]["transition"] = None
    new = {"id": _new_id(timeline, PREFIX["aroll"]), "src": clip["src"], "in": round(clip["in"], 3),
           "out": round(clip["out"], 3), "transition": None}
    if clip.get("gain_db"):
        new["gain_db"] = clip["gain_db"]
    aroll.insert(i, new)
    return {"id": new["id"], "at": at, "length": length}


def _shift_beats(pid: str, at: float, length: float) -> None:
    """Décale de `length` les beats du storyboard qui commencent à partir de `at`."""
    from . import storyboard

    board = storyboard.load(pid)
    if not board:
        return
    moved = False
    for b in board.get("beats", []):
        if b.get("at", 0) >= at - 1e-3:
            b["at"] = round(b["at"] + length, 3)
            moved = True
    if moved:
        storyboard.save(pid, board)


def shift_beats(pid: str, at: float, length: float) -> None:
    """
    Les beats du storyboard suivent une insertion dans l'A-roll. Le décalage est noté dans le dernier état de
    l'historique (celui d'avant la modification) : l'annuler le défait aussi.
    """
    _shift_beats(pid, at, length)
    steps = history_steps(pid)
    if steps:
        file = steps[-1] / SHIFTS_FILE
        done = json.loads(file.read_text(encoding="utf-8")) if file.is_file() else []
        file.write_text(json.dumps(done + [{"at": at, "length": length}]), encoding="utf-8")


def apply_insertions(pid: str, task: str) -> list[str]:
    """
    Les clips que Daryl a demandé d'insérer pour la demande `task` (insertions.json dans son dossier de travail :
    [{src, at, in, out, gain_db?}], `at` en temps
    de la timeline au moment où il écrit le fichier) : insérés dans sa copie de travail l'un après l'autre, du dernier
    au premier pour que les temps restent justes. Les beats du storyboard ne suivent qu'à la fin du tour, si son A-roll
    est gardé (finish_work). Le fichier est effacé ; rend ce qui n'a pas pu l'être.
    """
    file = work_dir(pid, task) / INSERTIONS_FILE
    if not file.is_file():
        return []
    try:
        wanted = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        file.unlink(missing_ok=True)
        return [f"insertions.json illisible : {e}"]
    file.unlink(missing_ok=True)
    if isinstance(wanted, dict):
        wanted = [wanted]
    project = service.load(pid)
    duration = (_source(project) or {}).get("duration") or 0.0
    timeline = clean(pid, _read(work_file(pid, task)) or load(pid), duration)
    problems, shifts = [], []
    for w in sorted((w for w in wanted if isinstance(w, dict)), key=lambda w: -_num(w.get("at"))):
        src = _resolve_src(pid, str(w.get("src") or ""))
        if not src:
            problems.append(f"média introuvable : {w.get('src')}")
            continue
        limit = media.probe(service.project_dir(pid) / src).get("duration") or 0.0
        a = max(0.0, _num(w.get("in")))
        b = min(_num(w.get("out"), limit or a + 4), limit or 1e9)
        if b - a < 0.04:
            problems.append(f"plage vide pour {src}")
            continue
        done = insert_aroll(timeline, _num(w.get("at")), {"src": src, "in": a, "out": b, "gain_db": _num(w.get("gain_db"))})
        shifts.append({"at": done["at"], "length": done["length"]})
    _dump(work_file(pid, task), clean(pid, timeline, duration))
    noted = work_dir(pid, task) / WORK_BASE / SHIFTS_FILE
    before = json.loads(noted.read_text(encoding="utf-8")) if noted.is_file() else []
    noted.write_text(json.dumps(before + shifts), encoding="utf-8")
    return problems


# --- Enregistrement, historique --------------------------------------------------------------

def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _dump(path: Path, timeline: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _write(pid: str, timeline: dict) -> None:
    _dump(root(pid) / TIMELINE_FILE, timeline)
    rev(pid)
    kept = sorted((root(pid) / REVS_DIR).glob("*.json"), key=lambda p: p.stat().st_mtime)
    for old in kept[:-REVS_MAX]:
        old.unlink(missing_ok=True)


def rev(pid: str) -> str:
    """L'empreinte de la timeline enregistrée (« » sans fichier). La version est gardée : une retouche faite sur elle
    pourra être fusionnée dans une version plus récente."""
    path = root(pid) / TIMELINE_FILE
    if not path.is_file():
        return ""
    data = path.read_bytes()
    key = hashlib.sha1(data).hexdigest()[:16]
    copy = root(pid) / REVS_DIR / f"{key}.json"
    if not copy.is_file():
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(data)
    return key


@contextmanager
def _locked(pid: str) -> Iterator[None]:
    """Une écriture de la timeline à la fois, entre l'API et le worker ; un verrou oublié expire."""
    path = root(pid) / LOCK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, deadline = None, time.time() + LOCK_STALE
    while fd is None:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except (FileExistsError, PermissionError):
            try:
                stale = time.time() - path.stat().st_mtime > LOCK_STALE
            except OSError:
                continue
            if stale or time.time() > deadline:
                path.unlink(missing_ok=True)
            else:
                time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        path.unlink(missing_ok=True)


def snapshot(pid: str, motions: list[Path] | None = None) -> None:
    """Garde l'état actuel de la timeline (et des compositions : seulement `motions` si donné) avant une modification."""
    path = root(pid) / TIMELINE_FILE
    if not path.is_file():
        return
    history = root(pid) / HISTORY_DIR
    n = max((int(p.name) for p in history.iterdir() if p.name.isdigit()), default=0) + 1 if history.is_dir() else 1
    target = history / str(n)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target / TIMELINE_FILE)
    for comp in motion_dir(pid).glob("*.html") if motions is None else motions:
        (target / MOTION_DIR).mkdir(exist_ok=True)
        shutil.copy2(comp, target / MOTION_DIR / comp.name)
    for old in sorted((p for p in history.iterdir() if p.name.isdigit()), key=lambda p: int(p.name))[:-HISTORY_MAX]:
        shutil.rmtree(old, ignore_errors=True)


def history_steps(pid: str) -> list[Path]:
    history = root(pid) / HISTORY_DIR
    return sorted((p for p in history.iterdir() if p.name.isdigit()), key=lambda p: int(p.name)) if history.is_dir() else []


def undo(pid: str, motions: bool = True) -> None:
    """Revient à l'état d'avant la dernière modification. `motions` faux : les compositions restent telles quelles
    (Daryl est en train d'en écrire)."""
    with _locked(pid):
        steps = history_steps(pid)
        if not steps:
            raise ValueError("rien à annuler")
        last = steps[-1]
        shutil.copy2(last / TIMELINE_FILE, root(pid) / TIMELINE_FILE)
        rev(pid)
        # les beats du storyboard décalés par une insertion reviennent à leur place (le reste du storyboard est gardé)
        if (last / SHIFTS_FILE).is_file():
            for shift in reversed(json.loads((last / SHIFTS_FILE).read_text(encoding="utf-8"))):
                _shift_beats(pid, shift["at"] + shift["length"], -shift["length"])
        if motions and (last / MOTION_DIR).is_dir():
            for comp in (last / MOTION_DIR).glob("*.html"):
                shutil.copy2(comp, motion_dir(pid) / comp.name)
        shutil.rmtree(last, ignore_errors=True)


def save(pid: str, raw: dict, keep_history: bool = True, shifts: list[dict] | None = None, base: str | None = None) -> dict:
    """
    Enregistre une timeline venue de l'interface : nettoyée, historisée, exportée. `shifts` : les insertions dans
    l'A-roll qu'elle contient ([{at, length}]), que les beats du storyboard suivent. `base` : l'empreinte de la version
    retouchée ; si la timeline a changé depuis (le tour de Daryl vient d'y être fusionné), la retouche y est fusionnée.
    """
    project = service.load(pid)
    duration = (_source(project) or {}).get("duration") or 0.0
    cleaned = clean(pid, raw, duration)
    with _locked(pid):
        older = _read(root(pid) / REVS_DIR / f"{base}.json") if base and base != rev(pid) else None
        if older is not None:
            cleaned = clean(pid, merge(older, cleaned, load(pid))[0], duration)
        if keep_history:
            snapshot(pid)
        _write(pid, cleaned)
        for shift in shifts or []:
            # sans historique, rien à défaire : on décale seulement
            (shift_beats if keep_history else _shift_beats)(pid, _num(shift.get("at")), _num(shift.get("length")))
    after_change(pid)
    return cleaned


# --- La copie de travail de Daryl ------------------------------------------------------------

def task_slot() -> str:
    """La file la moins chargée pour une demande à Daryl (tous projets confondus)."""
    load_ = {k: 0 for k in TASK_KINDS}
    for j in jobs.list_jobs(service.MODULE):
        if j.kind in load_ and not j.finished:
            load_[j.kind] += 1
    return min(TASK_KINDS, key=lambda k: load_[k])


def work_dir(pid: str, task: str) -> Path:
    """Le dossier de travail de Daryl pour une demande : sa copie de la timeline, son contexte, ses insertions."""
    return root(pid) / WORK_DIR / task


def work_file(pid: str, task: str) -> Path:
    return work_dir(pid, task) / TIMELINE_FILE


def _motion_numbers(timeline: dict | None) -> set[int]:
    return {int(m["id"][1:]) for m in (timeline or {}).get("motion") or [] if re.fullmatch(r"m\d+", str(m.get("id")))}


def start_work(pid: str, task: str) -> list[str]:
    """
    Début d'un tour du chat : Daryl reçoit une copie de la timeline ; l'état de départ (timeline et compositions)
    est gardé pour la fusion et pour annuler son tour. D'autres demandes tournent peut-être en même temps : il reçoit
    des ids de motion à lui (pas deux fois le même fichier de composition). Rend ces ids.
    """
    with _locked(pid):
        work = work_dir(pid, task)
        shutil.rmtree(work, ignore_errors=True)
        (work / WORK_BASE / MOTION_DIR).mkdir(parents=True)
        timeline = load(pid)
        _dump(work / TIMELINE_FILE, timeline)
        _dump(work / WORK_BASE / TIMELINE_FILE, timeline)
        for comp in motion_dir(pid).glob("*.html"):
            shutil.copy2(comp, work / WORK_BASE / MOTION_DIR / comp.name)
        # au-delà de tout ce qui existe ou est réservé par les autres demandes en cours
        used = _motion_numbers(timeline) | {int(p.stem[1:]) for p in motion_dir(pid).glob("m*.html") if p.stem[1:].isdigit()}
        for other in (root(pid) / WORK_DIR).iterdir():
            used |= _motion_numbers(_read(other / TIMELINE_FILE))
            used |= {int(i[1:]) for i in json.loads((other / RESERVED_FILE).read_text(encoding="utf-8"))} \
                if (other / RESERVED_FILE).is_file() else set()
        n = max(used, default=0) + 1
        ids = [f"m{n + i}" for i in range(RESERVED)]
        (work / RESERVED_FILE).write_text(json.dumps(ids), encoding="utf-8")
    return ids


def finish_work(pid: str, task: str, touched: set[str]) -> tuple[bool, list[str]]:
    """
    Fin d'un tour : la copie de Daryl est fusionnée dans la timeline, que le client (et les autres demandes finies
    entre-temps) a pu changer pendant ce temps : la timeline gagne quand les deux ont changé la même chose. `touched` :
    les compositions qu'il a écrites (noms de fichiers). L'état d'avant est historisé : annuler défait ce tour, pas le
    reste. Rend (quelque chose a changé, ce qui n'a pas pu être pris).
    """
    work = work_dir(pid, task)
    base, theirs = _read(work / WORK_BASE / TIMELINE_FILE), _read(work / TIMELINE_FILE)
    if base is None or theirs is None:
        return False, []
    before = {name: work / WORK_BASE / MOTION_DIR / name for name in touched}
    motions_changed = any(not p.is_file() or not (motion_dir(pid) / p.name).is_file()
                          or p.read_bytes() != (motion_dir(pid) / p.name).read_bytes() for p in before.values())
    project = service.load(pid)
    duration = (_source(project) or {}).get("duration") or 0.0
    theirs = clean(pid, theirs, duration)
    noted = work / WORK_BASE / SHIFTS_FILE
    shifts = json.loads(noted.read_text(encoding="utf-8")) if noted.is_file() else []
    notes: list[str] = []
    changed = motions_changed or theirs != clean(pid, base, duration)
    if changed:
        with _locked(pid):
            merged, notes, renamed = merge(base, load(pid), theirs)
            for old, new in renamed.items():
                comp = motion_dir(pid) / f"{old}.html"
                if comp.is_file():
                    comp.replace(motion_dir(pid) / f"{new}.html")
            # les compositions qu'il a retouchées, telles qu'avant son tour
            snapshot(pid, [p for p in before.values() if p.is_file()])
            _write(pid, clean(pid, merged, duration))
            # ses insertions dans l'A-roll sont gardées : les beats du storyboard les suivent
            if _shape(merged["aroll"]) == _shape(theirs["aroll"]):
                for shift in shifts:
                    shift_beats(pid, shift["at"], shift["length"])
            elif shifts:
                notes.append("le clip que j'ai inséré dans l'A-roll n'y est pas (ta version de l'A-roll est gardée) : redemande-le")
    shutil.rmtree(work, ignore_errors=True)
    return changed, notes


# --- Fusion de deux versions de la timeline ------------------------------------------------------
# Les éléments se retrouvent par leur id. Ceux du dessus de l'A-roll sont repérés par le moment de la vidéo où ils
# commencent (le média, le temps dans le média) : une coupe ou une insertion d'un côté ne les fait pas bouger de l'autre.

TRACK_LABEL = {"aroll": "le clip", "zooms": "le zoom", "broll": "le B-roll", "motion": "le motion", "audio": "le son",
               "texts": "le texte", "markers": "le marqueur"}
# ce qui fait la forme de l'A-roll (le reste d'un clip : sa transition, son volume)
SHAPE = ("src", "in", "out")
_MISSING = object()


def _shape(aroll: list[dict]) -> list[tuple]:
    return [(c["id"], c.get("src"), c["in"], c["out"]) for c in aroll]


def _starts(aroll: list[dict]) -> list[float]:
    out, cursor = [], 0.0
    for c in aroll:
        out.append(cursor)
        cursor += c["out"] - c["in"]
    return out


def _anchor(aroll: list[dict], starts: list[float], t: float) -> tuple | None:
    """L'instant `t` de la timeline dans la vidéo : (média, temps dans le média, clip)."""
    if not aroll:
        return None
    k = max((i for i, s in enumerate(starts) if s <= t + 1e-6), default=0)
    c = aroll[k]
    return (c.get("src") or "", round(c["in"] + min(max(t - starts[k], 0.0), c["out"] - c["in"]), 3), c["id"])


def _place(aroll: list[dict], starts: list[float], anchor: tuple) -> float | None:
    """L'instant de la timeline où passe ce moment de la vidéo (dans le même clip de préférence) ; None s'il est coupé."""
    src, s, cid = anchor
    fits = [k for k, c in enumerate(aroll) if (c.get("src") or "") == src and c["in"] - 1e-3 <= s <= c["out"] + 1e-3]
    if not fits:
        return None
    k = next((k for k in fits if aroll[k]["id"] == cid), fits[0])
    return round(starts[k] + s - aroll[k]["in"], 3)


def _eq(a, b) -> bool:
    """Égaux, un moment de la vidéo comparé sans son clip (une coupe change le clip, pas le moment)."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_eq(a[k], b[k]) for k in a)
    if isinstance(a, tuple) and isinstance(b, tuple):
        return a[:2] == b[:2]
    return a == b


def _merge_item(b, o, t) -> tuple[dict | None, list[str]]:
    """Un élément dans les trois versions (None : absent) ; rend la version fusionnée et les champs où les deux côtés
    l'ont changé différemment (« * » : supprimé d'un côté, retouché de l'autre)."""
    if _eq(o, t) or _eq(t, b):
        return o, []
    if _eq(o, b):
        return t, []
    if o is None or t is None or b is None:
        return o, ["*"]
    out, lost = {}, []
    for k in list(o) + [k for k in t if k not in o]:
        ov, tv, bv = o.get(k, _MISSING), t.get(k, _MISSING), b.get(k, _MISSING)
        if _eq(ov, bv) and not _eq(tv, bv):
            v = tv
        else:
            v = ov
            if not (_eq(ov, tv) or _eq(tv, bv)):
                lost.append(k)
        if v is not _MISSING:
            out[k] = v
    return out, lost


def merge(base: dict, ours: dict, theirs: dict) -> tuple[dict, list[str], dict[str, str]]:
    """
    Fusionne deux versions de la timeline nées de `base` : `ours` (celle du client), `theirs` (celle de Daryl). Ce
    qu'un seul côté a changé est pris ; ce que les deux ont changé, `ours` le garde. Rend (la timeline, ce qui n'a pas
    été pris de `theirs`, les motions de `theirs` renommés : {ancien id: nouveau}).
    """
    notes: list[str] = []
    renamed: dict[str, str] = {}
    sides = [{track: list(v.get(track) or []) for track in TRACKS} for v in (base, ours, theirs)]
    kept = "tu l'as modifié pendant ce temps, ta version est gardée"

    # l'A-roll : sa forme (ordre, bornes) vient d'un côté ; transitions et volumes, des deux
    b_ar, o_ar, t_ar = (s["aroll"] for s in sides)
    shape = t_ar if _shape(o_ar) == _shape(b_ar) else o_ar
    if _shape(t_ar) not in (_shape(b_ar), _shape(o_ar)) and shape is o_ar:
        notes.append("tu as retouché l'A-roll pendant ce temps : ta version de l'A-roll est gardée")
    by = [{c["id"]: {k: v for k, v in c.items() if k not in SHAPE} for c in s["aroll"]} for s in sides]
    aroll = []
    for c in shape:
        b, o, t = (x.get(c["id"]) for x in by)
        m, lost = _merge_item(b, o, t) if o is not None and t is not None else (None, [])
        notes += [f"{TRACK_LABEL['aroll']} {c['id']} ({k}) : {kept}" for k in lost if k != "*"]
        aroll.append({**(m or o or t), **{k: c[k] for k in SHAPE if k in c}})
    starts = _starts(aroll)

    used = {x["id"] for s in sides for track in TRACKS for x in s[track]}
    out: dict = {"aroll": aroll}
    for track in TRACKS[1:]:
        pos = "t" if track == "markers" else "at"
        # l'instant de chaque élément devient un moment de la vidéo, le temps de fusionner
        b_items, o_items, t_items = ({x["id"]: {**x, pos: _anchor(s["aroll"], _starts(s["aroll"]), x[pos]) or x[pos]}
                                      for x in s[track]} for s in sides)
        # un même id ajouté des deux côtés : l'élément de Daryl en prend un autre
        for i in [i for i in t_items if i in o_items and i not in b_items and not _eq(o_items[i], t_items[i])]:
            n = 1
            while f"{PREFIX[track]}{n}" in used:
                n += 1
            used.add(new := f"{PREFIX[track]}{n}")
            t_items[new] = {**t_items.pop(i), "id": new}
            if track == "motion":
                renamed[i] = new
        items = []
        for i in [*o_items, *(i for i in t_items if i not in o_items), *(i for i in b_items if i not in o_items and i not in t_items)]:
            m, lost = _merge_item(b_items.get(i), o_items.get(i), t_items.get(i))
            if lost:
                notes.append(f"{TRACK_LABEL[track]} {i}" + ("" if lost == ["*"] else f" ({', '.join(lost)})") + f" : {kept}")
            if m is None:
                continue
            if isinstance(m[pos], tuple):
                at = _place(aroll, starts, m[pos])
                if at is None:
                    if i not in o_items:
                        notes.append(f"{TRACK_LABEL[track]} {i} : son passage de l'A-roll a été coupé, il n'est pas gardé")
                    continue
                m = {**m, pos: at}
            items.append(m)
        out[track] = items
    return out, notes, renamed


def after_change(pid: str) -> None:
    """Après une modification : rendre les motions nouvelles ou retouchées, refaire l'export."""
    enqueue_motion_renders(pid)
    try:
        export(pid)
    except Exception:  # noqa: BLE001 - un export raté ne doit pas empêcher d'enregistrer
        pass


# --- Motion design : rendu des compositions en .mov avec transparence ------------------------

# un média posé dans une composition : <video src="media/m3-x.mp4" data-from="library/broll/x.mp4">
_MEDIA_TAG = re.compile(r"<(?:video|img|audio|source)\b[^>]*>", re.I)


def _attr(tag: str, name: str) -> str:
    found = re.search(rf"""\s{name}\s*=\s*(?:"([^"]*)"|'([^']*)')""", tag, re.I)
    return html.unescape(found.group(1) or found.group(2) or "").strip() if found else ""


def _media_origin(pid: str, src: str) -> Path | None:
    """Le fichier d'un média listé dans contexte.md (« library/… » ou un chemin du projet)."""
    src = src.replace("\\", "/").strip().lstrip("/")
    if not src or ".." in src.split("/"):
        return None
    if src.startswith("library/"):
        path = library.LIBRARY_DIR / src[len("library/"):]
    else:
        path = service.project_dir(pid) / src
    return path if path.is_file() else None


def bring_media(pid: str, comp: str) -> list[str]:
    """Copie à côté de la composition (montage/motion/media/) les médias qu'elle pose, depuis le projet ou la
    bibliothèque : le rendu ne lit que ce dossier. Rend ce qui manque toujours."""
    path = motion_dir(pid) / comp
    if not path.is_file():
        return []
    missing = []
    for tag in _MEDIA_TAG.findall(path.read_text(encoding="utf-8")):
        src = _attr(tag, "src").split("?")[0].split("#")[0]
        if not src.startswith(f"{MEDIA_DIR}/") or ".." in src.split("/"):
            continue
        dest = motion_dir(pid) / src
        origin = _media_origin(pid, _attr(tag, "data-from"))
        if origin and (not dest.is_file() or dest.stat().st_size != origin.stat().st_size):
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, dest)
        if not dest.is_file():
            missing.append(f"{path.stem} : média introuvable ({_attr(tag, 'data-from') or src})")
    return missing


def motion_signature(pid: str, item: dict) -> str | None:
    comp = motion_dir(pid) / f"{item['id']}.html"
    if not comp.is_file():
        return None
    raw = comp.read_bytes()
    # la charte qu'elle charge compte, pas son nom : figer une charte (changement de style) ne relance aucun rendu
    link = _STYLE_LINK.search(raw)
    style = motion_dir(pid) / (link.group(1).decode() if link else STYLE_FILE)
    body = _STYLE_LINK.sub(f'href="{STYLE_FILE}"'.encode(), raw) + json.dumps([item["dur"], MOTION_PAGE_VERSION]).encode()
    if style.is_file():
        body += style.read_bytes()
    return hashlib.sha1(body).hexdigest()[:12]


def motion_render_file(pid: str, item_id: str, signature: str) -> Path:
    return motion_dir(pid) / RENDERS_DIR / f"{item_id}-{signature}.mov"


def motion_jobs(pid: str) -> dict[str, jobs.Job]:
    """Le dernier rendu de chaque motion (par id)."""
    found = {}
    for j in jobs.list_jobs(service.MODULE):
        if j.kind == "project_motion_render" and j.payload.get("project") == pid:
            found[j.payload["motion"]] = j
    return found


def enqueue_motion_renders(pid: str) -> None:
    timeline = load(pid)
    current = motion_jobs(pid)
    size = _size(service.load(pid))
    for item in timeline["motion"]:
        sig = motion_signature(pid, item)
        if not sig or motion_render_file(pid, item["id"], sig).is_file():
            continue
        job = current.get(item["id"])
        if job and job.payload.get("signature") == sig and job.status not in ("error", "cancelled"):
            continue
        if job and not job.finished:
            jobs.cancel(job)
        jobs.create(service.MODULE, "project_motion_render",
                    {"project": pid, "motion": item["id"], "signature": sig, "duration": item["dur"],
                     "width": size[0], "height": size[1]}, {})


def motion_states(pid: str, timeline: dict) -> dict[str, dict]:
    """Pour chaque motion : sa composition, et où en est son rendu."""
    current = motion_jobs(pid)
    out = {}
    for item in timeline["motion"]:
        sig = motion_signature(pid, item)
        job = current.get(item["id"])
        ready = bool(sig) and motion_render_file(pid, item["id"], sig).is_file()
        state = "ready" if ready else "none" if not sig else (job.status if job and job.payload.get("signature") == sig else "queued")
        comp = motion_dir(pid) / f"{item['id']}.html"
        out[item["id"]] = {
            "html": f"/api/projects/{pid}/files/{MONTAGE_DIR}/{MOTION_DIR}/{item['id']}.html?v={int(comp.stat().st_mtime * 1000)}"
            if comp.is_file() else None,
            "render": state, "progress": job.progress if job and not ready else (1.0 if ready else 0.0),
            "error": job.error if job and state == "error" else None,
        }
    return out


def _size(project: dict) -> tuple[int, int]:
    source = _source(project) or {}
    return source.get("width") or 1920, source.get("height") or 1080


# --- Export FCPXML -------------------------------------------------------------------------

def _zoom_at(zooms: list[dict], t: float) -> dict:
    """Le recadrage à l'instant `t` de la timeline (montée et descente linéaires)."""
    for z in zooms:
        a, b = z["at"], z["at"] + z["dur"]
        if a <= t <= b:
            ramp = min(ZOOM_RAMP, z["dur"] / 3)
            k = min(1.0, (t - a) / ramp, (b - t) / ramp) if ramp else 1.0
            return {"scale": round(1 + (z["scale"] - 1) * k, 4), "x": round(z["x"] * k, 4), "y": round(z["y"] * k, 4)}
    return {"scale": 1.0, "x": 0.0, "y": 0.0}


def _zoom_keys(zooms: list[dict], clip_start: float, clip_len: float) -> list[dict]:
    """Les zooms qui touchent un clip, en images clés relatives au début du clip."""
    keys: list[dict] = []
    for z in zooms:
        a, b = z["at"], z["at"] + z["dur"]
        if b <= clip_start or a >= clip_start + clip_len:
            continue
        ramp = min(ZOOM_RAMP, z["dur"] / 3)
        for t in (a, a + ramp, b - ramp, b):
            local = t - clip_start
            if 0 < local < clip_len:
                keys.append({"t": round(local, 3), **_zoom_at(zooms, t)})
    if keys:
        # un zoom déjà commencé (ou pas fini) à la coupe : le clip démarre (finit) au bon cadrage
        keys.insert(0, {"t": 0.0, **_zoom_at(zooms, clip_start)})
        keys.append({"t": round(clip_len, 3), **_zoom_at(zooms, clip_start + clip_len)})
    return keys


def build(pid: str) -> tuple[dict, list[str]]:
    """La timeline au format d'export (timeline.py), et ce qui n'a pas pu y entrer."""
    project = service.load(pid)
    source = _source(project)
    if not source:
        raise ValueError("pas de vidéo source")
    timeline = load(pid)
    problems = []
    src_asset = tl.asset(source["path"], source["name"])
    info = media.probe(Path(source["path"]))
    out = {"fps_num": info.get("fps_num") or 25, "fps_den": info.get("fps_den") or 1,
           "width": source.get("width") or 1920, "height": source.get("height") or 1080,
           "assets": {"source": src_asset}, "clips": [], "audio": [], "video": [], "markers": []}
    base = service.project_dir(pid)

    def asset_key(path: Path) -> str:
        key = hashlib.sha1(str(path).encode()).hexdigest()[:10]
        if key not in out["assets"]:
            out["assets"][key] = tl.asset(path)
        return key

    cursor = 0.0
    for c in timeline["aroll"]:
        clip = {"asset": asset_key(base / c["src"]) if c.get("src") else "source", "in": c["in"], "out": c["out"]}
        if c.get("gain_db"):
            clip["gain_db"] = c["gain_db"]
        keys = _zoom_keys(timeline["zooms"], cursor, c["out"] - c["in"])
        if keys:
            clip["zoom"] = keys
        if c.get("transition") and out["clips"]:
            # Resolve ne relit que le fondu enchaîné : les autres transitions y arrivent en fondu
            clip["transition"] = {"type": "dissolve", "duration": c["transition"]["dur"]}
            if c["transition"]["fx"] != "fade":
                problems.append(f"transition « {transitions.label(c['transition']['fx'])} » à {cursor:.1f} s : "
                                "un fondu enchaîné dans Resolve (exacte dans le rendu du studio)")
        out["clips"].append(clip)
        cursor += c["out"] - c["in"]

    for b in timeline["broll"]:
        out["video"].append({"asset": asset_key(base / b["src"]), "at": b["at"], "in": b["in"], "out": b["out"],
                             "lane": 1, "mute": True})
    for m in timeline["motion"]:
        sig = motion_signature(pid, m)
        file = motion_render_file(pid, m["id"], sig) if sig else None
        if not file or not file.is_file():
            problems.append(f"motion « {m['title'] or m['id']} » pas encore rendu")
            continue
        out["video"].append({"asset": asset_key(file), "at": m["at"], "in": 0.0,
                             "out": min(m["dur"], out["assets"][asset_key(file)]["duration"] or m["dur"]),
                             "lane": 2, "mute": True})
    for s in timeline["audio"]:
        out["audio"].append({"asset": asset_key(base / s["src"]), "at": s["at"], "in": s["in"], "out": s["out"],
                             "gain_db": s["gain_db"], "role": s["role"]})
    ends = sum(1 for x in timeline["broll"] + timeline["motion"] for k in ("enter", "exit") if x.get(k))
    if ends:
        problems.append(f"{ends} entrée(s) ou sortie(s) de B-roll / motion : coupes franches dans Resolve "
                        "(exactes dans le rendu du studio)")
    out["markers"] = [{"t": k["t"], "text": k["text"], "kind": k["kind"]} for k in timeline["markers"]]
    # les textes ne passent pas dans le FCPXML : un marqueur à leur place, pour les refaire dans Resolve
    out["markers"] += [{"t": x["at"], "text": f"Texte : {x['text']}", "kind": "note"} for x in timeline["texts"]]
    if timeline["texts"]:
        problems.append(f"{len(timeline['texts'])} texte(s) à l'écran : marqueurs dans Resolve "
                        "(dessinés dans le rendu du studio)")
    return out, problems + tl.check(out)


def export_path(pid: str) -> Path:
    title = re.sub(r'[\\/:*?"<>|]+', "", service.load(pid).get("title") or "montage").strip() or "montage"
    return root(pid) / f"{title}.fcpxml"


def export(pid: str) -> tuple[Path, list[str]]:
    data, problems = build(pid)
    path = export_path(pid)
    for old in root(pid).glob("*.fcpxml"):
        if old != path:
            old.unlink(missing_ok=True)
    path.write_text(tl.fcpxml(data, path.stem), encoding="utf-8")
    return path, problems


# --- Forme d'onde et vignettes de la vidéo source ---------------------------------------------

def _source_key(source: dict) -> str:
    path = Path(source["path"])
    return hashlib.sha1(f"{path}:{path.stat().st_mtime}".encode()).hexdigest()[:10]


def peaks_file(pid: str, source: dict) -> Path:
    return root(pid) / CACHE_DIR / f"peaks-{_source_key(source)}.json"


def filmstrip_file(pid: str, source: dict) -> Path:
    return root(pid) / CACHE_DIR / f"filmstrip-{_source_key(source)}.jpg"


def filmstrip_step(duration: float) -> float:
    return max(1.0, round(duration / FILMSTRIP_MAX + 0.4999))


def compute_peaks(raw: bytes) -> list[int]:
    """PCM 16 bits mono à PEAKS_RATE * 50 Hz → une crête (0-100) par 1/PEAKS_RATE s."""
    samples = array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])
    per = 50
    out = []
    for i in range(0, len(samples), per):
        chunk = samples[i:i + per]
        out.append(max(max(chunk), -min(chunk)) if chunk else 0)
    top = max(out, default=1) or 1
    return [round(v * 100 / top) for v in out]


def media_state(pid: str, project: dict) -> dict:
    """Ce dont l'interface a besoin pour dessiner les pistes de la source."""
    source = _source(project)
    if not source:
        return {"peaks": None, "filmstrip": None, "pending": False}
    peaks, strip = peaks_file(pid, source), filmstrip_file(pid, source)
    pending = any(j.kind == "project_montage_media" and j.payload.get("project") == pid and not j.finished
                  for j in jobs.list_jobs(service.MODULE))
    duration = source.get("duration") or 0.0
    return {
        "peaks": f"/api/projects/{pid}/files/{peaks.relative_to(service.project_dir(pid)).as_posix()}" if peaks.is_file() else None,
        "peaks_rate": PEAKS_RATE,
        "filmstrip": {"url": f"/api/projects/{pid}/files/{strip.relative_to(service.project_dir(pid)).as_posix()}",
                      "step": filmstrip_step(duration), "cols": FILMSTRIP_COLS, "height": FILMSTRIP_HEIGHT,
                      "width": round(FILMSTRIP_HEIGHT * (source.get("width") or 16) / (source.get("height") or 9) / 2) * 2}
        if strip.is_file() else None,
        "pending": pending,
    }


def ensure_media(pid: str, project: dict) -> None:
    source = _source(project)
    if not source:
        return
    state = media_state(pid, project)
    if (state["peaks"] and state["filmstrip"]) or state["pending"]:
        return
    jobs.create(service.MODULE, "project_montage_media", {"project": pid, "path": source["path"],
                                                          "peaks": str(peaks_file(pid, source)),
                                                          "filmstrip": str(filmstrip_file(pid, source)),
                                                          "duration": source.get("duration") or 0.0,
                                                          "width": source.get("width") or 1920,
                                                          "height": source.get("height") or 1080}, {})


# --- Médias disponibles pour le montage ---------------------------------------------------

MEDIA_CATEGORIES = ("broll", "musique", "sfx")


def available(pid: str) -> list[dict]:
    """Rushes, B-roll, musique et sons : ceux du projet, puis ceux de la bibliothèque commune."""
    base = service.project_dir(pid)
    items = []
    # les rushes copiés dans le projet : à insérer dans l'A-roll (ou à poser en B-roll)
    for path in library._files(base / service.RUSHES_DIR):
        if path.suffix.lower() in library.VIDEO_EXT:
            items.append({"src": path.relative_to(base).as_posix(), "name": path.name, "category": "rush",
                          "where": "rushes", "kind": "Vidéo", "duration": library.duration(path),
                          "url": f"/api/projects/{pid}/files/{path.relative_to(base).as_posix()}"})
    for category in MEDIA_CATEGORIES:
        for path in library._files(base / service.ASSETS_DIR / category):
            if path.suffix.lower() in library.TIMED:
                items.append({"src": path.relative_to(base).as_posix(), "name": path.name, "category": category,
                              "where": "projet", "kind": library.kind_of(path), "duration": library.duration(path),
                              "url": f"/api/projects/{pid}/files/{path.relative_to(base).as_posix()}"})
    # les vidéos récupérées à l'étape Assets, rangées ailleurs que dans broll/
    for path in library._files(base / service.ASSETS_DIR):
        if path.suffix.lower() in library.VIDEO_EXT:
            items.append({"src": path.relative_to(base).as_posix(), "name": path.name, "category": "broll",
                          "where": "projet", "kind": "Vidéo", "duration": library.duration(path),
                          "url": f"/api/projects/{pid}/files/{path.relative_to(base).as_posix()}"})
    # les fichiers ajoutés au projet (Ressources) : une vidéo y sert de B-roll, un son de sound design
    for path in library._files(base / service.RESOURCES_DIR):
        ext = path.suffix.lower()
        if ext in library.TIMED:
            items.append({"src": path.relative_to(base).as_posix(), "name": path.name,
                          "category": "broll" if ext in library.VIDEO_EXT else "sfx",
                          "where": "ajoutés", "kind": library.kind_of(path), "duration": library.duration(path),
                          "url": f"/api/projects/{pid}/files/{path.relative_to(base).as_posix()}"})
    described = library.descriptions()
    for category in MEDIA_CATEGORIES:
        for path in library._files(library.LIBRARY_DIR / category):
            if path.suffix.lower() in library.TIMED:
                items.append({"src": f"library/{category}/{path.name}", "name": path.name, "category": category,
                              "where": "bibliothèque", "kind": library.kind_of(path), "duration": library.duration(path),
                              "description": described.get(f"{category}/{path.name}", ""),
                              "url": f"/api/projects/library/file/{category}/{path.name}"})
    # le volume par défaut de la bibliothèque vaut aussi pour la copie du son dans le projet
    gains = library.gains()
    for m in items:
        gain = library.gain_of(m["src"], gains)
        if gain is not None:
            m["gain_db"] = gain
    return items


def media_of(pid: str, timeline: dict) -> dict[str, dict]:
    """Durée et adresse de chaque média utilisé par la timeline."""
    base = service.project_dir(pid)
    out = {}
    for item in [*timeline["broll"], *timeline["audio"], *(c for c in timeline["aroll"] if c.get("src"))]:
        src = item["src"]
        if src not in out:
            path = base / src
            out[src] = {"name": path.name, "duration": library.duration(path) if path.is_file() else None,
                        "url": f"/api/projects/{pid}/files/{src}"}
    return out


# --- Le transcript en temps de la timeline (pour Claude et l'interface) ---------------------

def transcript_lines(project: dict, timeline: dict, lines: list[dict]) -> list[dict]:
    """Les phrases de la vidéo source replacées sur la timeline (les passages coupés disparaissent)."""
    out, cursor = [], 0.0
    for c in timeline["aroll"]:
        if c.get("src"):
            # un clip inséré d'un autre média : pas de phrase de la source
            cursor += c["out"] - c["in"]
            continue
        for line in lines:
            mid = (line["start"] + line["end"]) / 2
            if c["in"] <= mid < c["out"]:
                out.append({"start": round(cursor + max(line["start"], c["in"]) - c["in"], 2),
                            "end": round(cursor + min(line["end"], c["out"]) - c["in"], 2), "text": line["text"]})
        cursor += c["out"] - c["in"]
    return out

