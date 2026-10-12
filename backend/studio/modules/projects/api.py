"""
API des projets : /api/projects/…
"""
import base64
import shutil
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from ...core import jobs, system
from ..animations import kit
from ..youtube import service as youtube
from . import (assets, autoderush, derush, kit_adapt, library, migrate, montage, publish, render, roast, runtime, script,
               service, storyboard, storyboard_chat, thumbs, timeline, transitions)
from . import beat_anim

router = APIRouter()
migrate.run()


def _check(pid: str) -> None:
    if not service.exists(pid):
        raise HTTPException(404, "projet inconnu")


def _view(pid: str) -> dict:
    """Le projet tel que l'interface l'affiche, après application des jobs terminés."""
    _check(pid)
    return runtime.view(service.load_synced(pid, runtime.sync))


def _save_upload(file: UploadFile, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    dest = service.unique_path(folder, file.filename or "fichier")
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f, length=8 * 1024 * 1024)
    return dest


def _copy_job(pid: str, paths: list[str], folder: Path, target: str) -> None:
    """Copie en tâche de fond de fichiers choisis sur le disque ; appliquée au projet à la fin."""
    files = []
    for raw in paths:
        src = Path(raw.strip().strip('"'))
        if not src.is_file():
            raise HTTPException(400, f"fichier introuvable : {src}")
        dest = service.unique_path(folder, src.name)
        # réserve le nom : deux copies lancées coup sur coup ne visent pas le même fichier
        dest.touch()
        files.append({"src": str(src), "dest": str(dest), "pct": 0})
    job = jobs.create(service.MODULE, "project_copy", {"project": pid, "target": target}, {"files": files})
    with service.editing(pid) as project:
        project["copies"].append(job.id)


# --- Bibliothèque (avant les routes /{pid}) ------------------------------------------

@router.get("/library")
def get_library():
    return {"categories": library.CATEGORIES, "items": library.library()}


@router.get("/library/animations")
def get_animations():
    return {"items": library.animations(), "styles": library.animation_styles()}


@router.get("/library/animations/styles/{style}")
def get_style_animations(style: str):
    items = library.style_animations(style)
    if items is None:
        raise HTTPException(404, "style inconnu")
    return {"items": items}


# une carte d'editing-os et ce qu'elle charge (« ../../tokens.css », polices)
@router.get("/library/animations/editing-os/{rel:path}")
def editing_os_file(rel: str):
    path = library.editing_os_file(rel)
    if not path:
        raise HTTPException(404, "fichier inconnu")
    return FileResponse(path)


# l'exemple sous exemples/ et la charte à côté : son « ../style.css » se résout tout seul.
# La charte est générée depuis le design system : jamais en cache, elle change à chaque réglage.
@router.get("/library/animations/style.css")
def kit_style():
    return Response(kit.style_css(), media_type="text/css", headers={"Cache-Control": "no-store"})


@router.get("/library/animations/exemples/{name}")
@router.get("/library/animations/{name}")
def animation_file(name: str):
    path = library.animation_file(name)
    if not path:
        raise HTTPException(404, "fichier inconnu")
    # la charte porte l'empreinte du design system : une charte déjà en cache n'est jamais reprise
    html = path.read_text(encoding="utf-8").replace('href="../style.css"', f'href="../style.css?v={kit.version()}"')
    return Response(html, media_type="text/html", headers={"Cache-Control": "no-store"})


@router.delete("/library/animations/{name}")
def remove_animation(name: str):
    try:
        kit.remove(name)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"items": library.animations()}


@router.get("/library/kit/design")
def get_design():
    return {"design": kit.design(), "defaults": kit.defaults(), "colors": kit.COLORS, "fonts": kit.FONTS,
            "presets": kit.PRESETS}


@router.put("/library/kit/design")
def put_design(values: dict):
    kit.save_design(values)
    return get_design()


class AdaptRequest(BaseModel):
    style: str
    file: str


@router.get("/library/kit/adapt")
def get_adapts():
    return {"jobs": kit_adapt.view()}


@router.post("/library/kit/adapt")
def start_adapt(req: AdaptRequest):
    """Reporter une inspiration dans le kit : Claude la réécrit avec la charte du kit."""
    try:
        kit_adapt.start(req.style, req.file)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return {"jobs": kit_adapt.view()}


@router.post("/library/upload")
def library_upload(category: str = Form(...), files: list[UploadFile] = File(...)):
    try:
        folder = library.library_folder(category)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    for f in files:
        dest = _save_upload(f, folder)
        library.remember_origin(f"{category}/{dest.name}", None)
    return {"items": library.library()}


@router.get("/library/transitions")
def get_transitions():
    return {"items": transitions.catalog(), "groups": transitions.GROUPS, "dur": transitions.DUR,
            "default_dur": transitions.DEFAULT_DUR}


@router.get("/library/transitions/{fx}.mp4")
def transition_demo(fx: str):
    if fx not in transitions.IDS:
        raise HTTPException(404, "transition inconnue")
    return FileResponse(transitions.demo(fx), media_type="video/mp4", headers={"Cache-Control": "max-age=86400"})


@router.get("/library/file/{category}/{name}")
def library_file(category: str, name: str):
    path = library.LIBRARY_DIR / category / service.safe_name(name)
    if category not in library.CATEGORIES or not path.is_file():
        raise HTTPException(404, "fichier inconnu")
    return FileResponse(path)


class RevealRequest(BaseModel):
    rel: str


class DescribeRequest(BaseModel):
    rel: str
    description: str


@router.post("/library/describe")
def library_describe(req: DescribeRequest):
    try:
        library.describe(req.rel, req.description)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"items": library.library()}


class GainRequest(BaseModel):
    rel: str
    gain_db: float | None = None


@router.post("/library/gain")
def library_gain(req: GainRequest):
    try:
        library.set_gain(req.rel, req.gain_db)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"items": library.library()}


@router.post("/library/reveal")
def library_reveal(req: RevealRequest):
    path = (library.LIBRARY_DIR / req.rel).resolve()
    if library.LIBRARY_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, "fichier inconnu")
    system.reveal(path)
    return {"ok": True}


# --- Projets -----------------------------------------------------------------------

class Brief(BaseModel):
    idea: str = ""
    dir: str = ""
    dur: str = "10–20 min"
    notes: str = ""
    links: list[str] = []


class CreateRequest(BaseModel):
    mode: str = "idea"
    title: str = ""
    brief: Brief = Brief()


@router.get("")
def list_projects():
    out = []
    for p in service.list_projects():
        out.append({k: p.get(k) for k in ("id", "title", "mode", "status", "brief", "created_at", "updated_at",
                                          "opened_at")} | {"angle": (p["angles"][p["angle_sel"]]["t"]
                                                                     if p.get("angle_sel") is not None and p["angles"] else None),
                                                       "thumb": _cover(p),
                                                       "size": sum(service.storage(p["id"]).values())})
    return out


def _cover(project: dict) -> str | None:
    """La vignette affichée à l'accueil : celle de la première variante qui en a une (choisie, sinon la dernière générée)."""
    images = project.get("thumb_images") or {}
    for t in project.get("thumbs") or []:
        file = t.get("image") or next((i["file"] for i in images.get(t.get("id"), [])), None)
        if file:
            return f"{service.VIGNETTES_DIR}/{file}"
    return None


