"""
API du module animations : projets de slides animees creees par Claude a partir d'un transcript.
"""
import os
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...core import claude, jobs
from ..transcript import service as transcript
from . import service

router = APIRouter()


def _get(job_id: str) -> jobs.Job:
    job = jobs.get(job_id)
    if job is None or job.module != service.MODULE or job.kind != service.KIND:
        raise HTTPException(404, "projet inconnu")
    return job


def _idle(job_id: str) -> jobs.Job:
    """Les slides ne se modifient a la main que quand Claude ne travaille pas dessus."""
    job = _get(job_id)
    if not job.finished:
        raise HTTPException(409, "Claude est en train de travailler sur ce projet")
    return job


@router.get("/info")
def info():
    """Qui paie : le compte connecte dans Claude Code, et une eventuelle cle API qui serait ignoree."""
    return {"auth": claude.auth_status(),
            "api_key_in_env": any(os.environ.get(k) for k in claude.API_ENV)}


@router.get("/transcripts")
def transcripts():
    """Les transcripts termines du module transcription, a proposer comme point de depart."""
    return [{"id": j.id, "name": transcript.name(j), "duration": j.state.get("duration"),
             "created_at": j.created_at}
            for j in reversed(jobs.list_jobs(transcript.MODULE)) if j.status == "done"]


class Settings(BaseModel):
    format: str = "youtube"
    density: str = "equilibre"
    context: str = ""


def _settings(s: Settings) -> dict:
    if s.format not in service.FORMATS or s.density not in service.DENSITIES:
        raise HTTPException(400, "format ou densite inconnu")
    return s.model_dump()


class CreateRequest(BaseModel):
    transcript_job: str | None = None
    # ou un fichier fourni a la main (.srt, .vtt, .txt), lu par le navigateur
    filename: str | None = None
    text: str | None = None
    request: str = ""
    settings: Settings = Settings()
    model: str | None = None


@router.post("/jobs")
def create(req: CreateRequest):
    try:
        if req.transcript_job:
            name, text, media = service.from_transcript_job(req.transcript_job)
        elif req.text and req.text.strip():
            name, text, media = service.from_file(req.filename or "transcript", req.text)
        else:
            raise ValueError("choisis un transcript ou fournis un fichier")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    job = service.create_job(name, text, media, req.request, _settings(req.settings),
                             req.transcript_job, req.model or None)
    return service.detail(job)


class FromShortRequest(BaseModel):
    selection: str
    short: str
    model: str | None = None


@router.post("/jobs/from-short")
def create_from_short(req: FromShortRequest):
    """Un short monte (module shorts) devient un projet : sous-titres mot a mot + slides."""
    try:
        job = service.create_from_short(req.selection, req.short, req.model or None)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return service.detail(job)


@router.get("/jobs")
def list_jobs():
    return [service.summary(j) for j in jobs.list_jobs(service.MODULE) if j.kind == service.KIND]


@router.get("/jobs/{job_id}")
def job_detail(job_id: str):
    return service.detail(_get(job_id))


@router.get("/jobs/{job_id}/files/{path:path}")
def project_file(job_id: str, path: str):
    """Les fichiers du projet (compositions, charte, exemples), pour l'apercu en iframe."""
    root = service.project_dir(_get(job_id)).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(404, "fichier introuvable")
    # toujours la derniere version : Claude reecrit les fichiers en place
    return FileResponse(target, headers={"Cache-Control": "no-store"})


@router.put("/jobs/{job_id}/settings")
def update_settings(job_id: str, req: Settings):
    job = _idle(job_id)
    job.state["settings"] = _settings(req)
    service.save_state(job)
    return service.detail(job)


class MessageRequest(BaseModel):
    text: str
    # la demande ne concerne que cette slide
    slide: str | None = None


@router.post("/jobs/{job_id}/messages")
def send(job_id: str, req: MessageRequest):
    job = _idle(job_id)
    if not req.text.strip():
        raise HTTPException(400, "message vide")
    service.send(job, req.text, req.slide)
    return service.detail(_get(job_id))


@router.post("/jobs/{job_id}/stop")
def stop(job_id: str):
    """Coupe la reponse en cours ; le projet reste utilisable."""
    job = _get(job_id)
    if not job.finished:
        jobs.cancel(job)
    return {"ok": True}


class SlideChanges(BaseModel):
    start: float | None = None
    end: float | None = None
    title: str | None = None
    discarded: bool | None = None


@router.put("/jobs/{job_id}/slides/{slide_id}")
def update_slide(job_id: str, slide_id: str, req: SlideChanges):
    """Retouches du plan a la main ; la composition, elle, ne change que par Claude."""
    job = _idle(job_id)
    directory = service.project_dir(job)
    slides = service.load_plan(directory)
    if not any(s["id"] == slide_id for s in slides):
        raise HTTPException(404, "slide inconnue")
    service.snapshot(directory)
    changes = req.model_dump(exclude_none=True)
    slides = [service.clean_slide({**s, **changes}) if s["id"] == slide_id else s for s in slides]
    service.save_plan(directory, slides)
    return service.detail(job)


@router.delete("/jobs/{job_id}/slides/{slide_id}")
def delete_slide(job_id: str, slide_id: str):
    job = _idle(job_id)
    directory = service.project_dir(job)
    service.snapshot(directory)
    service.save_plan(directory, [s for s in service.load_plan(directory) if s["id"] != slide_id])
    service.slide_file(directory, slide_id).unlink(missing_ok=True)
    return service.detail(job)


class CaptionsRequest(BaseModel):
    style: str | None = None
    position: str | None = None


@router.put("/jobs/{job_id}/captions")
def update_captions(job_id: str, req: CaptionsRequest):
    job = _idle(job_id)
    try:
        service.set_captions(job, req.style, req.position)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return service.detail(job)


@router.post("/jobs/{job_id}/render")
def render(job_id: str):
    """Rendu final en MP4 (video + slides + sous-titres)."""
    job = _idle(job_id)
    current = service.last_render(job)
    if current and not current.finished:
        raise HTTPException(409, "un rendu est déjà en cours")
    try:
        service.enqueue_render(job)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return service.detail(job)


@router.post("/jobs/{job_id}/render/stop")
def stop_render(job_id: str):
    current = service.last_render(_get(job_id))
    if current and not current.finished:
        jobs.cancel(current)
    return {"ok": True}


@router.get("/renders/{render_id}/file")
def render_file(render_id: str, download: bool = False):
    render = jobs.get(render_id)
    if render is None or render.kind != service.RENDER_KIND or not service.render_output(render).is_file():
        raise HTTPException(404, "rendu introuvable")
    name = re.sub(r'[\\/:*?"<>|]+', "", render.payload["name"]).strip() or "video"
    return FileResponse(service.render_output(render), media_type="video/mp4", filename=f"{name}.mp4",
                        content_disposition_type="attachment" if download else "inline")


@router.post("/jobs/{job_id}/undo")
def undo(job_id: str):
    job = _idle(job_id)
    directory = service.project_dir(job)
    if not service.can_undo(directory):
        raise HTTPException(400, "rien à annuler")
    service.undo(directory)
    return service.detail(job)


@router.delete("/jobs/{job_id}")
def remove(job_id: str):
    job = _get(job_id)
    if job.finished:
        jobs.delete(job_id)
        service.remove_project(job)
    else:
        jobs.cancel(job)
    return {"ok": True}
