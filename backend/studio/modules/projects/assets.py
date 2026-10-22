"""
L'étape Assets côté API :

- YouTube : les vidéos prévisualisées (project.assets.videos) et les téléchargements lancés,
  des jobs du module youtube qui déposent le fichier dans le projet ou la bibliothèque ;
- Images : une discussion avec Claude par projet (job `<pid>-images`), qui garde les images
  proposées dans son état ; celles qu'on valide sont copiées à destination ;
- Documentation : les captures des sources du script (job `<pid>-captures`).
"""
import shutil
import uuid
from pathlib import Path

from ...core import jobs
from ..settings.service import language as channel_language
from ..youtube import service as youtube
from . import library, service

CANDIDATES_DIR = ".candidates"


def candidates_dir(pid: str, beat: str = "") -> Path:
    """Les images proposées par une recherche : celle de Médias, ou celle d'un beat du montage (`beat`)."""
    folder = service.project_dir(pid) / service.ASSETS_DIR / CANDIDATES_DIR
    return folder / "beats" / beat if beat else folder


def images_job_id(pid: str, beat: str = "") -> str:
    """La recherche d'images de Médias, ou celle d'un beat : chaque beat a sa discussion, qui tourne sans la popup."""
    return f"{pid}-images-{beat}" if beat else f"{pid}-images"


# --- YouTube ---------------------------------------------------------------------------

def add_video(project: dict, info: dict) -> dict:
    """Une vidéo prévisualisée rejoint la liste (en tête) ; déjà là, elle remonte."""
    videos = project["assets"]["videos"]
    url = info.get("webpage_url") or ""
    found = next((v for v in videos if v["url"] == url), None)
    if found:
        videos.remove(found)
    entry = found or {"id": "v" + uuid.uuid4().hex[:8], "url": url}
    entry.update(title=info.get("title") or url, uploader=info.get("uploader"), duration=info.get("duration"),
                 thumbnail=info.get("thumbnail"), heights=info.get("heights") or [],
                 # lecteur intégré pour YouTube seulement
                 yt=info.get("id") if info.get("extractor_key") == "Youtube" else None)
    videos.insert(0, entry)
    return entry


def start_download(project: dict, video: dict, options: dict, clip: dict | None, common: bool, category: str) -> None:
    folder, label = library.destination(project["id"], common, category)
    language = None if options["language"] == "auto" else options["language"] or channel_language()
    job = youtube.create_job(video["url"], options["mode"], options["max_height"], True, folder,
                             options["transcribe"], language, clip, options["precise"])
    project["assets"]["downloads"].append({"job": job.id, "video": video["id"], "dest": label,
                                           "common": common, "category": category, "recorded": False})


def _download_view(d: dict) -> dict | None:
    job = jobs.get(d["job"])
    if not job:
        return None
    path = job.state.get("filepath")
    return {"id": job.id, "video": d["video"], "dest": d["dest"], "status": job.status, "progress": job.progress,
            "error": job.error, "finished": job.finished, "mode": job.payload.get("mode"),
            "start": job.payload.get("start"), "end": job.payload.get("end"),
            "name": Path(path).name if path else None, "transcribe": job.payload.get("transcribe", False)}


# --- Résultats des jobs ----------------------------------------------------------------

def sync(project: dict) -> bool:
    """Les projets d'avant l'étape, les téléchargements finis vers la bibliothèque, les captures faites."""
    changed = False
    if "assets" not in project:
        project["assets"] = service.empty_assets()
        changed = True
    a = project["assets"]
    for d in a["downloads"]:
        if not d["common"] or d.get("recorded"):
            continue
        job = jobs.get(d["job"])
        if job and job.status == "done" and job.state.get("filepath"):
            # la bibliothèque retient de quel projet vient chaque fichier
            library.remember_origin(f"{d['category']}/{Path(job.state['filepath']).name}", project["title"])
            d["recorded"] = True
            changed = True
    capture_job = jobs.get(project["jobs"].get("captures") or "")
    if capture_job:
        for url, result in (capture_job.state.get("done") or {}).items():
            current = a["captures"].get(url) or {}
            # une image choisie à la main n'est pas écrasée par une capture d'avant
            if current != result and not current.get("manual"):
                a["captures"][url] = result
                changed = True
    return changed