@router.post("")
def create(req: CreateRequest):
    if req.mode not in ("idea", "video"):
        raise HTTPException(400, "mode inconnu")
    if req.mode == "idea" and not req.brief.idea.strip():
        raise HTTPException(400, "l'idée de départ est nécessaire")
    project = service.create(req.mode, req.title, req.brief.model_dump())
    return runtime.view(project)


@router.get("/{pid}")
def get(pid: str):
    return _view(pid)


@router.patch("/{pid}")
def patch(pid: str, changes: dict):
    _check(pid)
    try:
        service.patch(pid, changes)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _view(pid)


@router.get("/{pid}/storage")
def storage(pid: str):
    """Place occupée par le projet, par catégorie, et ce qui reste sur le disque des projets."""
    _check(pid)
    sizes = service.storage(pid)
    return {"total": sum(sizes.values()), "free": shutil.disk_usage(service.PROJECTS_DIR).free,
            "categories": [{"key": k, "bytes": v} for k, v in sizes.items()]}


@router.delete("/{pid}")
def remove(pid: str):
    _check(pid)
    service.remove(pid)
    return {"ok": True}


class StepRequest(BaseModel):
    done: bool


@router.post("/{pid}/steps/{step}")
def complete_step(pid: str, step: str, req: StepRequest):
    _check(pid)
    if step not in service.STEPS:
        raise HTTPException(404, "étape inconnue")
    with service.editing(pid) as project:
        service.complete_step(project, step, req.done)
    return _view(pid)


@router.post("/{pid}/reveal")
def reveal(pid: str, req: RevealRequest):
    _check(pid)
    root = service.project_dir(pid).resolve()
    path = (root / req.rel).resolve()
    if not path.exists():
        raise HTTPException(404, "fichier introuvable")
    system.reveal(path)
    return {"ok": True}


# --- Documents (script, notes) ---------------------------------------------

class DocRequest(BaseModel):
    content: str


@router.get("/{pid}/docs/{name}")
def get_doc(pid: str, name: str):
    _check(pid)
    if name not in service.DOCS:
        raise HTTPException(404, "document inconnu")
    return {"name": name, "content": service.read_doc(pid, name), "mtime": service.doc_mtime(pid, name)}


@router.put("/{pid}/docs/{name}")
def put_doc(pid: str, name: str, req: DocRequest):
    _check(pid)
    try:
        service.write_doc(pid, name, req.content)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"mtime": service.doc_mtime(pid, name)}


# --- Script : les blocs du texte et les plans qui s'y rattachent (voir script.py) -------------

@router.get("/{pid}/script")
def get_script(pid: str):
    _check(pid)
    data = script.load(pid)
    return {"blocks": data["blocks"], "plans": data["plans"], "setups": data["setups"], "sections": data["sections"],
            "mtime": service.doc_mtime(pid, service.SCRIPT_FILE)}


class ScriptBlock(BaseModel):
    id: str
    md: str


class ScriptRequest(BaseModel):
    blocks: list[ScriptBlock]


@router.put("/{pid}/script")
def put_script(pid: str, req: ScriptRequest):
    _check(pid)
    script_job = jobs.get(service.load(pid)["jobs"].get("script") or "")
    if script_job and not script_job.finished:
        raise HTTPException(409, "Claude est en train d'écrire le script")
    try:
        script.save(pid, [b.model_dump() for b in req.blocks])
    except ValueError as e:
        raise HTTPException(409, str(e))
    with service.editing(pid) as project:
        service.start_step(project, "script")
    return {"mtime": service.doc_mtime(pid, service.SCRIPT_FILE)}


class PlansRequest(BaseModel):
    plans: list[dict]


