"""
Projets : une vidéo, de l'idée à la publication. Le dossier du projet garde tout ce
qu'elle produit (script, rushes, transcripts, exports…) ; project.json en garde l'état.

  project.json      titre, brief, étapes, angles, titres, vignettes, plans, rushes, dérush, vidéo source
  script/           brief.md, notes.md, documentation.md (les sources), script.json (le script en blocs,
                    voir script.py) et sa vue script.md, skill/,
                    titres/<skill>/, vignette/ (le skill des vignettes), vignette-refs/ (les images de
                    référence de la variante, copiées pour que Claude les voie) :
                    le dossier où Claude travaille (il ne voit rien d'autre)
  rushes/           les rushes importés
  transcripts/      .srt / .txt des transcriptions
  derush/           export du dérush (.mp4, .xml) et analyse en cache
  source/           la vidéo retravaillée importée
  ressources/       fichiers ajoutés à la main
  vignettes/        les images générées à l'étape Vignette (fal.ai)
  assets/           ce que l'étape Assets récupère pour le projet, un dossier par catégorie
                    (broll/, musique/, images/…), et .candidates/ : les images proposées pas encore retenues

Seule l'API écrit project.json. Les jobs (Claude, copies, rendus) déposent leur résultat
dans leur propre état ; l'API l'applique au projet à la lecture suivante (voir `sync`).
"""
import json
import os
import re
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ...config import DATA_DIR, STUDIO_DIR
from ...core import jobs

MODULE = "projects"
PROJECTS_DIR = DATA_DIR / "projects"
PROJECT_FILE = "project.json"

SCRIPT_DIR = "script"
RUSHES_DIR = "rushes"
TRANSCRIPTS_DIR = "transcripts"
DERUSH_DIR = "derush"
SOURCE_DIR = "source"
RESOURCES_DIR = "ressources"
ASSETS_DIR = "assets"
VIGNETTES_DIR = "vignettes"

BRIEF_FILE = "brief.md"
NOTES_FILE = "notes.md"
SCRIPT_FILE = "script.md"
DOCUMENTATION_FILE = "documentation.md"
SKILL_DIR = "skill"
SKILL_SOURCE = Path(os.environ.get("SCRIPTS_SKILL_DIR",
                                   STUDIO_DIR / "skills" / "youtube-scriptwriting"))
# le skill des titres
TITLES_SKILL_DIR = "titre"
TITLES_SKILL_SOURCE = Path(os.environ.get("TITLES_SKILL_DIR", STUDIO_DIR / "skills" / "youtube-titles"))
# le skill des compositions de vignettes, et les images de référence qu'on lui montre
THUMB_SKILL_DIR = "vignette"
THUMB_SKILL_SOURCE = Path(os.environ.get("THUMB_SKILL_DIR", STUDIO_DIR / "skills" / "youtube-thumbnail"))
THUMB_REFS_DIR = "vignette-refs"
# titres retenus pour l'A/B test de YouTube
MAX_TITLES = 3
# les documents que l'interface lit ; script.md s'écrit par script.py (blocs), les notes telles quelles
DOCS = (SCRIPT_FILE, NOTES_FILE)
WRITABLE_DOCS = (NOTES_FILE,)

# les étapes, dans l'ordre (l'interface en a la description complète)
STEPS = ("angle", "titre", "vignette", "script", "roast", "tournage", "derush", "transcript",
         "storyboard", "montage", "motion", "son", "selection", "smontage", "soustitres",
         "rendu", "description", "upload")
NEXT = {"transcript": ("storyboard", "selection"), "son": ("rendu",), "soustitres": ("rendu",)}
DURATIONS = ("< 5 min", "5–10 min", "10–20 min", "20–40 min", "40 min +")

MAIN_TIMELINE = "main"
VIDEO_EXTENSIONS = ("mov", "mp4", "mxf", "mkv", "avi", "webm", "m4v", "mts")

_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def safe_name(name: str, fallback: str = "fichier") -> str:
    cleaned = _UNSAFE_NAME.sub("-", Path(name).name).strip(" .-")
    return cleaned or fallback


