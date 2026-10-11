"""
Ce que l'API fait pour un projet au-delà de project.json : appliquer le résultat des
jobs terminés, importer des rushes ou la vidéo source, lancer les transcriptions,
fabriquer le transcript du dérush.
"""
import hashlib
import json
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from ...core import jobs
from ...core.system import tool
from ..settings.service import language as channel_language
from ..transcript import cues
from ..transcript import service as transcript
from . import assets, derush, media, roast, script, service, thumbs
from .service import project_dir

# au-delà, la vidéo importée n'a probablement pas le même montage que le dérush
DRIFT_TOLERANCE = 1.0

_analysis_cache: dict[str, tuple[str, dict]] = {}


# --- Résultats des jobs ------------------------------------------------------------

def sync(project: dict) -> bool:
    """Applique au projet ce que les jobs ont produit depuis la dernière lecture ; True si modifié."""
    changed = _upgrade(project)
    changed |= assets.sync(project)
    changed |= thumbs.sync(project)
    claude_jobs = [("angles", jobs.get(project["jobs"].get("angles") or "")),
                   ("script", jobs.get(project["jobs"].get("script") or "")),
                   ("thumb_ideas", jobs.get(project["jobs"].get("thumb_ideas") or "")),
                   ("titles", jobs.get(project["jobs"].get("titles") or ""))]
    claude_jobs += [("chat", j) for j in service.chat_jobs(project["id"], "angle")]
    for name, job in claude_jobs:
        if job and job.status == "done" and job.state.get("applied") is False:
            result = job.state["result"]
            if name == "angles":
                _apply_angles(project, result)
            elif name == "titles":
                _apply_titles(project, result)
            elif name == "thumb_ideas":
                thumbs.apply_ideas(project, result, job.payload["thumb"])
            add_sources(project, result.get("sources") or [])
            job.state["applied"] = True
            jobs.update(job.id, state=job.state)
            changed = True
    for job_id in list(project["copies"]):
        job = jobs.get(job_id)
        if job and not job.finished:
            continue
        project["copies"].remove(job_id)
        changed = True
        if job and job.status == "done":
            paths = [Path(f["dest"]) for f in job.state["files"]]
            if job.payload["target"] == "rushes":
                add_rushes(project, paths)
            else:
                set_source(project, "import", paths[0])
    render_job = jobs.get(project["jobs"].get("render") or "")
    source = project.get("source")
    if render_job and render_job.status == "done" and source and source.get("pending"):
        dest = Path(render_job.payload["dest"])
        info = media.probe(dest)
        source.update(path=str(dest), name=dest.name, pending=False, duration=info.get("duration"),
                      width=info.get("width"), height=info.get("height"))
        changed = True
    return changed


def _upgrade(project: dict) -> bool:
    """Les projets créés avant l'étape Titre : la donnée et l'étape manquantes. Ceux d'avant la fusion des
    skills de titres : un avis par skill, et `skill` sur chaque titre de Claude."""
    if "titles" not in project:
        project.update(titles=[], titles_round=0, titles_advice="")
        project["status"].setdefault("titre", "skip" if project["mode"] == "video" else "todo")
        return True
    if not isinstance(project.get("titles_advice"), dict):
        return False
    project["titles_advice"] = ""
    for t in project["titles"]:
        if t.pop("skill", None):
            t["ai"] = True
    return True


def _url_key(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url.strip()).rstrip("/").lower()


def add_sources(project: dict, found: list[dict]) -> None:
    """Les sources trouvées par Claude rejoignent le tableau de l'onglet Recherche (sans doublon)."""
    known = {_url_key(s["u"]) for s in project["research"] if s.get("u")}
    added = False
    for f in found:
        url = (f.get("url") or "").strip()
        if not url or _url_key(url) in known:
            continue
        known.add(_url_key(url))
        project["research"].append({"t": f.get("title") or url, "u": url, "n": f.get("note") or "", "by": "claude"})
        added = True
    if added:
        service.write_documentation(project["id"], project["research"])


