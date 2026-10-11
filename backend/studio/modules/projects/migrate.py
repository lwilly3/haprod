"""
Reprise, une seule fois, de ce qui existait avant les projets :

- chaque projet du module Scripts devient un projet (dossier script/ recopié, brief relu) ;
- les recherche.md écrits par Claude deviennent des lignes du tableau des sources ;
- chaque transcription devient un projet « J'ai déjà une vidéo », à l'étape Vidéo source,
  avec la vidéo d'origine (non copiée) et son transcript ; les sélections de shorts et les
  animations qui en dérivent y sont rattachées (project.legacy) pour le portage de ces étapes.

Les données d'origine ne sont pas touchées.
"""
import re
import shutil
from pathlib import Path

from ...core import jobs
from . import media, runtime, service

DONE_KEY = "projects.migrated"
RESEARCH_KEY = "projects.research_migrated"
_URL = re.compile(r"https?://[^\s|)>\]]+")
SCRIPT_FILES = ("notes.md", "recherche.md", "script.md", "angles.md")


def _parse_brief(text: str) -> dict:
    idea, links, section = [], [], None
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip().lower()
        elif line.startswith("# "):
            continue
        elif section and section.startswith("liens"):
            if line.strip().startswith("- "):
                links.append(line.strip()[2:].strip())
        elif section is None:
            idea.append(line)
    return {"idea": "\n".join(idea).strip(), "links": links}


def _from_script(job: jobs.Job) -> None:
    source = Path(job.payload["project_dir"])
    if not source.is_dir() or service.exists(job.id):
        return
    brief = _parse_brief((source / "brief.md").read_text(encoding="utf-8")) if (source / "brief.md").is_file() else {}
    service.create("idea", job.payload.get("name") or "", brief, pid=job.id)
    target = service.project_dir(job.id) / service.SCRIPT_DIR
    for name in SCRIPT_FILES:
        if (source / name).is_file():
            shutil.copy2(source / name, target / name)
    if (source / "sources").is_dir():
        shutil.copytree(source / "sources", target / "sources", dirs_exist_ok=True)
    if (source / "skill").is_dir() and not (target / "skill").is_dir():
        shutil.copytree(source / "skill", target / "skill")
    with service.editing(job.id) as p:
        p["created_at"] = p["opened_at"] = job.created_at
        if (target / "script.md").is_file():
            p["status"] = service.initial_status("script")
        p["legacy"] = {"scripts": job.id}


def _from_transcript(job: jobs.Job, shorts: list[jobs.Job], animations: list[jobs.Job]) -> None:
    if job.state.get("derived") or service.exists(job.id) or job.status != "done":
        return
    sources = [Path(p) for p in job.payload["sources"]]
    if len(sources) != 1 or not sources[0].is_file():
        return
    path = sources[0]
    service.create("video", re.sub(r"[_-]+", " ", path.stem).strip(), {}, pid=job.id)
    info = media.probe(path)
    selections = [s.id for s in shorts if s.kind == "select" and s.payload.get("transcript_job") == job.id]
    anims = [a.id for a in animations if a.kind == "chat" and (a.payload.get("short") or {}).get("selection") in selections]
    with service.editing(job.id) as p:
        p["created_at"] = p["opened_at"] = job.created_at
        p["source"] = {"kind": "import", "path": str(path), "name": path.name, "pending": False,
                       "duration": info.get("duration") or job.state.get("duration"), "width": info.get("width"),
                       "height": info.get("height"), "drift": False, "derived": False, "transcript": job.id}
        p["legacy"] = {"transcript": job.id, "shorts": selections, "animations": anims}


def _research_rows(text: str) -> list[dict]:
    """Chaque ligne (de tableau ou de liste) qui cite une URL : le fait devient le commentaire."""
    found = []
    for line in text.splitlines():
        url = _URL.search(line)
        if not url:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.lstrip().startswith("|") else [line]
        fact = next((c for c in cells if c and not _URL.search(c)), "")
        fact = re.sub(r"^[-*]\s+", "", fact).strip()
        host = re.sub(r"^https?://(www\.)?", "", url.group(0)).split("/")[0]
        found.append({"title": host, "url": url.group(0).rstrip(".,;"), "note": fact})
    return found


def _research() -> None:
    for project in service.list_projects():
        path = service.project_dir(project["id"]) / service.SCRIPT_DIR / "recherche.md"
        if path.is_file():
            rows = _research_rows(path.read_text(encoding="utf-8"))
            with service.editing(project["id"]) as p:
                runtime.add_sources(p, rows)


def run() -> None:
    if not jobs.get_meta(RESEARCH_KEY):
        if jobs.get_meta(DONE_KEY):
            _research()
        jobs.set_meta(RESEARCH_KEY, True)
    if jobs.get_meta(DONE_KEY):
        return
    service.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    shorts = jobs.list_jobs("shorts")
    animations = jobs.list_jobs("animations")
    for job in jobs.list_jobs("scripts"):
        if job.kind == "script":
            _from_script(job)
    for job in jobs.list_jobs("transcript"):
        _from_transcript(job, shorts, animations)
    _research()
    jobs.set_meta(DONE_KEY, True)
