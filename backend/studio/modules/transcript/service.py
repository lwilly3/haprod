"""
Les jobs de transcription vus par le reste du studio : creation, resume, ecriture
des .srt/.txt. Utilisable par n'importe quel module (ex. youtube -> transcription).

payload : sources (chemins), language, output_dir, uploaded
state   : level, segments, parts, duration, detected_language, outputs, extracted
"""
import os
import re
from pathlib import Path

from ...config import DATA_DIR
from ...core import jobs
from . import cues

MODULE = "transcript"
KIND = "transcribe"

# les fichiers glisses dans le navigateur arrivent sans leur chemin d'origine :
# leurs .srt/.txt atterrissent ici
OUTPUT_DIR = Path(os.environ.get("TRANSCRIPT_OUTPUT_DIR", DATA_DIR / "transcripts"))
UPLOAD_DIR = DATA_DIR / "uploads"

MEDIA_EXTENSIONS = ("mov", "mp4", "mxf", "mkv", "avi", "webm", "m4v", "mts",
                    "mp3", "m4a", "wav", "aiff", "aif", "flac", "ogg", "opus", "aac")


def natural_key(path: Path):
    """clip2 avant clip10 ; GX010042 avant GX020042 (chapitres GoPro)."""
    # sur le nom sans extension, sinon "rush-1.mp4" passerait avant "rush.mp4"
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.stem)]


def create_jobs(sources: list[Path], language: str | None, level: str, sequence: bool,
                output_dir: Path | None, uploaded: bool = False,
                job_id: str | None = None) -> list[jobs.Job]:
    """Une tache par fichier, ou une seule pour toute la sequence."""
    if sequence and len(sources) > 1:
        groups = [sorted(sources, key=natural_key)]
    else:
        groups = [[s] for s in sources]
    created = []
    for group in groups:
        payload = {"sources": [str(p) for p in group], "language": language,
                   "output_dir": str(output_dir or group[0].parent), "uploaded": uploaded}
        state = {"level": level, "segments": [], "parts": [], "outputs": [], "extracted": 0}
        created.append(jobs.create(MODULE, KIND, payload, state, job_id=job_id))
    return created


def sources(job: jobs.Job) -> list[Path]:
    return [Path(p) for p in job.payload["sources"]]


def name(job: jobs.Job) -> str:
    srcs = sources(job)
    if len(srcs) == 1:
        return srcs[0].name
    return f"{srcs[0].stem} → {srcs[-1].stem} ({len(srcs)} fichiers)"


def stem(job: jobs.Job) -> str:
    """Nom des fichiers .srt/.txt ecrits."""
    srcs = sources(job)
    return f"{srcs[0].stem}_sequence" if len(srcs) > 1 else srcs[0].stem


def summary(job: jobs.Job) -> dict:
    s = job.state
    return {
        "id": job.id, "name": name(job), "status": job.status,
        "progress": job.progress, "duration": s.get("duration"),
        "language": job.payload["language"], "detected_language": s.get("detected_language"),
        "level": s["level"], "error": job.error, "outputs": s.get("outputs", []),
        "uploaded": job.payload["uploaded"], "sources": job.payload["sources"],
        "parts": s.get("parts", []), "extracted": s.get("extracted", 0),
        "elapsed": job.elapsed,
    }


def detail(job: jobs.Job) -> dict:
    segments = cues.load_segments(job.state.get("segments", []))
    return {**summary(job),
            "cues": {lvl: cues.build_cues(segments, lvl) for lvl in cues.LEVELS}}


def write_outputs(job: jobs.Job, segments: list[cues.Segment], level: str) -> list[str]:
    out_dir = Path(job.payload["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    built = cues.build_cues(segments, level)
    srt = out_dir / f"{stem(job)}.srt"
    txt = out_dir / f"{stem(job)}.txt"
    srt.write_text(cues.to_srt(built), encoding="utf-8")
    txt.write_text(cues.to_txt(built, level), encoding="utf-8")
    return [str(srt), str(txt)]