def unique_path(folder: Path, name: str) -> Path:
    """`name` dans `folder`, suffixé (-2, -3…) s'il existe déjà."""
    target = folder / safe_name(name)
    n = 2
    while target.exists():
        target = folder / f"{Path(name).stem}-{n}{Path(name).suffix}"
        n += 1
    return target


# --- Lecture / écriture -------------------------------------------------------

def project_dir(pid: str) -> Path:
    return PROJECTS_DIR / pid


def exists(pid: str) -> bool:
    return bool(re.fullmatch(r"[\w-]+", pid)) and (project_dir(pid) / PROJECT_FILE).is_file()


def load(pid: str) -> dict:
    project = json.loads((project_dir(pid) / PROJECT_FILE).read_text(encoding="utf-8"))
    _upgrade_derush(project)
    return project


def empty_derush() -> dict:
    """timelines : les timelines du dérush ({id, name, clips}) ; `main` : la timeline globale, celle qu'on
    exporte et qui devient la vidéo source. `clips` à None : la timeline découle des rushes (voir runtime.clips)."""
    return {"cuts": {}, "splits": {}, "timelines": [{"id": MAIN_TIMELINE, "name": "", "clips": None}], "main": MAIN_TIMELINE}


def _upgrade_derush(project: dict) -> None:
    """Avant les timelines multiples, le dérush n'avait qu'une liste de bouts (derush.clips)."""
    edits = project.get("derush")
    if edits is not None and "timelines" not in edits:
        edits["timelines"] = [{"id": MAIN_TIMELINE, "name": "", "clips": edits.pop("clips", None)}]
        edits["main"] = MAIN_TIMELINE