def capture_queue(project: dict) -> list[str]:
    """Les sources que le job de captures n'a pas encore traitées."""
    job = jobs.get(project["jobs"].get("captures") or "")
    if not job or job.finished:
        return []
    return [s["u"] for s in job.payload["sources"][job.state.get("next", 0):]]


def view(project: dict) -> dict:
    return {"downloads": [v for v in map(_download_view, project["assets"]["downloads"]) if v],
            "capturing": capture_queue(project)}


# --- Images ------------------------------------------------------------------------------

def images_state(pid: str, beat: str = "") -> dict:
    job = jobs.get(images_job_id(pid, beat))
    if not job:
        return {"messages": [], "results": [], "busy": False, "error": None, "activity": None}
    return {"messages": job.state.get("messages", []), "results": job.state.get("results", []),
            "busy": not job.finished, "error": job.error if job.status == "error" else None,
            "activity": job.state.get("activity")}


def reset_images(pid: str, beat: str = "") -> None:
    """Une nouvelle recherche : la discussion et les images proposées s'effacent (celles déjà rangées restent)."""
    job = jobs.get(images_job_id(pid, beat))
    if job and not job.finished:
        raise ValueError("Daryl cherche encore : attends la fin de la recherche")
    if job:
        jobs.delete(job.id)
    folder = candidates_dir(pid, beat)
    if beat:
        shutil.rmtree(folder, ignore_errors=True)
    elif folder.is_dir():
        # celles des beats restent : leurs recherches continuent
        for f in folder.iterdir():
            if f.is_file():
                f.unlink(missing_ok=True)


def beat_searches(pid: str, beats: list[str]) -> dict:
    """Les recherches d'images des beats, pour la file du montage : {beat: {status, activity, error, query, found}}.
    Une recherche finie que l'auteur a écartée (ou dont il a gardé des images) n'y figure plus."""
    out = {}
    for beat in beats:
        job = jobs.get(images_job_id(pid, beat))
        if not job or job.state.get("dismissed"):
            continue
        asked = next((m["text"] for m in reversed(job.state.get("messages", [])) if m["role"] == "user"), "")
        found = sum(1 for r in job.state.get("results", []) if r.get("query") == asked and not r.get("added"))
        status = job.status if job.status in ("queued", "error", "cancelled", "done") else "running"
        out[beat] = {"status": status, "activity": job.state.get("activity"), "error": job.error, "query": asked,
                     "found": found}
    return out


def dismiss_search(pid: str, beat: str) -> None:
    """Retire la recherche d'un beat de la file (sa discussion reste, pour la popup)."""
    job = jobs.get(images_job_id(pid, beat))
    if job and job.finished:
        jobs.update(job.id, state={**job.state, "dismissed": True})


def add_images(pid: str, ids: list[str], common: bool, category: str, project_title: str, beat: str = "") -> list[str]:
    """Copie les images retenues à destination ; rend leur `src` (comme la timeline), dans l'ordre de `ids`."""
    job = jobs.get(images_job_id(pid, beat))
    if not job:
        raise ValueError("aucune recherche d'images")
    if not job.finished:
        raise ValueError("Claude cherche encore : attends la fin de la recherche")
    folder, label = library.destination(pid, common, category)
    added = {}
    for r in job.state.get("results", []):
        if r["id"] not in ids or r.get("added"):
            continue
        src = candidates_dir(pid, beat) / r["file"]
        if not src.is_file():
            continue
        name = r["title"] + (f" - {r['variant']}" if r.get("variant") else "")
        dest = service.unique_path(folder, service.safe_name(name[:120] + src.suffix))
        shutil.copy2(src, dest)
        if common:
            library.remember_origin(f"{category}/{dest.name}", project_title)
        r["added"] = label
        added[r["id"]] = (f"library/{category}/{dest.name}" if common
                          else dest.relative_to(service.project_dir(pid)).as_posix())
    if beat and added:
        # gardées : la recherche quitte la file du montage
        job.state["dismissed"] = True
    jobs.update(job.id, state=job.state)
    return [added[i] for i in ids if i in added]