@router.put("/{pid}/script/plans")
def put_plans(pid: str, req: PlansRequest):
    _check(pid)
    try:
        return {"plans": script.save_plans(pid, req.plans)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class SetupsRequest(BaseModel):
    setups: list[dict]
    sections: dict[str, str]


@router.put("/{pid}/script/setups")
def put_setups(pid: str, req: SetupsRequest):
    _check(pid)
    return script.save_setups(pid, req.setups, req.sections)


# --- Claude : angles, titres, script, assistant ------------------------------------------------

class AnglesRequest(BaseModel):
    note: str = ""


def _claude_payload(pid: str, **extra) -> dict:
    return {"project": pid, "dir": str(service.project_dir(pid) / service.SCRIPT_DIR), "web": True, **extra}


@router.post("/{pid}/angles")
def generate_angles(pid: str, req: AnglesRequest):
    _check(pid)
    project = service.load(pid)
    sel = project.get("angle_sel")
    keep = project["angles"][sel] if sel is not None and 0 <= sel < len(project["angles"]) else None
    payload = _claude_payload(pid, mode="generate", note=req.note, keep=keep, existing=project["angles"])
    try:
        job = service.requeue(f"{pid}-angles", "project_angles", payload, {})
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    with service.editing(pid) as p:
        p["jobs"]["angles"] = job.id
    return _view(pid)


class IterateRequest(BaseModel):
    index: int
    note: str


@router.post("/{pid}/angles/iterate")
def iterate_angle(pid: str, req: IterateRequest):
    _check(pid)
    project = service.load(pid)
    if not 0 <= req.index < len(project["angles"]) or not req.note.strip():
        raise HTTPException(400, "angle ou remarque manquant")
    payload = _claude_payload(pid, mode="iterate", index=req.index, note=req.note.strip(),
                              angle=project["angles"][req.index])
    try:
        job = service.requeue(f"{pid}-angles", "project_angles", payload, {})
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    with service.editing(pid) as p:
        p["jobs"]["angles"] = job.id
    return _view(pid)


class TitlesRequest(BaseModel):
    note: str = ""


@router.post("/{pid}/titles")
def generate_titles(pid: str, req: TitlesRequest):
    _check(pid)
    # les projets créés avant l'étape Titre n'ont pas encore le skill
    service.copy_skills(pid)
    project = service.load_synced(pid, runtime.sync)
    sel = project.get("angle_sel")
    angle = project["angles"][sel] if sel is not None and 0 <= sel < len(project["angles"]) else None
    # pas de web : tout est dans le brief, les notes et l'angle
    payload = _claude_payload(pid, web=False, angle=angle, note=req.note,
                              kept=[t["t"] for t in project["titles"] if t.get("pick")],
                              existing=[t["t"] for t in project["titles"] if t.get("ai") and not t.get("pick")])
    try:
        job = service.requeue(f"{pid}-titles", "project_titles", payload, {})
    except ValueError as e:
        raise HTTPException(409, "Claude travaille déjà sur ces titres") from e
    with service.editing(pid) as p:
        p["jobs"]["titles"] = job.id
        service.start_step(p, "titre")
    return _view(pid)


@router.post("/{pid}/script/write")
def write_script(pid: str):
    _check(pid)
    project = service.load(pid)
    sel = project.get("angle_sel")
    angle = project["angles"][sel] if sel is not None and 0 <= sel < len(project["angles"]) else None
    rewrite = bool(service.read_doc(pid, service.SCRIPT_FILE).strip())
    payload = _claude_payload(pid, angle=angle, rewrite=rewrite, duration=project["brief"].get("dur", ""))
    try:
        job = service.requeue(f"{pid}-script", "project_script", payload, {})
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    with service.editing(pid) as p:
        p["jobs"]["script"] = job.id
        service.start_step(p, "script")
    return _view(pid)


# les discussions d'un projet, par sujet (choix de l'angle, script, roast) : chacune est un job
# avec sa propre session Claude ; on en ouvre une nouvelle quand on change de sujet. Celles du
# roast portent sur un roast précis (`scope` : son id).
CHAT_TOPICS = ("angle", "script", "roast")


def _topic(topic: str) -> str:
    if topic not in CHAT_TOPICS:
        raise HTTPException(404, "discussion inconnue")
    return topic


def _scope(pid: str, topic: str, scope: str | None) -> str | None:
    if topic != "roast":
        return None
    if not scope:
        raise HTTPException(400, "quel roast ?")
    _roast_job(pid, scope)
    return scope


def _chat_state(pid: str, topic: str, thread: str | None, scope: str | None = None) -> dict:
    """La discussion `thread` (par défaut la plus récente) et la liste des discussions du sujet."""
    found = service.chat_jobs(pid, topic, scope)
    threads = [{"id": j.id, "title": service.chat_title(j), "created_at": j.created_at} for j in reversed(found)]
    job = next((j for j in found if j.id == thread), None) if thread else (found[-1] if found else None)
    if not job:
        return {"thread": None, "threads": threads, "messages": [], "busy": False, "error": None, "activity": None}
    return {"thread": job.id, "threads": threads, "messages": job.state.get("messages", []), "busy": not job.finished,
            "error": job.error if job.status == "error" else None, "activity": job.state.get("activity")}


@router.get("/{pid}/chat/{topic}")
def get_chat(pid: str, topic: str, thread: str | None = None, scope: str | None = None):
    _check(pid)
    return _chat_state(pid, _topic(topic), thread, _scope(pid, topic, scope))


class ChatRequest(BaseModel):
    text: str
    quote: str | None = None
    # absent : une nouvelle discussion
    thread: str | None = None
    # le roast discuté (sujet « roast »)
    scope: str | None = None


@router.post("/{pid}/chat/{topic}")
def send_chat(pid: str, topic: str, req: ChatRequest):
    _check(pid)
    _topic(topic)
    scope = _scope(pid, topic, req.scope)
    if not req.text.strip():
        raise HTTPException(400, "message vide")
    job = next((j for j in service.chat_jobs(pid, topic, scope) if j.id == req.thread), None) if req.thread else None
    if req.thread and not job:
        raise HTTPException(404, "discussion inconnue")
    job_id = job.id if job else f"{pid}-chat-{topic}-{uuid.uuid4().hex[:6]}"
    state = job.state if job else {"messages": []}
    if job and job.status == "error" and state["messages"] and state["messages"][-1]["role"] == "user":
        # le message resté sans réponse est remplacé par le nouveau
        state["messages"].pop()
    state["messages"].append({"role": "user", "text": req.text.strip(), "quote": req.quote or None})
    try:
        service.requeue(job_id, "project_chat", _claude_payload(pid, topic=topic, scope=scope), state)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return _chat_state(pid, topic, job_id, scope)


# --- Roasting : Claude critique le script (voir roast.py) ----------------------------------------

def _roast_job(pid: str, rid: str) -> jobs.Job:
    job = jobs.get(rid)
    if not job or job.kind != roast.KIND or job.payload.get("project") != pid:
        raise HTTPException(404, "roast inconnu")
    return job


@router.get("/{pid}/roasts")
def get_roasts(pid: str):
    _check(pid)
    return {"runs": [roast.view(j) for j in reversed(roast.project_runs(pid))], **roast.labels()}


class RoastRequest(BaseModel):
    cold: bool = True
    note: str = ""


@router.post("/{pid}/roasts")
def start_roast(pid: str, req: RoastRequest):
    _check(pid)
    try:
        job = roast.start(pid, req.cold, req.note)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    with service.editing(pid) as project:
        project["jobs"]["roast"] = job.id
        service.start_step(project, "roast")
    return _view(pid)


class MarksRequest(BaseModel):
    # id de remarque -> "done", "ignored" ou None (rien)
    marks: dict[str, str | None]


@router.put("/{pid}/roasts/{rid}/marks")
def put_roast_marks(pid: str, rid: str, req: MarksRequest):
    _check(pid)
    job = _roast_job(pid, rid)
    try:
        roast.set_marks(job, req.marks)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"marks": job.state["marks"]}


@router.delete("/{pid}/roasts/{rid}")
def delete_roast(pid: str, rid: str):
    _check(pid)
    job = _roast_job(pid, rid)
    if not job.finished:
        raise HTTPException(409, "le roast est en cours : arrête-le d'abord")
    talks = service.chat_jobs(pid, "roast", rid)
    if any(not j.finished for j in talks):
        raise HTTPException(409, "Claude répond sur ce roast : attends la fin de sa réponse")
    for j in [job, *talks]:
        jobs.delete(j.id)
    return {"ok": True}


class AddAngleRequest(BaseModel):
    title: str
    promise: str = ""
    why: str = ""
    select: bool = False


@router.post("/{pid}/angles/add")
def add_angle(pid: str, req: AddAngleRequest):
    """Un angle proposé dans la discussion rejoint la liste (et peut être retenu d'emblée)."""
    _check(pid)
    if not req.title.strip():
        raise HTTPException(400, "angle sans titre")
    with service.editing(pid) as project:
        project["angles"].append({"t": req.title.strip(), "p": req.promise.strip(), "why": req.why.strip(), "v": 1})
        if req.select:
            project["angle_sel"] = len(project["angles"]) - 1
    return _view(pid)


@router.post("/{pid}/jobs/{name}/stop")
def stop_job(pid: str, name: str):
    _check(pid)
    job = jobs.get(service.load(pid)["jobs"].get(name) or "")
    if job and not job.finished:
        jobs.cancel(job)
    return _view(pid)


# --- Vignettes (fal.ai) --------------------------------------------------------------

class ThumbGenerateRequest(BaseModel):
    models: list[str]


@router.post("/{pid}/thumbs/{tid}/generate")
def generate_thumb(pid: str, tid: str, req: ThumbGenerateRequest):
    _check(pid)
    if not thumbs.ready():
        raise HTTPException(400, "clé fal.ai absente : définis FAL_KEY (setx FAL_KEY \"ta-clé\")")
    with service.editing(pid) as project:
        runtime.sync(project)
        try:
            thumbs.start(project, tid, req.models)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    return _view(pid)


class ThumbEditRequest(BaseModel):
    instruction: str
    models: list[str]


@router.post("/{pid}/thumbs/{tid}/images/{name}/edit")
def edit_thumb_image(pid: str, tid: str, name: str, req: ThumbEditRequest):
    _check(pid)
    if not thumbs.ready():
        raise HTTPException(400, "clé fal.ai absente : définis FAL_KEY (setx FAL_KEY \"ta-clé\")")
    with service.editing(pid) as project:
        runtime.sync(project)
        try:
            thumbs.start_edit(project, tid, name, req.instruction, req.models)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    return _view(pid)