def _write(project: dict) -> None:
    path = project_dir(project["id"]) / PROJECT_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(project, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _lock(pid: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(pid, threading.Lock())


@contextmanager
def editing(pid: str) -> Iterator[dict]:
    """Lecture-modification-écriture de project.json, une requête à la fois par projet."""
    with _lock(pid):
        project = load(pid)
        yield project
        project["updated_at"] = time.time()
        _write(project)


def load_synced(pid: str, sync) -> dict:
    """Lit le projet et lui applique `sync(project) -> bool` ; n'écrit que si quelque chose a changé."""
    with _lock(pid):
        project = load(pid)
        if sync(project):
            project["updated_at"] = time.time()
            _write(project)
        return project


def list_projects() -> list[dict]:
    if not PROJECTS_DIR.is_dir():
        return []
    found = [load(p.name) for p in PROJECTS_DIR.iterdir() if (p / PROJECT_FILE).is_file()]
    return sorted(found, key=lambda p: p.get("opened_at") or p["created_at"], reverse=True)


# --- Création ------------------------------------------------------------------

def initial_status(start: str) -> dict:
    """Les étapes avant `start` sont sautées, `start` est en cours."""
    i = STEPS.index(start)
    return {s: "skip" if k < i else "cur" if k == i else "todo" for k, s in enumerate(STEPS)}


def name_from_idea(idea: str) -> str:
    first = re.split(r"[.:!?\n]", idea.strip())[0].strip()
    if len(first) > 60:
        first = first[:60].rsplit(" ", 1)[0] + "…"
    return (first[:1].upper() + first[1:]) or "Nouveau projet"


def write_brief(pid: str, brief: dict) -> None:
    """brief.md : ce que Claude lit pour chercher des angles et écrire le script."""
    parts = [f"# Brief\n\n{brief.get('idea', '').strip()}\n"]
    if brief.get("dir", "").strip():
        parts.append(f"## Direction\n\n{brief['dir'].strip()}\n")
    if brief.get("dur"):
        parts.append(f"## Durée visée\n\n{brief['dur']}\n")
    if brief.get("notes", "").strip():
        parts.append(f"## Notes\n\n{brief['notes'].strip()}\n")
    if brief.get("links"):
        parts.append("## Liens fournis\n\n" + "\n".join(f"- {link}" for link in brief["links"]) + "\n")
    (project_dir(pid) / SCRIPT_DIR / BRIEF_FILE).write_text("\n".join(parts), encoding="utf-8")


def write_documentation(pid: str, research: list[dict]) -> None:
    """documentation.md : le tableau des sources de l'onglet Recherche, avec leur commentaire."""

    def cell(text: str) -> str:
        return " ".join(text.split()).replace("|", "\\|")

    lines = ["# Sources du projet", "", "| Source | Lien | À retenir / à consulter ? |", "| --- | --- | --- |"]
    lines += [f"| {cell(s.get('t') or '')} | {cell(s.get('u') or '')} | {cell(s.get('n') or '')} |" for s in research]
    (project_dir(pid) / SCRIPT_DIR / DOCUMENTATION_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _source_from_link(link: str) -> dict:
    title = re.sub(r"^https?://(www\.)?", "", link).split("/")[0] if re.match(r"https?://", link) else link
    return {"t": title, "u": link, "n": ""}


def copy_skills(pid: str) -> None:
    """Les skills que Claude suit, copiés dans le dossier où il travaille (s'ils n'y sont pas déjà)."""
    pairs = [(SKILL_SOURCE, SKILL_DIR), (THUMB_SKILL_SOURCE, THUMB_SKILL_DIR), (TITLES_SKILL_SOURCE, TITLES_SKILL_DIR)]
    for source, name in pairs:
        target = project_dir(pid) / SCRIPT_DIR / name
        if source.is_dir() and not target.exists():
            shutil.copytree(source, target)


def create(mode: str, title: str, brief: dict, pid: str | None = None) -> dict:
    pid = pid or uuid.uuid4().hex[:10]
    directory = project_dir(pid)
    for sub in (SCRIPT_DIR, RUSHES_DIR, TRANSCRIPTS_DIR, DERUSH_DIR, SOURCE_DIR, RESOURCES_DIR, ASSETS_DIR):
        (directory / sub).mkdir(parents=True, exist_ok=True)
    copy_skills(pid)
    brief = {"idea": "", "dir": "", "dur": "10–20 min", "notes": "", "links": [], **brief}
    now = time.time()
    project = {
        "id": pid, "title": title.strip() or name_from_idea(brief["idea"]), "mode": mode,
        "created_at": now, "updated_at": now, "opened_at": now,
        "status": initial_status("transcript" if mode == "video" else "angle"),
        "brief": brief,
        "angles": [], "angle_sel": None, "angle_round": 0,
        "titles": [], "titles_round": 0, "titles_advice": "",
        "thumbs": [], "thumb_sel": None, "thumb_images": {},
        "research": [_source_from_link(link) for link in brief["links"]],
        "shots": [],
        "rushes": [], "rush_sort": "Script",
        "derush": empty_derush(),
        "source": None,
        "assets": empty_assets(),
        "jobs": {}, "copies": [],
    }
    _write(project)
    write_brief(pid, brief)
    write_documentation(pid, project["research"])
    if not (directory / SCRIPT_DIR / NOTES_FILE).exists():
        (directory / SCRIPT_DIR / NOTES_FILE).write_text("", encoding="utf-8")
    return project


def empty_assets() -> dict:
    """videos : les liens prévisualisés ; downloads : les téléchargements lancés (job, destination) ;
    capture : les sources à capturer (url -> bool) ; captures : les captures faites (url -> {rel, error})."""
    return {"videos": [], "downloads": [], "capture": {}, "captures": {}}


def remove(pid: str) -> None:
    project = load(pid)
    for job_id in [*project["jobs"].values(), *project["copies"]]:
        job = jobs.get(job_id)
        if job and not job.finished:
            jobs.cancel(job)
    shutil.rmtree(project_dir(pid), ignore_errors=True)
    _storage_cache.pop(pid, None)


# --- Place occupée sur le disque -----------------------------------------------

# catégorie de chaque dossier de premier niveau ; le reste (script/, montage/, project.json…) : "other"
STORAGE_CATEGORIES = {
    RUSHES_DIR: "rushes", SOURCE_DIR: "source", DERUSH_DIR: "derush", TRANSCRIPTS_DIR: "derush",
    "rendu": "renders", ASSETS_DIR: "media", RESOURCES_DIR: "media", VIGNETTES_DIR: "media",
}
STORAGE_ORDER = ("rushes", "source", "derush", "renders", "media", "other")
# parcourir 20 Go de rushes reste rapide, mais l'accueil relit la liste souvent
STORAGE_TTL = 30
_storage_cache: dict[str, tuple[float, dict[str, int]]] = {}


def _tree_size(path: Path) -> int:
    try:
        if not path.is_dir():
            return path.stat().st_size
        return sum(_tree_size(Path(e.path)) if e.is_dir(follow_symlinks=False) else e.stat().st_size
                   for e in os.scandir(path))
    except OSError:
        return 0


def storage(pid: str) -> dict[str, int]:
    """Octets occupés par le projet, par catégorie (dans l'ordre de STORAGE_ORDER, catégories vides comprises)."""
    cached = _storage_cache.get(pid)
    if cached and time.time() - cached[0] < STORAGE_TTL:
        return cached[1]
    sizes = dict.fromkeys(STORAGE_ORDER, 0)
    directory = project_dir(pid)
    if directory.is_dir():
        for entry in directory.iterdir():
            sizes[STORAGE_CATEGORIES.get(entry.name, "other")] += _tree_size(entry)
    _storage_cache[pid] = (time.time(), sizes)
    return sizes


def forget_storage(pid: str) -> None:
    """Après une suppression : la prochaine lecture de la place occupée refait le compte."""
    _storage_cache.pop(pid, None)


# --- Modifications depuis l'interface ------------------------------------------

# ce que l'interface peut remplacer tel quel
EDITABLE = {"title", "status", "brief", "angle_sel", "titles", "thumbs", "thumb_sel", "research", "shots",
            "rush_sort", "rush_order", "cuts", "splits", "timelines", "capture", "opened_at", "publish"}


def patch(pid: str, changes: dict) -> dict:
    unknown = set(changes) - EDITABLE
    if unknown:
        raise ValueError(f"champ non modifiable : {', '.join(sorted(unknown))}")
    with editing(pid) as project:
        for key, value in changes.items():
            if key in ("cuts", "splits"):
                project["derush"][key] = value
            elif key == "timelines":
                project["derush"]["timelines"] = _clean_timelines(project, value)
            elif key == "capture":
                project.setdefault("assets", empty_assets())["capture"] = value
            elif key == "rush_order":
                by_id = {r["id"]: r for r in project["rushes"]}
                ordered = [by_id.pop(i) for i in value if i in by_id]
                project["rushes"] = ordered + list(by_id.values())
            elif key == "titles" and sum(1 for t in value if t.get("pick")) > MAX_TITLES:
                raise ValueError(f"{MAX_TITLES} titres retenus au plus")
            elif key == "title":
                if not str(value).strip():
                    raise ValueError("le titre ne peut pas être vide")
                project["title"] = str(value).strip()
            elif key == "status":
                project["status"] = {s: value.get(s, project["status"].get(s, "todo")) for s in STEPS}
            else:
                project[key] = value
        if "brief" in changes:
            write_brief(pid, project["brief"])
        if "research" in changes:
            write_documentation(pid, project["research"])
    return project


def _clean_timelines(project: dict, value: list) -> list[dict]:
    """Les timelines envoyées par l'interface : bouts de rushes connus ({rush}) ou timelines imbriquées ({tl}),
    sans boucle (une timeline ne peut pas se contenir, même de loin). La globale ne disparaît jamais."""
    rushes = {r["id"] for r in project["rushes"]}
    ids = [str(t["id"]) for t in value]
    out: list[dict] = []
    for tl in value:
        clips = tl.get("clips")
        if clips is not None:
            kept = []
            for c in clips:
                a, b = round(float(c["in"]), 3), round(float(c["out"]), 3)
                if b <= a:
                    continue
                if c.get("rush") in rushes:
                    kept.append({"id": str(c["id"]), "rush": c["rush"], "in": a, "out": b})
                elif c.get("tl") in ids and c["tl"] != tl["id"]:
                    kept.append({"id": str(c["id"]), "tl": c["tl"], "in": a, "out": b})
            clips = kept
        out.append({"id": str(tl["id"]), "name": str(tl.get("name") or "").strip(), "clips": clips})
    main = project["derush"]["main"]
    if main not in ids:
        out.insert(0, next(t for t in project["derush"]["timelines"] if t["id"] == main))
    # une imbrication qui ferait boucle est retirée
    by_id = {t["id"]: t for t in out}

    def reaches(start: str, target: str, seen: set[str]) -> bool:
        for c in by_id[start]["clips"] or []:
            sub = c.get("tl")
            if sub == target or (sub and sub not in seen and reaches(sub, target, seen | {sub})):
                return True
        return False

    for tl in out:
        if tl["clips"]:
            tl["clips"] = [c for c in tl["clips"] if not (c.get("tl") and reaches(c["tl"], tl["id"], {c["tl"]}))]
    return out


def complete_step(project: dict, step: str, done: bool) -> None:
    """« Marquer comme terminé » : les étapes suivantes passent en cours."""
    status = project["status"]
    if not done:
        status[step] = "cur"
        return
    status[step] = "done"
    i = STEPS.index(step)
    following = NEXT.get(step) or (STEPS[i + 1:i + 2])
    for s in following:
        if status.get(s, "todo") == "todo":
            status[s] = "cur"


def start_step(project: dict, step: str) -> None:
    """Une étape qu'on entame (transcription lancée, vidéo importée…) n'est plus « à faire »."""
    if project["status"].get(step, "todo") in ("todo", "skip"):
        project["status"][step] = "cur"


# --- Documents du dossier script/ ----------------------------------------------

def read_doc(pid: str, name: str) -> str:
    path = project_dir(pid) / SCRIPT_DIR / name
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def write_doc(pid: str, name: str, content: str) -> None:
    if name not in WRITABLE_DOCS:
        raise ValueError("document inconnu")
    (project_dir(pid) / SCRIPT_DIR / name).write_text(content, encoding="utf-8")


def doc_mtime(pid: str, name: str) -> float:
    path = project_dir(pid) / SCRIPT_DIR / name
    return path.stat().st_mtime if path.is_file() else 0


# --- Jobs rattachés -------------------------------------------------------------

def job_view(job_id: str | None) -> dict | None:
    job = jobs.get(job_id) if job_id else None
    if not job:
        return None
    return {"id": job.id, "kind": job.kind, "status": job.status, "progress": job.progress,
            "error": job.error, "finished": job.finished, "activity": job.state.get("activity"),
            # pour les angles : recherche ou réécriture d'un angle précis
            "mode": job.payload.get("mode"), "index": job.payload.get("index")}


def chat_jobs(pid: str, topic: str, scope: str | None = None) -> list[jobs.Job]:
    """Les discussions d'un sujet (et, pour le roast, d'un roast : `scope`), de la plus ancienne à la plus récente."""
    return [j for j in jobs.list_jobs(MODULE) if j.kind == "project_chat" and j.payload.get("project") == pid
            # les premières discussions du script n'avaient pas de sujet
            and j.payload.get("topic", "script") == topic and (scope is None or j.payload.get("scope") == scope)]


def chat_title(job: jobs.Job) -> str:
    first = next((m["text"] for m in job.state.get("messages", []) if m["role"] == "user"), "Discussion")
    first = " ".join(first.split())
    return first[:48] + ("…" if len(first) > 48 else "")


def requeue(job_id: str, kind: str, payload: dict, state: dict) -> jobs.Job:
    """Les jobs Claude d'un projet ont un id fixe : on les relance avec une nouvelle demande."""
    job = jobs.get(job_id)
    if job is None:
        return jobs.create(MODULE, kind, payload, state, job_id=job_id)
    if not job.finished:
        raise ValueError("Claude travaille déjà sur cette demande")
    jobs.update(job_id, payload=payload, state=state, status="queued", progress=0,
                cancel_requested=False, error=None, started_at=None, finished_at=None)
    return jobs.get(job_id)