def _apply_angles(project: dict, result: dict) -> None:
    if result["mode"] == "iterate":
        i = result["index"]
        if 0 <= i < len(project["angles"]):
            old = project["angles"][i]
            a = result["angle"]
            project["angles"][i] = {"t": a["title"], "p": a["promise"], "why": a["why"],
                                    "v": old.get("v", 1) + 1, "note": result["note"]}
        return
    sel = project.get("angle_sel")
    keep = [project["angles"][sel]] if sel is not None and 0 <= sel < len(project["angles"]) else []
    fresh = [{"t": a["title"], "p": a["promise"], "why": a["why"], "v": 1} for a in result["angles"]]
    project["angles"] = keep + [a for a in fresh if not any(k["t"] == a["t"] for k in keep)]
    project["angle_sel"] = 0 if keep else None
    project["angle_round"] = project.get("angle_round", 0) + 1


def _apply_titles(project: dict, result: dict) -> None:
    """Les nouveaux titres de Claude remplacent les anciens, sauf ceux retenus ; ceux ajoutés à la main restent."""
    kept = [t for t in project["titles"] if t.get("pick") or not t.get("ai")]
    known = {t["t"].strip().lower() for t in kept}
    fresh = [{"t": t["title"].strip(), "pattern": t.get("pattern", ""), "why": t.get("why", ""),
              "top": bool(t.get("top")), "ai": True} for t in result["titles"]]
    project["titles"] = kept + [t for t in fresh if t["t"] and t["t"].lower() not in known]
    project["titles_round"] = project.get("titles_round", 0) + 1
    project["titles_advice"] = result.get("message", "")


# --- Rushes ----------------------------------------------------------------------

def _rush_entry(path: Path) -> dict:
    info = media.probe(path)
    shot_at = info.get("shot_at")
    try:
        time_label = datetime.fromisoformat(shot_at).strftime("%H:%M") if shot_at else ""
    except ValueError:
        time_label = ""
    return {"id": "r" + uuid.uuid4().hex[:8], "name": path.name, "path": str(path),
            "size": path.stat().st_size, "time": time_label, "transcript": None, **info}


def add_rushes(project: dict, paths: list[Path]) -> None:
    """Nouveaux rushes : leur transcription part tout de suite (file GPU)."""
    for path in paths:
        rush = _rush_entry(path)
        project["rushes"].append(rush)
        transcribe_rush(project, rush)
        if project["derush"].get("clips") is not None and rush.get("duration"):
            project["derush"]["clips"].append({"id": "c" + uuid.uuid4().hex[:8], "rush": rush["id"],
                                               "in": 0.0, "out": rush["duration"]})
    service.start_step(project, "tournage")
    service.start_step(project, "derush")
    if project["rush_sort"] == "Heure":
        sort_rushes(project, "Heure")


def transcribe_rush(project: dict, rush: dict) -> None:
    out_dir = project_dir(project["id"]) / service.TRANSCRIPTS_DIR
    job = transcript.create_jobs([Path(rush["path"])], channel_language(), "line", False, out_dir)[0]
    rush["transcript"] = job.id


def remove_rush(project: dict, rush_id: str) -> None:
    rush = next((r for r in project["rushes"] if r["id"] == rush_id), None)
    if not rush:
        raise ValueError("rush inconnu")
    job = jobs.get(rush.get("transcript") or "")
    if job and not job.finished:
        jobs.cancel(job)
    project["rushes"].remove(rush)
    prefix = rush_id + ":"
    project["derush"]["cuts"] = {k: v for k, v in project["derush"]["cuts"].items() if not k.startswith(prefix)}
    project["derush"].get("splits", {}).pop(rush_id, None)
    if project["derush"].get("clips") is not None:
        project["derush"]["clips"] = [c for c in project["derush"]["clips"] if c["rush"] != rush_id]
    path = Path(rush["path"])
    # le fichier n'est supprimé que s'il a été copié dans le projet
    if project_dir(project["id"]) in path.parents:
        _unlink_when_free(path)


def _unlink_when_free(path: Path, attempts: int = 30, delay: float = 2.0) -> None:
    """Supprime le fichier ; sous Windows, s'il est encore ouvert (le <video> du navigateur qui le lit
    encore), réessaie en arrière-plan le temps que la lecture soit coupée."""
    try:
        path.unlink(missing_ok=True)
        return
    except PermissionError:
        pass

    def retry() -> None:
        for _ in range(attempts):
            time.sleep(delay)
            try:
                path.unlink(missing_ok=True)
                return
            except PermissionError:
                continue

    threading.Thread(target=retry, daemon=True, name=f"unlink-{path.name}").start()