class ThumbIdeasRequest(BaseModel):
    note: str = ""


@router.post("/{pid}/thumbs/{tid}/ideas")
def propose_thumbs(pid: str, tid: str, req: ThumbIdeasRequest):
    _check(pid)
    # les projets créés avant ce skill ne l'ont pas encore
    service.copy_skills(pid)
    project = service.load_synced(pid, runtime.sync)
    try:
        payload = _claude_payload(pid, web=False, **thumbs.ideas_payload(project, tid, req.note))
        job = service.requeue(f"{pid}-thumb-ideas", "project_thumb_ideas", payload, {})
    except ValueError as e:
        raise HTTPException(409 if "travaille" in str(e) else 400, str(e)) from e
    with service.editing(pid) as p:
        p["jobs"]["thumb_ideas"] = job.id
        service.start_step(p, "vignette")
    return _view(pid)


@router.delete("/{pid}/thumbs/{tid}/images/{name}")
def remove_thumb_image(pid: str, tid: str, name: str):
    _check(pid)
    with service.editing(pid) as project:
        runtime.sync(project)
        thumbs.remove_image(project, tid, name)
    return _view(pid)


# --- Rushes -------------------------------------------------------------------------

@router.post("/{pid}/rushes/upload")
def upload_rushes(pid: str, files: list[UploadFile] = File(...)):
    _check(pid)
    folder = service.project_dir(pid) / service.RUSHES_DIR
    paths = [_save_upload(f, folder) for f in files]
    with service.editing(pid) as project:
        runtime.add_rushes(project, paths)
    return _view(pid)


@router.post("/{pid}/rushes/browse")
def browse_rushes(pid: str):
    _check(pid)
    picked = system.pick_files("Choisis les rushes", service.VIDEO_EXTENSIONS)
    if picked:
        _copy_job(pid, picked, service.project_dir(pid) / service.RUSHES_DIR, "rushes")
    return _view(pid)


class SortRequest(BaseModel):
    mode: str


@router.post("/{pid}/rushes/sort")
def sort_rushes(pid: str, req: SortRequest):
    _check(pid)
    if req.mode not in ("Script", "Heure", "Manuel"):
        raise HTTPException(400, "ordre inconnu")
    with service.editing(pid) as project:
        runtime.sort_rushes(project, req.mode)
    return _view(pid)


@router.delete("/{pid}/rushes/{rush_id}")
def delete_rush(pid: str, rush_id: str):
    _check(pid)
    with service.editing(pid) as project:
        try:
            runtime.remove_rush(project, rush_id)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
    return _view(pid)


@router.post("/{pid}/rushes/transcribe")
def transcribe_rushes(pid: str):
    """Relance la transcription des rushes qui n'en ont pas (ou dont elle a échoué)."""
    _check(pid)
    with service.editing(pid) as project:
        for rush in project["rushes"]:
            job = jobs.get(rush.get("transcript") or "")
            if not job or job.status in ("error", "cancelled"):
                runtime.transcribe_rush(project, rush)
    return _view(pid)


@router.post("/{pid}/rushes/{rush_id}/transcribe")
def retranscribe_rush(pid: str, rush_id: str):
    """Refait la transcription d'un rush, même réussie. La timeline (en secondes du rush) est gardée."""
    _check(pid)
    with service.editing(pid) as project:
        rush = next((r for r in project["rushes"] if r["id"] == rush_id), None)
        if not rush:
            raise HTTPException(404, "rush introuvable")
        job = jobs.get(rush.get("transcript") or "")
        if job and not job.finished:
            jobs.cancel(job)
        runtime.transcribe_rush(project, rush)
    return _view(pid)


@router.get("/{pid}/rushes/{rush_id}/media")
def rush_media(pid: str, rush_id: str):
    _check(pid)
    rush = next((r for r in service.load(pid)["rushes"] if r["id"] == rush_id), None)
    if not rush or not Path(rush["path"]).is_file():
        raise HTTPException(404, "rush introuvable")
    return FileResponse(rush["path"])


@router.get("/{pid}/rushes/{rush_id}/peaks")
def rush_peaks(pid: str, rush_id: str):
    """La forme d'onde du rush (une crête 0-100 par 1/RUSH_PEAKS_RATE s), calculée une fois puis gardée."""
    _check(pid)
    rush = next((r for r in service.load(pid)["rushes"] if r["id"] == rush_id), None)
    if not rush or not Path(rush["path"]).is_file():
        raise HTTPException(404, "rush introuvable")
    try:
        return {"rate": derush.PEAKS_RATE, "peaks": runtime.rush_peaks(pid, rush)}
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e


# --- Dérush -------------------------------------------------------------------------

@router.get("/{pid}/derush")
def get_derush(pid: str):
    _check(pid)
    project = service.load(pid)
    return {**runtime.analysis(project, edited=False), "clips": runtime.clips(project)}


class AutoDerushRequest(BaseModel):
    # consigne de l'auteur pour ce dérush (« garde la prise la plus énergique »…)
    note: str = ""


@router.get("/{pid}/derush/auto")
def get_auto_derush(pid: str):
    """Les coupes proposées par Daryl (ou l'avancement de sa lecture)."""
    _check(pid)
    return autoderush.result(service.load(pid)["jobs"].get("autoderush"))


@router.post("/{pid}/derush/auto")
def start_auto_derush(pid: str, req: AutoDerushRequest):
    _check(pid)
    project = service.load(pid)
    if not runtime.analysis(project)["ready"]:
        raise HTTPException(409, "les rushes doivent d'abord être transcrits")
    payload = {"project": pid, "dir": str(service.project_dir(pid) / service.DERUSH_DIR), "note": req.note}
    try:
        job = service.requeue(f"{pid}-autoderush", autoderush.KIND, payload, {})
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    with service.editing(pid) as p:
        p["jobs"]["autoderush"] = job.id
    return _view(pid)


@router.get("/{pid}/derush/export.xml")
def export_xml(pid: str):
    _check(pid)
    project = service.load(pid)
    found = runtime.ranges(project)
    if not found:
        raise HTTPException(400, "rien à exporter")
    body = derush.timeline_xml(project, found, f"{project['title']} — dérush")
    dest = service.project_dir(pid) / service.DERUSH_DIR / "derush.xml"
    dest.write_text(body, encoding="utf-8")
    return Response(body, media_type="application/xml", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(service.safe_name(project['title']) + '-derush.xml')}"})


@router.get("/{pid}/derush/export.fcpxml")
def export_fcpxml(pid: str):
    _check(pid)
    project = service.load(pid)
    found = runtime.ranges(project)
    if not found:
        raise HTTPException(400, "rien à exporter")
    body = timeline.fcpxml(timeline.from_ranges(project, found), f"{project['title']} — dérush")
    dest = service.project_dir(pid) / service.DERUSH_DIR / "derush.fcpxml"
    dest.write_text(body, encoding="utf-8")
    return Response(body, media_type="application/xml", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(service.safe_name(project['title']) + '-derush.fcpxml')}"})


