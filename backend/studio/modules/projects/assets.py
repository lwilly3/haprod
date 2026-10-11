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


def candidates_dir(pid: str) -> Path:
    return service.project_dir(pid) / service.ASSETS_DIR / CANDIDATES_DIR


def images_job_id(pid: str) -> str:
    return f"{pid}-images"


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
    service.start_step(project, "assets")


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

def images_state(pid: str) -> dict:
    job = jobs.get(images_job_id(pid))
    if not job:
        return {"messages": [], "results": [], "busy": False, "error": None, "activity": None}
    return {"messages": job.state.get("messages", []), "results": job.state.get("results", []),
            "busy": not job.finished, "error": job.error if job.status == "error" else None,
            "activity": job.state.get("activity")}


def add_images(pid: str, ids: list[str], common: bool, category: str, project_title: str) -> int:
    """Copie les images retenues à destination ; rend leur nombre."""
    job = jobs.get(images_job_id(pid))
    if not job:
        raise ValueError("aucune recherche d'images")
    if not job.finished:
        raise ValueError("Claude cherche encore : attends la fin de la recherche")
    folder, label = library.destination(pid, common, category)
    count = 0
    for r in job.state.get("results", []):
        if r["id"] not in ids or r.get("added"):
            continue
        src = candidates_dir(pid) / r["file"]
        if not src.is_file():
            continue
        name = r["title"] + (f" - {r['variant']}" if r.get("variant") else "")
        dest = service.unique_path(folder, service.safe_name(name[:120] + src.suffix))
        shutil.copy2(src, dest)
        if common:
            library.remember_origin(f"{category}/{dest.name}", project_title)
        r["added"] = label
        count += 1
    jobs.update(job.id, state=job.state)
    return count