def rush_levels(pid: str, rush: dict) -> list[int]:
    """Le niveau du son du rush : la crête (0-32767) de chaque 1/PEAKS_RATE s, calculée une fois puis gardée."""
    path = Path(rush["path"])
    key = hashlib.sha1(f"{path}:{path.stat().st_mtime}:{derush.PEAKS_RATE}:raw".encode()).hexdigest()[:10]
    cache = project_dir(pid) / service.DERUSH_DIR / f"levels-{rush['id']}-{key}.json"
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    proc = subprocess.run([tool("ffmpeg"), "-v", "error", "-i", str(path), "-vn", "-ac", "1",
                           "-ar", str(derush.PEAKS_RATE * 50), "-f", "s16le", "-"], capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg : {proc.stderr.decode(errors='replace')[-300:]}")
    levels = derush.frame_levels(proc.stdout, 50)
    cache.parent.mkdir(parents=True, exist_ok=True)
    for old in [*cache.parent.glob(f"levels-{rush['id']}-*.json"), *cache.parent.glob(f"peaks-{rush['id']}-*.json")]:
        old.unlink(missing_ok=True)
    cache.write_text(json.dumps(levels), encoding="utf-8")
    return levels


def rush_peaks(pid: str, rush: dict) -> list[int]:
    """La forme d'onde à afficher (0-100) : rapportée au haut de la voix, pas au pic le plus fort,
    pour qu'un claquement isolé n'écrase pas tout le reste."""
    levels = rush_levels(pid, rush)
    if not levels:
        return []
    top = sorted(levels)[int(len(levels) * 0.995)] or 1
    return [min(100, round(v * 100 / top)) for v in levels]


def _levels_or_none(pid: str, rush: dict) -> list[int] | None:
    try:
        return rush_levels(pid, rush) if Path(rush["path"]).is_file() else None
    except RuntimeError:
        return None


def sort_rushes(project: dict, mode: str) -> None:
    project["rush_sort"] = mode
    if mode == "Heure":
        project["rushes"].sort(key=lambda r: r.get("shot_at") or "")
    elif mode == "Script":
        segs = analysis(project)["segs"]
        first: dict[str, int] = {}
        for s in segs:
            if s["type"] == "speech" and s.get("sec") and s["rush"] not in first:
                first[s["rush"]] = int(s["sec"][1:])
        project["rushes"].sort(key=lambda r: first.get(r["id"], 10_000))
    order_clips(project)


# --- Dérush ------------------------------------------------------------------------

def _signature(project: dict, script_md: str) -> str:
    parts = [script_md]
    for rush in project["rushes"]:
        job = jobs.get(rush.get("transcript") or "")
        parts.append(f"{rush['id']}|{rush.get('duration')}|{job.status if job else ''}|{job.finished_at if job else ''}")
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def analysis(project: dict, edited: bool = True) -> dict:
    """L'analyse du dérush, recalculée seulement quand les transcripts ou le script changent.
    Sans `edited`, les morceaux d'origine : l'interface y applique elle-même coupes et recoupes."""
    script_md = service.read_doc(project["id"], service.SCRIPT_FILE)
    sig = _signature(project, script_md)
    cached = _analysis_cache.get(project["id"])
    if cached and cached[0] == sig:
        result = cached[1]
    else:
        result = derush.analyze(project, script_md, lambda rush: _levels_or_none(project["id"], rush))
        if result["ready"]:
            _analysis_cache[project["id"]] = (sig, result)
    edits = project["derush"]
    # les coupes et les recoupes changent sans invalider l'analyse
    segs = derush.apply_edits(result["segs"], edits.get("splits", {}) if edited else {}, edits["cuts"])
    return {**result, "segs": segs, "transcripts": result["transcripts"] if not result["ready"] else
            [{"rush": r["id"], "status": "done", "progress": 1.0} for r in project["rushes"]]}


def clips(project: dict) -> list[dict]:
    """La timeline du dérush : des bouts de rushes {id, rush, in, out}, dans l'ordre de lecture.
    Tant que l'utilisateur n'y a pas touché, elle découle des anciennes coupes (ou des rushes entiers)."""
    known = {r["id"] for r in project["rushes"]}
    stored = project["derush"].get("clips")
    if stored is not None:
        return [c for c in stored if c["rush"] in known]
    found = analysis(project)
    if found["ready"]:
        return [{"id": f"c{i}", "rush": r["rush"], "in": r["start"], "out": r["end"]}
                for i, r in enumerate(derush.kept_ranges(project, found["segs"]))]
    return [{"id": f"c{i}", "rush": r["id"], "in": 0.0, "out": r["duration"]}
            for i, r in enumerate(project["rushes"]) if r.get("duration")]


def order_clips(project: dict) -> None:
    """Après un changement d'ordre des rushes : les bouts suivent, rush par rush."""
    stored = project["derush"].get("clips")
    if stored is None:
        return
    rank = {r["id"]: i for i, r in enumerate(project["rushes"])}
    stored.sort(key=lambda c: rank.get(c["rush"], len(rank)))


def ranges(project: dict) -> list[dict]:
    """Les plages lues, dans l'ordre, fusionnées quand deux bouts se suivent dans un même rush."""
    rushes = {r["id"]: r for r in project["rushes"]}
    out: list[dict] = []
    for c in clips(project):
        if c["out"] - c["in"] <= 0.01:
            continue
        last = out[-1] if out else None
        if last and last["rush"] == c["rush"] and abs(last["end"] - c["in"]) < 1e-3:
            last["end"] = c["out"]
        else:
            rush = rushes[c["rush"]]
            out.append({"rush": c["rush"], "path": rush["path"], "start": c["in"], "end": c["out"],
                        "audio": rush.get("audio", True)})
    return out


def kept_duration(project: dict) -> float:
    return sum(r["end"] - r["start"] for r in ranges(project))


def render_signature(found: list[dict]) -> str:
    return hashlib.sha1(json.dumps([[r["path"], r["start"], r["end"]] for r in found]).encode()).hexdigest()[:12]


def start_render(project: dict) -> jobs.Job:
    found = ranges(project)
    if not found:
        raise ValueError("rien à exporter : tout est coupé")
    current = jobs.get(project["jobs"].get("render") or "")
    if current and not current.finished:
        jobs.cancel(current)
    first = next(r for r in project["rushes"] if r["id"] == found[0]["rush"])
    fmt = {"width": first.get("width") or 1920, "height": first.get("height") or 1080, "fps": first.get("fps") or 25}
    dest = project_dir(project["id"]) / service.DERUSH_DIR / "derush.mp4"
    job = jobs.create(service.MODULE, "project_render",
                      {"project": project["id"], "ranges": found, "format": fmt, "dest": str(dest),
                       "signature": render_signature(found)}, {})
    project["jobs"]["render"] = job.id
    return job


def render_current(project: dict) -> bool:
    """Le .mp4 exporté correspond-il encore au dérush ?"""
    job = jobs.get(project["jobs"].get("render") or "")
    return bool(job and job.status == "done" and Path(job.payload["dest"]).is_file()
                and job.payload["signature"] == render_signature(ranges(project)))


# --- Vidéo source --------------------------------------------------------------------

def derived_transcript(project: dict, source_path: Path) -> str:
    """Un job de transcription « terminé » dont les segments viennent du dérush."""
    segments = derush.derived_segments(clips(project), project)
    out_dir = project_dir(project["id"]) / service.TRANSCRIPTS_DIR
    payload = {"sources": [str(source_path)], "language": channel_language(), "output_dir": str(out_dir), "uploaded": False}
    duration = kept_duration(project)
    state = {"level": "line", "segments": cues.dump_segments(segments), "parts": [
        {"name": source_path.name, "start": 0.0, "duration": duration}], "outputs": [], "extracted": 1,
        "duration": duration, "detected_language": payload["language"], "derived": True}
    job = jobs.create(transcript.MODULE, transcript.KIND, payload, state, status="done")
    job.state["outputs"] = transcript.write_outputs(job, segments, "line")
    jobs.update(job.id, state=job.state)
    return job.id


def whisper_source(project: dict) -> None:
    source = project["source"]
    out_dir = project_dir(project["id"]) / service.TRANSCRIPTS_DIR
    job = transcript.create_jobs([Path(source["path"])], channel_language(), "line", False, out_dir)[0]
    source.update(transcript=job.id, derived=False, drift=False)


def set_source(project: dict, kind: str, path: Path | None) -> None:
    """La vidéo sur laquelle travaillent les étapes suivantes, et son transcript."""
    service.start_step(project, "transcript")
    has_derush = bool(project["rushes"]) and analysis(project)["ready"]
    if kind == "derush":
        pending = not render_current(project)
        if pending:
            start_render(project)
        dest = project_dir(project["id"]) / service.DERUSH_DIR / "derush.mp4"
        duration = kept_duration(project)
        project["source"] = {"kind": "derush", "path": str(dest), "name": dest.name, "pending": pending,
                             "duration": duration, "width": None, "height": None, "drift": False,
                             "derived": True, "transcript": derived_transcript(project, dest)}
        if not pending:
            info = media.probe(dest)
            project["source"].update(width=info.get("width"), height=info.get("height"))
        return
    info = media.probe(path)
    project["source"] = {"kind": "import", "path": str(path), "name": path.name, "pending": False,
                         "duration": info.get("duration"), "width": info.get("width"), "height": info.get("height"),
                         "drift": False, "derived": False, "transcript": None}
    if has_derush:
        project["source"]["transcript"] = derived_transcript(project, path)
        project["source"]["derived"] = True
        kept = kept_duration(project)
        project["source"]["drift"] = bool(info.get("duration")) and abs(info["duration"] - kept) > DRIFT_TOLERANCE
    else:
        whisper_source(project)


def source_transcript(project: dict) -> dict | None:
    """Le transcript de la vidéo source, phrase par phrase."""
    source = project.get("source") or {}
    job = jobs.get(source.get("transcript") or "")
    if not job:
        return None
    lines = []
    if job.status == "done":
        segments = cues.load_segments(job.state.get("segments", []))
        lines = [{"start": c["start"], "end": c["end"], "text": c["text"]}
                 for c in cues.build_cues(segments, "segment")]
    return {"id": job.id, "status": job.status, "progress": job.progress, "error": job.error,
            "language": job.state.get("detected_language") or job.payload.get("language"),
            "duration": job.state.get("duration"), "lines": lines, "outputs": job.state.get("outputs", [])}


def shorts_view(project: dict) -> dict:
    """La dernière sélection de shorts faite sur le transcript de la vidéo source : shorts, et ceux en montage."""
    from ..animations import service as animations
    from ..shorts import service as shorts

    tid = (project.get("source") or {}).get("transcript")
    found = [j for j in jobs.list_jobs(shorts.MODULE)
             if tid and j.kind == shorts.KIND and j.payload.get("transcript_job") == tid]
    if not found:
        return {"selection": None, "count": 0, "montages": 0}
    last = found[-1]
    return {"selection": last.id, "count": len(last.state.get("shorts", [])),
            "montages": len({short for short, _ in animations.short_projects(last.id)})}


# --- Vue complète pour l'interface ----------------------------------------------------

def view(project: dict) -> dict:
    pid = project["id"]
    script_md = service.read_doc(pid, service.SCRIPT_FILE)
    importing = []
    for job_id in project["copies"]:
        job = jobs.get(job_id)
        if job:
            importing += [{"name": Path(f["dest"]).name, "pct": f.get("pct", 0), "target": job.payload["target"],
                           "error": job.error} for f in job.state["files"]]
    rush_jobs = {}
    for rush in project["rushes"]:
        job = jobs.get(rush.get("transcript") or "")
        rush_jobs[rush["id"]] = ({"status": job.status, "progress": job.progress, "error": job.error}
                                 if job else {"status": "none", "progress": 0, "error": None})
    return {
        **project,
        "runtime": {
            "jobs": {k: service.job_view(v) for k, v in project["jobs"].items()},
            "importing": importing,
            "rush_transcripts": rush_jobs,
            "source_transcript": service.job_view((project.get("source") or {}).get("transcript")),
            "docs": {name: service.doc_mtime(pid, name) for name in service.DOCS},
            "has_script": bool(script_md.strip()),
            "script_words": len(derush.spoken_text(script_md).split()),
            "plans": script.counts(pid),
            "roast_score": roast.last_score(pid, project["jobs"].get("roast")),
            "render_current": render_current(project) if project["rushes"] else False,
            "assets": assets.view(project),
            "thumbs": thumbs.view(),
            "shorts": shorts_view(project),
            "now": time.time(),
        },
    }