@router.post("/{pid}/derush/export.mp4")
def export_mp4(pid: str):
    _check(pid)
    with service.editing(pid) as project:
        try:
            runtime.start_render(project)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    return _view(pid)


@router.get("/{pid}/derush/export.mp4")
def download_mp4(pid: str):
    _check(pid)
    path = service.project_dir(pid) / service.DERUSH_DIR / "derush.mp4"
    if not path.is_file():
        raise HTTPException(404, "pas encore exporté")
    return FileResponse(path, filename="derush.mp4")


# --- Vidéo source ---------------------------------------------------------------------

@router.post("/{pid}/source/upload")
def upload_source(pid: str, file: UploadFile = File(...)):
    _check(pid)
    dest = _save_upload(file, service.project_dir(pid) / service.SOURCE_DIR)
    with service.editing(pid) as project:
        runtime.set_source(project, "import", dest)
    return _view(pid)


@router.post("/{pid}/source/browse")
def browse_source(pid: str):
    _check(pid)
    picked = system.pick_files("Choisis la vidéo", service.VIDEO_EXTENSIONS)
    if picked:
        _copy_job(pid, picked[:1], service.project_dir(pid) / service.SOURCE_DIR, "source")
    return _view(pid)


@router.post("/{pid}/source/derush")
def use_derush(pid: str):
    _check(pid)
    with service.editing(pid) as project:
        if not project["rushes"] or not runtime.analysis(project)["ready"]:
            raise HTTPException(400, "le dérush n'est pas prêt")
        runtime.set_source(project, "derush", None)
    return _view(pid)


@router.post("/{pid}/source/transcribe")
def transcribe_source(pid: str):
    _check(pid)
    with service.editing(pid) as project:
        if not project.get("source") or project["source"].get("pending"):
            raise HTTPException(400, "pas de vidéo source")
        runtime.whisper_source(project)
    return _view(pid)


@router.delete("/{pid}/source")
def reset_source(pid: str):
    _check(pid)
    with service.editing(pid) as project:
        project["source"] = None
    return _view(pid)


@router.get("/{pid}/source/transcript")
def get_source_transcript(pid: str):
    _check(pid)
    return runtime.source_transcript(service.load(pid))


@router.get("/{pid}/source/media")
def source_media(pid: str):
    _check(pid)
    source = service.load(pid).get("source") or {}
    if not source.get("path") or not Path(source["path"]).is_file() or source.get("pending"):
        raise HTTPException(404, "vidéo introuvable")
    return FileResponse(source["path"])


# --- Ressources du projet ----------------------------------------------------------------

@router.get("/{pid}/resources")
def get_resources(pid: str):
    _check(pid)
    return runtime_resources(pid)


def runtime_resources(pid: str) -> dict:
    return {"groups": library.resources(service.load(pid))}


@router.post("/{pid}/resources/upload")
def upload_resources(pid: str, files: list[UploadFile] = File(...)):
    _check(pid)
    for f in files:
        _save_upload(f, service.project_dir(pid) / service.RESOURCES_DIR)
    return runtime_resources(pid)


class ToLibraryRequest(BaseModel):
    rel: str
    category: str


@router.post("/{pid}/resources/to-library")
def to_library(pid: str, req: ToLibraryRequest):
    """Un fichier du projet versé dans la bibliothèque commune (copie)."""
    _check(pid)
    root = service.project_dir(pid).resolve()
    src = (root / req.rel).resolve()
    if root not in src.parents or not src.is_file():
        raise HTTPException(404, "fichier inconnu")
    try:
        folder = library.library_folder(req.category)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    dest = service.unique_path(folder, src.name)
    shutil.copy2(src, dest)
    library.remember_origin(f"{req.category}/{dest.name}", service.load(pid)["title"])
    return {"ok": True, "name": dest.name}


@router.get("/{pid}/files/{rel:path}")
def project_file(pid: str, rel: str):
    """Un fichier du projet (aperçu d'une capture, d'un asset)."""
    _check(pid)
    root = service.project_dir(pid).resolve()
    path = (root / rel).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "fichier introuvable")
    return FileResponse(path)


# --- Assets : YouTube --------------------------------------------------------------------

class VideoRequest(BaseModel):
    url: str


@router.post("/{pid}/assets/videos")
def preview_video(pid: str, req: VideoRequest):
    """Aperçu d'un lien (titre, durée, résolutions), gardé dans la liste des vidéos prévisualisées."""
    _check(pid)
    url = req.url.strip()
    if not url:
        raise HTTPException(400, "lien vide")
    try:
        info = youtube.probe(url)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    with service.editing(pid) as project:
        runtime.sync(project)
        assets.add_video(project, info)
    return _view(pid)


@router.delete("/{pid}/assets/videos/{vid}")
def forget_video(pid: str, vid: str):
    """Retire une vidéo de la liste (ses téléchargements restent)."""
    _check(pid)
    with service.editing(pid) as project:
        runtime.sync(project)
        project["assets"]["videos"] = [v for v in project["assets"]["videos"] if v["id"] != vid]
    return _view(pid)


class ClipRange(BaseModel):
    start: float
    end: float


class DownloadRequest(BaseModel):
    video: str
    # absent : la vidéo entière
    clip: ClipRange | None = None
    mode: str = "video"
    max_height: int | None = 1080
    transcribe: bool = False
    # absente : la langue de la chaîne ; « auto » : Whisper la détecte
    language: str | None = None
    precise: bool = True
    common: bool = False
    category: str = "broll"


@router.post("/{pid}/assets/downloads")
def download(pid: str, req: DownloadRequest):
    _check(pid)
    if req.mode not in ("video", "audio", "thumbnail"):
        raise HTTPException(400, f"mode inconnu : {req.mode}")
    if req.mode == "thumbnail":
        # une image : ni extrait ni transcription
        req.clip, req.transcribe = None, False
    if req.clip and (req.clip.start < 0 or req.clip.end <= req.clip.start):
        raise HTTPException(400, "extrait invalide")
    with service.editing(pid) as project:
        runtime.sync(project)
        video = next((v for v in project["assets"]["videos"] if v["id"] == req.video), None)
        if not video:
            raise HTTPException(404, "vidéo inconnue")
        try:
            assets.start_download(project, video, req.model_dump(), req.clip.model_dump() if req.clip else None,
                                  req.common, req.category)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    return _view(pid)


@router.delete("/{pid}/assets/downloads/{job_id}")
def remove_download(pid: str, job_id: str):
    """Annule un téléchargement en cours, ou le retire de la liste (le fichier reste)."""
    _check(pid)
    with service.editing(pid) as project:
        runtime.sync(project)
        job = jobs.get(job_id)
        if job and not job.finished:
            jobs.cancel(job)
        else:
            project["assets"]["downloads"] = [d for d in project["assets"]["downloads"] if d["job"] != job_id]
    return _view(pid)


# --- Assets : images -------------------------------------------------------------------

@router.get("/{pid}/assets/images")
def get_images(pid: str):
    _check(pid)
    return assets.images_state(pid)


class ImagesRequest(BaseModel):
    text: str


