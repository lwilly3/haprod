"""
Ce qui ne sert plus dans le dossier d'un projet, et sa purge :

  assets/                  un B-roll, une image, une musique, un son que ni la timeline ni une composition n'utilise,
                           sauf s'il est prévu sur un beat du storyboard ou capturé depuis l'onglet Médias ; un clip
                           de l'historique qui le posait ne revient plus en annulant
  montage/motion/renders/  le rendu d'un motion retiré du montage (ou d'une version de sa composition qui n'est plus
                           la sienne) ; refait de lui-même si le motion revient (annuler)
  montage/motion/media/    un média qu'aucune composition ne pose plus, ni dans l'historique ni chez Daryl
  derush/                  l'export d'une timeline supprimée, les niveaux et la vignette d'un rush retiré
  rushes/, source/         une vidéo que le projet n'utilise plus (rush retiré, source remplacée)

Par prudence, hors assets/, rien de ce que nomment project.json, la timeline, le storyboard, l'historique ou les copies
de travail de Daryl n'est compté, ni un fichier qu'une copie en cours remplit.
"""
import html
import json
import re
from pathlib import Path
from urllib.parse import unquote

from ...core import jobs
from . import assets, montage, service

ORDER = ("assets", "motion_renders", "motion_media", "derush", "videos")
# les caches du dérush d'un rush : levels-<rush>-<clé>.json, peaks-…, thumb-<rush>-<clé>.jpg
_RUSH_CACHE = re.compile(r"(?:levels|peaks|thumb)-([^-]+)-.+")
_TIMELINE_EXPORT = re.compile(r"derush-(.+)\.mp4")


# un média posé par une composition : src="media/…", data-from='media/…', url(media/…) ; un nom peut avoir des
# apostrophes ou des parenthèses (« Icône FilmCraft (équivalent de Premiere) - icône d'appli.webp »)
_MEDIA_REF = re.compile(rb""""media/([^"<>]+)"|'media/([^'<>]+)'|\(\s*media/([^"'()<>]+)\)""")
# ce qu'on a déjà lu d'un fichier, tant qu'il ne change pas : l'historique ne bouge plus une fois écrit
_read_cache: dict[tuple[Path, str], tuple[tuple[int, int], object]] = {}


def _cached(path: Path, parse):
    try:
        st = path.stat()
        key = (st.st_mtime_ns, st.st_size)
        hit = _read_cache.get((path, parse.__name__))
        if hit and hit[0] == key:
            return hit[1]
        value = parse(path.read_bytes())
    except (OSError, ValueError):
        return None
    _read_cache[path, parse.__name__] = (key, value)
    return value


def _state_text(raw: bytes) -> str:
    # les chemins Windows (« C:\\Dev\\… ») s'écrivent comme les autres, avec des /
    return json.dumps(json.loads(raw), ensure_ascii=False).replace("\\\\", "/")


def _media_names(raw: bytes) -> set[str]:
    return {unquote(html.unescape(m.decode("utf-8", "replace")))
            for groups in _MEDIA_REF.findall(raw) for m in groups if m}


def _page_text(raw: bytes) -> str:
    return unquote(html.unescape(raw.decode("utf-8", "replace")))


def _texts(paths, parse) -> str:
    return "\n".join(t for p in paths if (t := _cached(p, parse)))


def _references(pid: str) -> tuple[str, str, set[str]]:
    """Tout ce que nomment l'état du projet (ses .json, en texte, historique compris) ; ce qui garde un média de
    assets/ (l'état sans l'historique, et les compositions) ; les médias que posent les compositions (historique
    compris)."""
    directory = service.project_dir(pid)
    work = montage.root(pid) / montage.WORK_DIR
    history = montage.root(pid) / montage.HISTORY_DIR
    current = [directory / service.PROJECT_FILE, montage.root(pid) / montage.TIMELINE_FILE,
               montage.root(pid) / "storyboard.json", *work.rglob("*.json")]
    current_text = _texts(current, _state_text)
    text = current_text + "\n" + _texts(history.glob(f"*/{montage.TIMELINE_FILE}"), _state_text)
    pages = [*montage.motion_dir(pid).glob("*.html"), *work.rglob("*.html")]
    keep_assets = current_text + "\n" + _texts(pages, _page_text)
    media: set[str] = set()
    for path in [*pages, *history.glob(f"*/{montage.MOTION_DIR}/*.html")]:
        media |= _cached(path, _media_names) or set()
    return text, keep_assets, media


def _copying(project: dict) -> set[Path]:
    """Les fichiers que remplit une copie pas encore terminée."""
    out = set()
    for job_id in project.get("copies", []):
        job = jobs.get(job_id)
        if job and not job.finished:
            out |= {Path(f["dest"]).resolve() for f in job.state.get("files", [])}
    return out


def _files(folder: Path) -> list[Path]:
    return [p for p in folder.iterdir() if p.is_file()] if folder.is_dir() else []


def unused(pid: str) -> dict[str, list[Path]]:
    """Les fichiers qui ne servent plus, par catégorie (dans l'ordre de ORDER)."""
    directory = service.project_dir(pid)
    project = service.load(pid)
    state, keep_assets, media = _references(pid)
    copying = _copying(project)
    out: dict[str, list[Path]] = {k: [] for k in ORDER}

    def named(path: Path) -> bool:
        return path.relative_to(directory).as_posix() in state or path.resolve() in copying

    folder = directory / service.ASSETS_DIR
    for path in folder.rglob("*") if folder.is_dir() else []:
        # les images proposées attendent qu'on choisisse
        if path.is_file() and assets.CANDIDATES_DIR not in path.parts and path.resolve() not in copying \
                and path.relative_to(directory).as_posix() not in keep_assets:
            out["assets"].append(path)

    timeline = montage.load(pid)
    renders = {montage.motion_render_file(pid, m["id"], sig).name
               for m in timeline["motion"] if (sig := montage.motion_signature(pid, m))}
    for path in _files(montage.motion_dir(pid) / montage.RENDERS_DIR):
        if path.suffix == ".mov" and path.name not in renders and not named(path):
            out["motion_renders"].append(path)

    for path in _files(montage.motion_dir(pid) / montage.MEDIA_DIR):
        if path.name not in media and path.name not in state:
            out["motion_media"].append(path)

    rushes = {r["id"] for r in project["rushes"]}
    timelines = {t["id"] for t in project["derush"]["timelines"]}
    for path in _files(directory / service.DERUSH_DIR):
        cache, export = _RUSH_CACHE.fullmatch(path.name), _TIMELINE_EXPORT.fullmatch(path.name)
        if (cache and cache.group(1) not in rushes or export and export.group(1) not in timelines) and not named(path):
            out["derush"].append(path)

    for folder in (service.RUSHES_DIR, service.SOURCE_DIR):
        for path in _files(directory / folder):
            if not named(path):
                out["videos"].append(path)
    return out


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def summary(pid: str) -> dict:
    found = unused(pid)
    categories = [{"key": k, "count": len(found[k]), "bytes": sum(_size(p) for p in found[k])} for k in ORDER]
    return {"total": sum(c["bytes"] for c in categories), "categories": categories}


def purge(pid: str) -> int:
    """Supprime ce qui ne sert plus ; rend les octets libérés (un fichier encore ouvert reste, sans erreur)."""
    freed = 0
    for paths in unused(pid).values():
        for path in paths:
            size = _size(path)
            try:
                path.unlink()
            except OSError:
                continue
            freed += size
    service.forget_storage(pid)
    return freed
