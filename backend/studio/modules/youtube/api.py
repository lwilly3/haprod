"""
API du module YouTube : apercu d'une URL, file de telechargements.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...core import jobs, system
from ..settings.service import language as channel_language
from ..transcript import service as transcript
from . import service

router = APIRouter()


def _get(job_id: str) -> jobs.Job:
    job = jobs.get(job_id)
    if job is None or job.module != service.MODULE:
        raise HTTPException(404, "telechargement inconnu")
    return job


def _file(job: jobs.Job) -> Path:
    path = job.state.get("filepath")
    if not path or not Path(path).is_file():
        raise HTTPException(404, "fichier introuvable")
    return Path(path)


@router.get("/info")
def info():
    return {"output_dir": str(service.OUTPUT_DIR)}


@router.get("/probe")
def probe(url: str):
    """Titre, miniature et resolutions disponibles, sans rien telecharger."""
    try:
        return service.probe(url)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class Clip(BaseModel):
    start: float
    end: float
    label: str = ""


class DownloadRequest(BaseModel):
    url: str
    mode: str = "video"
    max_height: int | None = None
    mp4: bool = True
    output_dir: str | None = None
    transcribe: bool = False
    # absente : la langue de la chaîne ; « auto » : Whisper la détecte
    language: str | None = None
    clips: list[Clip] = []
    precise: bool = True


@router.post("/jobs")
def add(req: DownloadRequest):
    if req.mode not in ("video", "audio"):
        raise HTTPException(400, f"mode inconnu : {req.mode}")
    url = req.url.strip()
    if not url:
        raise HTTPException(400, "URL vide")
    for clip in req.clips:
        if clip.start < 0 or clip.end <= clip.start:
            raise HTTPException(400, f"clip invalide : {clip.start} -> {clip.end}")
    output_dir = Path(req.output_dir.strip().strip('"')) if req.output_dir else service.OUTPUT_DIR
    language = None if req.language == "auto" else req.language or channel_language()
    # un job par clip : chacun a sa ligne, son fichier et sa transcription
    clips = [c.model_dump() for c in req.clips] or [None]
    return [service.summary(service.create_job(url, req.mode, req.max_height, req.mp4, output_dir,
                                               req.transcribe, language, clip, req.precise))
            for clip in clips]


@router.get("/jobs")
def list_jobs():
    return [service.summary(j) for j in jobs.list_jobs(service.MODULE)]


@router.delete("/jobs/{job_id}")
def remove(job_id: str):
    """Retire de la liste (le fichier telecharge reste sur le disque)."""
    job = _get(job_id)
    if job.finished:
        jobs.delete(job_id)
    else:
        jobs.cancel(job)
    return {"ok": True}


@router.post("/jobs/{job_id}/reveal")
def reveal(job_id: str):
    system.reveal(_file(_get(job_id)))
    return {"ok": True}


class TranscribeRequest(BaseModel):
    language: str | None = None


@router.post("/jobs/{job_id}/transcribe")
def transcribe(job_id: str, req: TranscribeRequest):
    """Transcrire apres coup une video deja telechargee."""
    job = _get(job_id)
    if job.status != "done":
        raise HTTPException(409, "le telechargement n'est pas termine")
    if not service.transcript_job(job):
        path = _file(job)
        created = transcript.create_jobs([path], None if req.language == "auto" else req.language or channel_language(), "line",
                                         sequence=False, output_dir=path.parent)[0]
        job.state["transcript_job"] = created.id
        jobs.update(job.id, state=job.state)
    return service.summary(job)


@router.get("/jobs/{job_id}/media")
def media(job_id: str):
    return FileResponse(_file(_get(job_id)))


@router.post("/browse-folder")
def browse_folder(start: str | None = None):
    return {"path": system.pick_folder("Dossier de destination", start)}