@router.post("/{pid}/assets/images")
def search_images(pid: str, req: ImagesRequest):
    _check(pid)
    if not req.text.strip():
        raise HTTPException(400, "demande vide")
    job = jobs.get(assets.images_job_id(pid))
    state = job.state if job else {"messages": [], "results": []}
    if job and job.status == "error" and state["messages"] and state["messages"][-1]["role"] == "user":
        # la demande restée sans réponse est remplacée par la nouvelle
        state["messages"].pop()
    state["messages"].append({"role": "user", "text": req.text.strip()})
    try:
        service.requeue(assets.images_job_id(pid), "project_images", _claude_payload(pid), state)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return assets.images_state(pid)


class AddImagesRequest(BaseModel):
    ids: list[str]
    common: bool = False
    category: str = "images"


@router.post("/{pid}/assets/images/add")
def add_images(pid: str, req: AddImagesRequest):
    _check(pid)
    try:
        count = assets.add_images(pid, req.ids, req.common, req.category, service.load(pid)["title"])
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return {"added": count, **assets.images_state(pid)}


@router.get("/{pid}/assets/candidates/{name}")
def candidate(pid: str, name: str):
    _check(pid)
    path = assets.candidates_dir(pid) / service.safe_name(name)
    if not path.is_file():
        raise HTTPException(404, "image inconnue")
    return FileResponse(path)


# --- Assets : captures des sources ------------------------------------------------------

class CaptureRequest(BaseModel):
    # des sources précises (capturées à nouveau si elles l'étaient déjà) ; sinon les cochées pas encore capturées
    urls: list[str] | None = None


def _is_web(url: str) -> bool:
    return url.startswith(("http://", "https://"))


@router.post("/{pid}/assets/captures")
def capture_sources(pid: str, req: CaptureRequest | None = None):
    """Capture des sources (celles en erreur sont retentées) ; en cours, le job les ajoute à sa file."""
    _check(pid)
    urls = req.urls if req else None
    project = service.load_synced(pid, runtime.sync)
    a = project["assets"]
    sources = [{"u": s["u"], "t": s.get("t") or s["u"]} for s in project["research"] if _is_web(s.get("u", ""))
               and (s["u"] in urls if urls is not None
                    else a["capture"].get(s["u"]) and not (a["captures"].get(s["u"]) or {}).get("rel"))]
    queued = set(assets.capture_queue(project))
    sources = [s for s in sources if s["u"] not in queued]
    if not sources:
        if urls and queued.issuperset(urls):
            return _view(pid)
        raise HTTPException(400, "aucune source à capturer")
    with service.editing(pid) as p:
        for s in sources:
            p["assets"]["capture"][s["u"]] = True
            # recapturer remplace l'image choisie à la main
            if (p["assets"]["captures"].get(s["u"]) or {}).get("manual"):
                del p["assets"]["captures"][s["u"]]
    job_id = f"{pid}-captures"
    job = jobs.get(job_id)
    if job and not job.finished:
        jobs.update(job_id, payload={**job.payload, "sources": job.payload["sources"] + sources})
        job = jobs.get(job_id)
    if not job or job.finished:
        folder, _ = library.destination(pid, False, "images")
        job = service.requeue(job_id, "project_captures",
                              {"project": pid, "sources": sources, "dest": str(folder)}, {"done": {}, "next": 0})
    with service.editing(pid) as p:
        p["jobs"]["captures"] = job.id
    return _view(pid)


@router.post("/{pid}/assets/captures/upload")
def upload_capture(pid: str, url: str = Form(...), file: UploadFile = File(...)):
    """Une image choisie à la main pour une source, à la place de la capture."""
    _check(pid)
    project = service.load(pid)
    source = next((s for s in project["research"] if s.get("u") == url), None)
    if not source:
        raise HTTPException(404, "source inconnue")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in library.IMAGE_EXT or ext == ".psd":
        raise HTTPException(400, "il faut une image (png, jpg, webp, gif, svg)")
    folder, _ = library.destination(pid, False, "images")
    file.filename = f"Capture - {(source.get('t') or url)[:80]}{ext}"
    dest = _save_upload(file, folder)
    with service.editing(pid) as p:
        p["assets"]["captures"][url] = {"rel": dest.relative_to(service.project_dir(pid)).as_posix(),
                                        "error": None, "manual": True}
    return _view(pid)


# --- Montage de la vidéo longue ----------------------------------------------------------

def _montage_tasks(pid: str) -> list[jobs.Job]:
    """Les demandes faites à Daryl dans le chat du montage, une tâche (et une conversation) chacune, dans l'ordre où
    elles ont été faites ; le worker en traite plusieurs à la fois (montage.TASK_SLOTS)."""
    found = [j for j in jobs.list_jobs(service.MODULE) if j.kind in montage.TASK_KINDS and j.payload.get("project") == pid]
    return sorted(found, key=lambda j: j.created_at)


def _montage_task(pid: str, task: str) -> jobs.Job:
    job = jobs.get(task)
    if not job or job.kind not in montage.TASK_KINDS or job.payload.get("project") != pid:
        raise HTTPException(404, "demande introuvable")
    return job


def _task_status(job: jobs.Job) -> str:
    return job.status if job.status == "queued" or job.finished else "running"


def _montage_busy(pid: str) -> bool:
    """Daryl est en train de traiter une demande (pas seulement en file)."""
    return any(_task_status(j) == "running" for j in _montage_tasks(pid))


def _montage_view(pid: str) -> dict:
    project = service.load(pid)
    source = montage._source(project)
    timeline = montage.load(pid)
    montage.ensure_media(pid, project)
    tasks = _montage_tasks(pid)
    # l'utilisation de l'abonnement : la dernière connue
    last = max((j for j in tasks if j.state.get("usage")), key=lambda j: j.started_at or 0, default=None)
    path = montage.export_path(pid)
    return {
        "timeline": timeline,
        # l'empreinte de cette version : une retouche faite dessus est fusionnée si la timeline a changé depuis
        "rev": montage.rev(pid),
        "source": {"url": f"/api/projects/{pid}/source/media?v={quote(f'{source['path']}:{source.get('duration')}')}",
                   "name": source["name"], "duration": source.get("duration") or 0.0,
                   "width": source.get("width") or 1920, "height": source.get("height") or 1080,
                   "fps": montage.source_fps(source)} if source else None,
        "analysis": montage.media_state(pid, project),
        "media": montage.media_of(pid, timeline),
        "motions": montage.motion_states(pid, timeline),
        "can_undo": bool(montage.history_steps(pid)),
        "export": {"rel": path.relative_to(service.project_dir(pid)).as_posix(), "name": path.name,
                   "exists": path.is_file()},
        "tasks": [{"id": j.id, "status": _task_status(j), "messages": j.state.get("messages", []),
                   "activity": j.state.get("activity"), "error": j.error if j.status == "error" else None} for j in tasks],
        "busy": any(_task_status(j) == "running" for j in tasks),
        "usage": last.state.get("usage") if last else None,
    }


@router.get("/{pid}/montage")
def get_montage(pid: str):
    _check(pid)
    return _montage_view(pid)


