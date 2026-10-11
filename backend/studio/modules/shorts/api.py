"""
API du module shorts : selections de passages proposees par Claude a partir d'un
transcript, et leur montage video.
"""
import re
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from ...core import jobs
from . import service

router = APIRouter()


def _get(job_id: str) -> jobs.Job:
    job = jobs.get(job_id)
    if job is None or job.module != service.MODULE or job.kind != service.KIND:
        raise HTTPException(404, "sélection inconnue")
    return job


def _idle(job_id: str) -> jobs.Job:
    job = _get(job_id)
    if not job.finished:
        raise HTTPException(409, "Claude est en train de travailler sur cette sélection")
    return job


def _short(job: jobs.Job, short_id: str) -> dict:
    short = next((s for s in job.state["shorts"] if s["id"] == short_id), None)
    if short is None:
        raise HTTPException(404, "short inconnu")
    return short


def _filename(title: str, ext: str) -> str:
    return (re.sub(r'[\\/:*?"<>|]+', "", title).strip() or "short") + ext


class Settings(BaseModel):
    max_duration: int = 180
    count: int = 0
    context: str = ""
    format: str = "vertical"


class CreateRequest(BaseModel):
    transcript_job: str
    request: str = ""
    settings: Settings = Settings()
    model: str | None = None


@router.post("/jobs")
def create(req: CreateRequest):
    try:
        job = service.create_job(req.transcript_job, req.request, req.settings.model_dump(),
                                 req.model or None)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return service.detail(job)


@router.get("/jobs")
def list_jobs(transcript: str | None = None):
    return [service.summary(j) for j in jobs.list_jobs(service.MODULE)
            if j.kind == service.KIND
            and (transcript is None or j.payload["transcript_job"] == transcript)]


@router.get("/jobs/{job_id}")
def job_detail(job_id: str):
    return service.detail(_get(job_id))


class MessageRequest(BaseModel):
    text: str


@router.post("/jobs/{job_id}/messages")
def send(job_id: str, req: MessageRequest):
    job = _idle(job_id)
    if not req.text.strip():
        raise HTTPException(400, "message vide")
    service.send(job, req.text)
    return service.detail(_get(job_id))


@router.post("/jobs/{job_id}/stop")
def stop(job_id: str):
    job = _get(job_id)
    if not job.finished:
        jobs.cancel(job)
    return {"ok": True}


@router.delete("/jobs/{job_id}/shorts/{short_id}")
def remove_short(job_id: str, short_id: str):
    """Ecarter un short ; Claude le saura au prochain message (selection actuelle)."""
    job = _idle(job_id)
    job.state["shorts"] = [s for s in job.state["shorts"] if s["id"] != short_id]
    jobs.update(job.id, state=job.state)
    return service.detail(job)


@router.get("/jobs/{job_id}/shorts/{short_id}/srt")
def short_srt(job_id: str, short_id: str):
    job = _get(job_id)
    short = _short(job, short_id)
    filename = quote(_filename(short["title"], ".srt"))
    return PlainTextResponse(service.to_srt(job, short), headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})


@router.post("/jobs/{job_id}/shorts/{short_id}/render")
def render_short(job_id: str, short_id: str, force: bool = True):
    """(Re)monter un short a la demande, meme s'il depasse la duree ; sans `force`, un montage
    deja fait ou en cours est repris."""
    job = _get(job_id)
    service.enqueue_render(job, _short(job, short_id), force=force)
    return service.detail(job)


class FormatRequest(BaseModel):
    format: str


@router.put("/jobs/{job_id}/format")
def set_format(job_id: str, req: FormatRequest):
    """Changer de format remonte les shorts deja montes (ceux deja montes dans ce format sont repris)."""
    job = _idle(job_id)
    mounted = service.mounted(job)
    try:
        job.state["settings"] = service.clean_settings({**job.state["settings"], "format": req.format})
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    jobs.update(job.id, state=job.state)
    for short in mounted:
        service.enqueue_render(job, short)
    return service.detail(job)


@router.get("/renders/{render_id}/file")
def render_file(render_id: str, download: bool = False):
    job = jobs.get(render_id)
    if job is None or job.kind != service.RENDER_KIND or not service.render_file(job).is_file():
        raise HTTPException(404, "montage introuvable")
    return FileResponse(service.render_file(job), media_type="video/mp4",
                        filename=_filename(job.payload["title"], ".mp4"),
                        content_disposition_type="attachment" if download else "inline")


@router.delete("/jobs/{job_id}")
def remove(job_id: str):
    job = _get(job_id)
    if job.finished:
        service.remove_selection(job)
        jobs.delete(job_id)
    else:
        jobs.cancel(job)
    return {"ok": True}
