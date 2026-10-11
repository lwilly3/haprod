"""
API du module transcription : file de rushs, transcript, corrections, exports.
"""
import shutil
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from ...core import jobs, system
from ..settings.service import language as channel_language
from . import cues, service

router = APIRouter()


def _language(value: str | None) -> str | None:
    """« auto » : Whisper détecte la langue ; absente : celle de la chaîne."""
    if value == "auto":
        return None
    return value or channel_language()


def _level(value: str) -> str:
    if value not in cues.LEVELS:
        raise HTTPException(400, f"niveau inconnu : {value}")
    return value


def _get(job_id: str) -> jobs.Job:
    job = jobs.get(job_id)
    if job is None or job.module != service.MODULE:
        raise HTTPException(404, "job inconnu")
    return job


def _create(sources: list[Path], language: str, level: str, sequence: bool,
            output_dir: Path | None, uploaded: bool = False,
            job_id: str | None = None) -> list[dict]:
    created = service.create_jobs(sources, _language(language), _level(level), sequence,
                                  output_dir, uploaded, job_id)
    return [service.summary(j) for j in created]


class PathsRequest(BaseModel):
    paths: list[str]
    language: str | None = None
    level: str = "line"
    sequence: bool = False


@router.get("/info")
def info():
    engine = jobs.get_meta("transcript.engine") or {}
    return {**engine, "output_dir": str(service.OUTPUT_DIR),
            "extensions": service.MEDIA_EXTENSIONS}


@router.post("/browse")
def browse():
    return {"paths": system.pick_files("Choisis un ou plusieurs rushs", service.MEDIA_EXTENSIONS)}


@router.post("/jobs")
def add_paths(req: PathsRequest):
    sources = []
    for raw in req.paths:
        # "Copier en tant que chemin d'acces" de Windows entoure le chemin de guillemets
        source = Path(raw.strip().strip('"').strip("'"))
        if not source.is_file():
            raise HTTPException(400, f"Fichier introuvable : {source}")
        sources.append(source)
    return _create(sources, req.language, req.level, req.sequence, output_dir=None)


@router.post("/jobs/upload")
def add_upload(files: list[UploadFile] = File(...), language: str | None = Form(None),
               level: str = Form("line"), sequence: bool = Form(False)):
    sequence = sequence and len(files) > 1
    group_id = uuid.uuid4().hex[:10]
    created, group = [], []
    for file in files:
        # le dossier d'upload porte l'id du job, pour le nettoyer quand on le retire
        job_id = group_id if sequence else uuid.uuid4().hex[:10]
        dest = service.UPLOAD_DIR / job_id / Path(file.filename or "rush").name
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f, length=8 * 1024 * 1024)
        if sequence:
            group.append(dest)
        else:
            created += _create([dest], language, level, False, service.OUTPUT_DIR, True, job_id)
    if group:
        created += _create(group, language, level, True, service.OUTPUT_DIR, True, group_id)
    return created


@router.get("/jobs")
def list_jobs():
    return [service.summary(j) for j in jobs.list_jobs(service.MODULE)]


@router.get("/jobs/{job_id}")
def job_detail(job_id: str):
    return service.detail(_get(job_id))


@router.delete("/jobs/{job_id}")
def remove_job(job_id: str):
    job = _get(job_id)
    if job.finished:
        jobs.delete(job_id)
        if job.payload["uploaded"]:
            shutil.rmtree(service.UPLOAD_DIR / job.id, ignore_errors=True)
    else:
        jobs.cancel(job)
    return {"ok": True}


def _editable(job_id: str) -> tuple[jobs.Job, list[cues.Segment]]:
    job = _get(job_id)
    if job.status != "done":
        raise HTTPException(409, "attends la fin de la transcription pour corriger le texte")
    return job, cues.load_segments(job.state["segments"])


def _commit(job: jobs.Job, segments: list[cues.Segment]) -> None:
    # une ligne videe entierement disparait du transcript
    segments = [s for s in segments if s.words or s.text]
    job.state["segments"] = cues.dump_segments(segments)
    # les fichiers a cote du clip restent toujours a jour des corrections
    job.state["outputs"] = service.write_outputs(job, segments, job.state["level"])
    jobs.update(job.id, state=job.state)


@router.post("/jobs/{job_id}/save")
def save_level(job_id: str, level: str):
    """Reecrit les .srt/.txt a cote du clip avec un autre niveau de decoupage."""
    job, segments = _editable(job_id)
    job.state["level"] = _level(level)
    _commit(job, segments)
    return service.summary(job)


class EditRequest(BaseModel):
    seg: int
    w0: int
    w1: int
    text: str


class ReplaceRequest(BaseModel):
    find: str
    replace: str
    match_case: bool = False


@router.post("/jobs/{job_id}/edit")
def edit(job_id: str, req: EditRequest):
    job, segments = _editable(job_id)
    if not 0 <= req.seg < len(segments):
        raise HTTPException(400, "ligne inconnue (le transcript a change ?)")
    seg = segments[req.seg]
    if not 0 <= req.w0 <= req.w1 <= len(seg.words):
        raise HTTPException(400, "mots inconnus (le transcript a change ?)")
    cues.edit_segment(seg, req.w0, req.w1, req.text)
    _commit(job, segments)
    return service.detail(job)


@router.post("/jobs/{job_id}/replace")
def replace(job_id: str, req: ReplaceRequest):
    job, segments = _editable(job_id)
    if not req.find:
        raise HTTPException(400, "rien a chercher")
    count = cues.replace_all(segments, req.find, req.replace, req.match_case)
    _commit(job, segments)
    return {"count": count, "detail": service.detail(job)}


@router.get("/jobs/{job_id}/export")
def export(job_id: str, level: str = "line", fmt: str = "srt"):
    job = _get(job_id)
    built = cues.build_cues(cues.load_segments(job.state["segments"]), _level(level))
    body = cues.to_srt(built) if fmt == "srt" else cues.to_txt(built, level)
    filename = f"{service.stem(job)}.{'srt' if fmt == 'srt' else 'txt'}"
    return PlainTextResponse(body, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


@router.get("/jobs/{job_id}/media")
def media(job_id: str, part: int = 0):
    srcs = service.sources(_get(job_id))
    if not 0 <= part < len(srcs):
        raise HTTPException(404, "morceau inconnu")
    return FileResponse(srcs[part])