@router.get("/{pid}/montage/media")
def montage_media(pid: str):
    """B-roll, musique et sons utilisables : ceux du projet et de la bibliothèque."""
    _check(pid)
    return montage.available(pid)


class MontageRequest(BaseModel):
    timeline: dict
    # les insertions dans l'A-roll que contient cette timeline : les beats du storyboard les suivent
    beats_shift: list[dict] = []
    # l'empreinte de la version retouchée
    rev: str | None = None


@router.put("/{pid}/montage")
def put_montage(pid: str, req: MontageRequest):
    _check(pid)
    montage.prepare(pid)
    montage.save(pid, req.timeline, shifts=req.beats_shift, base=req.rev)
    with service.editing(pid) as p:
        service.start_step(p, "montage")
    return _montage_view(pid)


@router.post("/{pid}/montage/undo")
def undo_montage(pid: str):
    _check(pid)
    try:
        # pendant un tour de Daryl, ses compositions en cours d'écriture restent telles quelles
        montage.undo(pid, motions=not _montage_busy(pid))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    montage.after_change(pid)
    return _montage_view(pid)


class MontageChatRequest(BaseModel):
    text: str
    # la sélection dans la timeline : {"range": [a, b]} ou {"item": {"track", "id"}}
    selection: dict | None = None
    # l'image où le client a mis en pause pour en parler (temps de la timeline) : Daryl la regarde
    frame: float | None = None
    # l'image telle que le client la voit dans l'aperçu (A-roll, B-roll, motion, beats) : data URL JPEG
    image: str | None = None
    # la demande à laquelle on répond (sa conversation continue) ; absente : une nouvelle demande, mise en file
    task: str | None = None


def _save_view(pid: str, data_url: str) -> str:
    """Enregistre l'image de l'aperçu dans montage/frames/ ; rend son chemin relatif au projet."""
    head, _, data = data_url.partition(",")
    if not head.startswith("data:image/jpeg;base64"):
        raise HTTPException(400, "image attendue en JPEG")
    try:
        raw = base64.b64decode(data, validate=True)
    except ValueError as e:
        raise HTTPException(400, "image illisible") from e
    folder = montage.root(pid) / storyboard_chat.FRAMES_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"view-{round(time.time() * 1000)}.jpg"
    path.write_bytes(raw)
    return path.relative_to(service.project_dir(pid)).as_posix()


@router.post("/{pid}/montage/chat")
def montage_chat(pid: str, req: MontageChatRequest):
    _check(pid)
    if not req.text.strip():
        raise HTTPException(400, "message vide")
    job = _montage_task(pid, req.task) if req.task else None
    state = job.state if job else {"messages": []}
    # une demande ratée ou arrêtée avant d'être traitée : remplacée par la nouvelle
    if job and job.status in ("error", "cancelled") and state["messages"] and state["messages"][-1]["role"] == "user":
        state["messages"].pop()
    state["messages"].append({"role": "user", "text": req.text.strip(), "selection": req.selection or None,
                              "frame": req.frame, "image": _save_view(pid, req.image) if req.image else None,
                              "at": time.time()})
    # la file la moins chargée : plusieurs demandes sont traitées à la fois
    slot = montage.task_slot()
    if job and job.finished:
        jobs.update(job.id, kind=slot)
    try:
        job = service.requeue(job.id if job else f"{pid}-montage-{uuid.uuid4().hex[:8]}", slot, {"project": pid}, state)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    with service.editing(pid) as p:
        service.start_step(p, "montage")
    return {**_montage_view(pid), "task": job.id}


class MontageTaskRequest(BaseModel):
    task: str


@router.post("/{pid}/montage/stop")
def stop_montage(pid: str, req: MontageTaskRequest):
    """Arrête une demande en cours, ou la retire de la file."""
    _check(pid)
    job = _montage_task(pid, req.task)
    if not job.finished:
        jobs.cancel(job)
    return _montage_view(pid)


@router.delete("/{pid}/montage/tasks/{task}")
def delete_montage_task(pid: str, task: str):
    """Retire une demande terminée de la liste (ses changements restent dans la timeline)."""
    _check(pid)
    job = _montage_task(pid, task)
    if not job.finished:
        raise HTTPException(409, "Daryl travaille sur cette demande : arrête-la d'abord")
    jobs.delete(job.id)
    return _montage_view(pid)


class StoryboardRequest(BaseModel):
    density: str = storyboard.DEFAULT_DENSITY
    # consigne de l'auteur (« peu de plein écran », « insiste sur les chiffres »…)
    note: str = ""
    # les types de beats à proposer (motion, zoom, broll, transition) ; absent : tous
    types: list[str] | None = None


@router.get("/{pid}/montage/storyboard")
def get_storyboard(pid: str):
    """Le storyboard proposé par Daryl, ses contrôles, ou l'avancement de sa génération."""
    _check(pid)
    return storyboard.view(pid)


@router.post("/{pid}/montage/storyboard")
def start_storyboard(pid: str, req: StoryboardRequest):
    _check(pid)
    if req.density not in storyboard.DENSITIES:
        raise HTTPException(400, "densité inconnue")
    if not montage._source(service.load(pid)):
        raise HTTPException(409, "pas de vidéo source")
    montage.prepare(pid)
    payload = {"project": pid, "dir": str(montage.root(pid)), "density": req.density, "note": req.note,
               "types": [t for t in (req.types or storyboard.TYPES) if t in storyboard.TYPES] or storyboard.TYPES}
    try:
        service.requeue(storyboard.job_id(pid), storyboard.KIND, payload, {})
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    with service.editing(pid) as p:
        service.start_step(p, "storyboard")
    return storyboard.view(pid)


class StoryboardEditRequest(BaseModel):
    # les beats gardés : {id, show?, kind?, place?, sfx?, on?, at?, dur?}
    beats: list[dict]


@router.put("/{pid}/montage/storyboard")
def put_storyboard(pid: str, req: StoryboardEditRequest):
    _check(pid)
    if any((j := jobs.get(k)) and not j.finished for k in (storyboard.job_id(pid), storyboard_chat.job_id(pid))):
        raise HTTPException(409, "Daryl est en train d'écrire le storyboard")
    try:
        storyboard.edit(pid, req.beats)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return storyboard.view(pid)


class BeatAddRequest(BaseModel):
    # motion, zoom, broll ou transition
    type: str = "motion"
    at: float
    dur: float = storyboard.HAND_DUR
    show: str = ""


@router.post("/{pid}/montage/storyboard/beats")
def add_beat(pid: str, req: BeatAddRequest):
    """Un beat posé à la main sur la timeline du montage ; rend le storyboard et l'id du beat (`added`)."""
    _check(pid)
    if any((j := jobs.get(k)) and not j.finished for k in (storyboard.job_id(pid), storyboard_chat.job_id(pid))):
        raise HTTPException(409, "Daryl est en train d'écrire le storyboard")
    try:
        added = storyboard.add(pid, req.type, req.at, req.dur, req.show)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {**storyboard.view(pid), "added": added}


class StoryboardChatRequest(BaseModel):
    text: str
    # le moment de la timeline dont on parle, le beat choisi, et si l'image de la vidéo est jointe
    at: float | None = None
    beat: str | None = None
    frame: bool = False


@router.post("/{pid}/montage/storyboard/chat")
def storyboard_chat_send(pid: str, req: StoryboardChatRequest):
    """Une demande à Daryl sur le storyboard ; ses changements sont appliqués à la fin de son tour."""
    _check(pid)
    if not req.text.strip():
        raise HTTPException(400, "message vide")
    gen = jobs.get(storyboard.job_id(pid))
    if gen and not gen.finished:
        raise HTTPException(409, "Daryl est en train d'écrire le storyboard")
    job = jobs.get(storyboard_chat.job_id(pid))
    state = job.state if job else {"messages": []}
    if job and job.status == "error" and state["messages"] and state["messages"][-1]["role"] == "user":
        state["messages"].pop()
    state["messages"].append({"role": "user", "text": req.text.strip(), "at": req.at, "beat": req.beat,
                              "frame": bool(req.frame and req.at is not None)})
    payload = {"project": pid, "dir": str(service.project_dir(pid))}
    try:
        service.requeue(storyboard_chat.job_id(pid), storyboard_chat.KIND, payload, state)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    with service.editing(pid) as p:
        service.start_step(p, "storyboard")
    return storyboard.view(pid)


@router.post("/{pid}/montage/storyboard/chat/stop")
def storyboard_chat_stop(pid: str):
    _check(pid)
    job = jobs.get(storyboard_chat.job_id(pid))
    if job and not job.finished:
        jobs.cancel(job)
    return storyboard.view(pid)


class AnimateRequest(BaseModel):
    # les beats à animer ; absent : tous les beats cochés pas encore animés
    beats: list[str] | None = None


@router.post("/{pid}/montage/storyboard/animate")
def animate_storyboard(pid: str, req: AnimateRequest):
    """Les beats entrent dans la timeline : zooms et B-roll vidéo posés tels quels ; motions, transitions et
    images en motion (place, durée, son), puis une tâche par beat écrit son animation, SLOTS à la fois."""
    _check(pid)
    if _montage_busy(pid):
        raise HTTPException(409, "Daryl modifie la timeline dans le chat : attends la fin de sa réponse")
    montage.prepare(pid)
    try:
        done = storyboard.compose(pid, req.beats)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    by_motion = {m: b for b, m in storyboard.composed(montage.load(pid)).items()}
    for mid in done["motions"]:
        beat_anim.enqueue(pid, by_motion[mid], mid)
    with service.editing(pid) as p:
        service.start_step(p, "montage")
    queued = {by_motion[m] for m in done["motions"]}
    return {"queued": sorted(queued), "placed": [b for b in done["placed"] if b not in queued],
            "skipped": done["skipped"], "missing": done["missing"]}


class AnimateStopRequest(BaseModel):
    beat: str


@router.post("/{pid}/montage/storyboard/animate/stop")
def stop_animation(pid: str, req: AnimateStopRequest):
    _check(pid)
    job = jobs.get(beat_anim.job_id(pid, req.beat))
    if job and not job.finished:
        jobs.cancel(job)
    return storyboard.view(pid)


@router.post("/{pid}/montage/storyboard/stop")
def stop_storyboard(pid: str):
    _check(pid)
    job = jobs.get(storyboard.job_id(pid))
    if job and not job.finished:
        jobs.cancel(job)
    return storyboard.view(pid)


@router.post("/{pid}/montage/export")
def export_montage(pid: str):
    """Refait l'export FCPXML ; renvoie ce qui n'a pas pu y entrer."""
    _check(pid)
    try:
        path, problems = montage.export(pid)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"rel": path.relative_to(service.project_dir(pid)).as_posix(), "name": path.name, "problems": problems}


# --- Rendu final ------------------------------------------------------------------------

def _rendu_view(pid: str, quality: str, selection: str | None) -> dict:
    project = service.load(pid)
    return {"long": render.view(project, quality), "shorts": render.shorts(project, selection)}


@router.get("/{pid}/rendu")
def get_rendu(pid: str, quality: str = "1080p", selection: str | None = None):
    """La vidéo longue dans cette qualité, et les shorts de la sélection (la dernière par défaut)."""
    _check(pid)
    return _rendu_view(pid, quality, selection)


class RenduRequest(BaseModel):
    # "long" : la vidéo longue ; sinon l'id d'un short de la sélection
    target: str
    quality: str = "1080p"
    selection: str | None = None


@router.post("/{pid}/rendu")
def start_rendu(pid: str, req: RenduRequest):
    """Lance un rendu : la vidéo longue, ou un short."""
    _check(pid)
    try:
        if req.target == "long":
            long = render.view(service.load(pid), req.quality)
            if long["status"] not in ("none", *jobs.FINISHED):
                raise ValueError("un rendu de la vidéo longue est déjà en cours")
            with service.editing(pid) as project:
                render.start(project, req.quality)
        else:
            items = render.shorts(service.load(pid), req.selection)["items"]
            item = next((i for i in items if i["id"] == req.target), None)
            if item is None:
                raise HTTPException(404, "short inconnu")
            render.start_short(item)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    with service.editing(pid) as project:
        service.start_step(project, "rendu")
    return _rendu_view(pid, req.quality, req.selection)


@router.post("/{pid}/rendu/stop")
def stop_rendu(pid: str, req: RenduRequest):
    _check(pid)
    project = service.load(pid)
    render.stop(project, render.shorts(project, req.selection)["items"], req.target)
    return _rendu_view(pid, req.quality, req.selection)


@router.get("/{pid}/rendu/long.mp4")
def download_long(pid: str, quality: str = "1080p"):
    _check(pid)
    path = render.output_file(pid, quality) if quality in render.QUALITIES else None
    if not path or not path.is_file():
        raise HTTPException(404, "pas encore rendu")
    title = service.safe_name(service.load(pid).get("title") or "video", "video")
    return FileResponse(path, media_type="video/mp4", filename=f"{title}.mp4", content_disposition_type="attachment")


# --- Description et Upload --------------------------------------------------------------

def _publish_view(pid: str, selection: str | None) -> dict:
    data = publish.view(service.load(pid), selection)
    if publish.all_sent(data["videos"]):
        # tout est en ligne : le projet passe dans « Publiées »
        with service.editing(pid) as project:
            if project["status"].get("upload") != "done":
                project["status"]["upload"] = "done"
    return data


@router.get("/{pid}/publish")
def get_publish(pid: str, selection: str | None = None):
    """Les vidéos à publier (la longue, les shorts de la sélection) : métadonnées, vérifications, envois."""
    _check(pid)
    return _publish_view(pid, selection)


class UploadRequest(BaseModel):
    video: str
    selection: str | None = None


@router.post("/{pid}/upload")
def start_upload(pid: str, req: UploadRequest):
    _check(pid)
    try:
        with service.editing(pid) as project:
            publish.start(project, req.video, req.selection)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _publish_view(pid, req.selection)


@router.post("/{pid}/upload/stop")
def stop_upload(pid: str, req: UploadRequest):
    _check(pid)
    job = jobs.get(service.load(pid)["jobs"].get(f"upload:{req.video}") or "")
    if job and not job.finished:
        jobs.cancel(job)
    return _publish_view(pid, req.selection)
