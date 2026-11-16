"""
Côté worker : les tours de Claude (angles, titres, script, assistant), les copies de fichiers
dans le projet et le rendu du dérush. Aucun n'écrit project.json : le résultat reste dans
l'état du job, l'API l'applique au projet (service.sync).
"""
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from ...core import claude, jobs
from ...core.system import h264, tool
from ...core.tasks import Task, TaskContext
from ..settings.service import claude_model
from . import library, prompts, service
from . import script as script_doc

COPY_CHUNK = 8 * 1024 * 1024


def _tool_label(block: dict) -> str:
    name, args = block.get("name", ""), block.get("input") or {}
    if name == "WebSearch":
        return f"cherche « {args['query']} »" if args.get("query") else "cherche sur le web"
    if name == "WebFetch":
        return f"lit {urlparse(args['url']).netloc}" if args.get("url") else "lit une page web"
    target = args.get("file_path") or args.get("pattern") or ""
    shown = Path(target).name if "file_path" in args else target
    verb = {"Write": "écrit", "Edit": "retouche", "Read": "lit"}.get(name, name)
    return f"{verb} {shown}".strip()


def ask(ctx: TaskContext, prompt: str, system: str, tools: str, allowed: str | None = None,
        schema: dict | None = None, session_id: str | None = None, level: str = "light") -> dict:
    """Un tour de Claude dans le dossier script/ ; rend {text, output, session_id}.
    `level` : "light" (tour court) ou "heavy" (travail d'agent), pour le modèle choisi dans les réglages."""
    state = ctx.state
    result = {"text": "", "output": None, "session_id": session_id}
    ctx.set_status("thinking")
    for event in claude.stream(prompt, Path(ctx.payload["dir"]), system, session_id, claude_model(level), ctx.check_cancel,
                               tools=tools, json_schema=schema, allowed_tools=allowed):
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            result["session_id"] = event["session_id"]
        elif kind == "stream_event":
            e = event["event"]
            block = e.get("content_block") or {}
            if e["type"] == "content_block_start" and block.get("type") == "thinking":
                state["activity"] = "réfléchit"
                ctx.save(force=True)
            elif (e.get("delta") or {}).get("type") in ("text_delta", "input_json_delta"):
                if state.get("activity") != "rédige":
                    ctx.set_status("writing")
                    state["activity"] = "rédige"
                    ctx.save(force=True)
        elif kind == "assistant":
            for block in event["message"]["content"]:
                if block["type"] in ("tool_use", "server_tool_use") and block.get("name") != "StructuredOutput":
                    state["activity"] = _tool_label(block)
                    ctx.set_status("working")
                    ctx.save(force=True)
        elif kind == "result":
            claude.record_usage(event, ctx.job.kind)
            if event.get("is_error"):
                raise RuntimeError(event.get("result") or "Claude a renvoyé une erreur")
            result["text"] = event.get("result") or ""
            result["output"] = event.get("structured_output")
    state["activity"] = None
    return result


def _tools(web: bool, write: bool) -> tuple[str, str | None]:
    base = prompts.READ_TOOLS + (",Write,Edit" if write else "")
    return (f"{base},{prompts.WEB_TOOLS}", prompts.WEB_TOOLS) if web else (base, None)


def angles(ctx: TaskContext) -> None:
    p = ctx.payload
    tools, allowed = _tools(p.get("web", True), write=False)
    system = prompts.angles_system(p.get("web", True))
    if p["mode"] == "iterate":
        out = ask(ctx, prompts.iterate_prompt(p["angle"], p["note"]), system, tools, allowed, prompts.ANGLE_SCHEMA)
        angle = (out["output"] or {}).get("angle")
        if not angle:
            raise RuntimeError("Claude n'a pas renvoyé d'angle exploitable")
        ctx.state["result"] = {"mode": "iterate", "index": p["index"], "note": p["note"], "angle": angle,
                               "sources": out["output"].get("sources") or []}
    else:
        count = 3 - (1 if p.get("keep") else 0)
        out = ask(ctx, prompts.angles_prompt(p.get("existing", []), p.get("keep"), p.get("note", ""), count),
                  system, tools, allowed, prompts.ANGLES_SCHEMA)
        found = (out["output"] or {}).get("angles")
        if not found:
            raise RuntimeError("Claude n'a pas renvoyé d'angles exploitables")
        ctx.state["result"] = {"mode": "generate", "note": p.get("note", ""), "angles": found,
                               "sources": out["output"].get("sources") or []}
    ctx.state["applied"] = False


def titles(ctx: TaskContext) -> None:
    p = ctx.payload
    tools, allowed = _tools(p.get("web", False), write=False)
    out = ask(ctx, prompts.titles_prompt(p.get("angle"), p.get("kept", []), p.get("existing", []), p.get("note", "")),
              prompts.titles_system(), tools, allowed, prompts.TITLES_SCHEMA)
    found = (out["output"] or {}).get("titles")
    if not found:
        raise RuntimeError("Claude n'a pas renvoyé de titres exploitables")
    ctx.state["result"] = {"titles": found, "message": out["output"].get("message") or ""}
    ctx.state["applied"] = False


def thumb_ideas(ctx: TaskContext) -> None:
    p = ctx.payload
    # les références de la variante, là où Claude peut les lire (il ne voit que script/)
    refs = Path(p["dir"]) / service.THUMB_REFS_DIR
    shutil.rmtree(refs, ignore_errors=True)
    refs.mkdir()
    for kind, prefix in (("portraits", "portrait"), ("styles", "style")):
        for i, src in enumerate(p[kind], 1):
            shutil.copyfile(src, refs / f"{prefix}-{i}{Path(src).suffix.lower()}")
    tools, allowed = _tools(False, write=False)
    out = ask(ctx, prompts.thumb_ideas_prompt(p.get("angle"), p["titles"], p.get("title", ""), p["variants"],
                                              p.get("current"), len(p["portraits"]), len(p["styles"]),
                                              p.get("note", "")),
              prompts.thumb_ideas_system(), tools, allowed, prompts.THUMB_IDEAS_SCHEMA)
    found = (out["output"] or {}).get("compositions")
    if not found:
        raise RuntimeError("Claude n'a pas renvoyé de composition exploitable")
    ctx.state["result"] = {"compositions": found, "message": out["output"].get("message") or ""}
    ctx.state["applied"] = False


def script(ctx: TaskContext) -> None:
    p = ctx.payload
    tools, allowed = _tools(p.get("web", True), write=True)
    out = ask(ctx, prompts.script_prompt(p.get("angle"), p.get("rewrite", False)),
              prompts.script_system(p.get("web", True), p.get("duration", "")), tools, allowed,
              prompts.SCRIPT_SCHEMA)
    output = out["output"] or {}
    ctx.state["reply"] = output.get("message") or out["text"]
    ctx.state["result"] = {"sources": output.get("sources") or []}
    ctx.state["applied"] = False


def chat(ctx: TaskContext) -> None:
    state, p = ctx.state, ctx.payload
    messages = state["messages"]
    # un tour interrompu (worker relancé) repart de zéro
    while messages and messages[-1]["role"] == "ai":
        messages.pop()
    request = messages[-1]
    web = p.get("web", True)
    tools, allowed = _tools(web, write=False)
    if p.get("topic") == "angle":
        # les angles changent entre deux messages (générés, retenus, réécrits) : on les redonne à chaque fois
        project = service.load(p["project"])
        out = ask(ctx, prompts.angle_chat_prompt(request["text"], project["angles"], project.get("angle_sel")),
                  prompts.angle_chat_system(web), tools, allowed, prompts.ANGLE_CHAT_SCHEMA, state.get("session_id"))
        output = out["output"] or {}
        reply = {"role": "ai", "text": (output.get("message") or out["text"]).strip(), "quote": None,
                 "angles": output.get("angles") or []}
        state["result"] = {"sources": output.get("sources") or []}
        state["applied"] = False
    elif p.get("topic") == "roast":
        # au premier message, le script tel qu'il était au moment du roast et tout ce que le roast en
        # a dit ; ensuite, la session s'en souvient
        job = jobs.get(p["scope"])
        if not job or job.kind != roast.KIND:
            raise RuntimeError("ce roast a été supprimé")
        context = None if state.get("session_id") else roast.chat_context(job)
        out = ask(ctx, prompts.roast_chat_prompt(request["text"], request.get("quote"), context),
                  prompts.roast_chat_system(web, job.payload.get("cold", False)), tools, allowed, None,
                  state.get("session_id"))
        reply = {"role": "ai", "text": out["text"].strip(), "quote": request.get("quote")}
    else:
        # les plans et les visuels changent entre deux messages : on les redonne à chaque fois
        visuals = library.visuals(service.load(p["project"]))
        out = ask(ctx, prompts.chat_prompt(request["text"], request.get("quote"), script_doc.plans(p["project"]),
                                           visuals),
                  prompts.chat_system(web), tools, allowed, prompts.SCRIPT_CHAT_SCHEMA, state.get("session_id"))
        output = out["output"] or {}
        reply = {"role": "ai", "text": (output.get("message") or out["text"]).strip(), "quote": request.get("quote"),
                 "plans": _proposed_plans(output.get("plans") or [], visuals)}
    state["session_id"] = out["session_id"]
    messages.append(reply)


def _proposed_plans(found: list[dict], visuals: list[dict]) -> list[dict]:
    """Les plans proposés par Claude, avec un id (le plan créé quand on l'accepte le reprend) et le
    visuel choisi sous la forme d'un média de plan."""
    # les noms de fichiers ont des espaces insécables, des apostrophes courbes… que Claude ne recopie pas toujours
    loose = lambda s: " ".join(s.replace("’", "'").split()).lower()  # noqa: E731
    by_label = {loose(v["label"]): v for v in visuals}
    out = []
    for f in found:
        if f.get("type") not in prompts.PROPOSED_PLAN_TYPES or not (f.get("passage") or "").strip():
            continue
        v = by_label.get(loose(f.get("media") or ""))
        out.append({"id": "p" + uuid.uuid4().hex[:8], "type": f["type"], "passage": f["passage"].strip(),
                    "note": (f.get("note") or "").strip(), "why": (f.get("why") or "").strip(),
                    "media": [{k: v[k] for k in ("url", "name", "kind", "duration")}] if v else []})
    return out


# --- Copies et rendus ---------------------------------------------------------------

def copy(ctx: TaskContext) -> None:
    """Copie des fichiers choisis sur le disque (carte mémoire…) dans le dossier du projet."""
    files = ctx.state["files"]
    total = sum(Path(f["src"]).stat().st_size for f in files) or 1
    done = 0
    ctx.set_status("copying")
    for f in files:
        src, dest = Path(f["src"]), Path(f["dest"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        size = src.stat().st_size or 1
        copied = 0
        with src.open("rb") as fin, dest.open("wb") as fout:
            while chunk := fin.read(COPY_CHUNK):
                fout.write(chunk)
                copied += len(chunk)
                f["pct"] = round(copied / size * 100)
                ctx.progress = (done + copied) / total
                ctx.save()
                ctx.check_cancel()
        shutil.copystat(src, dest)
        done += size
        f["pct"] = 100
        ctx.save(force=True)


def _render_part(r: dict, dest: Path, fmt: dict, on_time: Callable[[float], None],
                 check_cancel: Callable[[], None]) -> None:
    """Une plage réencodée ; ffmpeg arrêté net si le job est annulé (une plage peut être un rush entier)."""
    w, h, fps = fmt["width"], fmt["height"], fmt["fps"]
    duration = r["end"] - r["start"]
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p"
    args = [tool("ffmpeg"), "-y", "-v", "error", "-nostats", "-progress", "pipe:1",
            "-ss", f"{r['start']:.3f}", "-t", f"{duration:.3f}", "-i", r["path"]]
    if not r.get("audio", True):
        # sans piste son, la concaténation casserait : on en fabrique une silencieuse
        args += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v:0", "-map", "1:a:0"]
    else:
        args += ["-map", "0:v:0", "-map", "0:a:0"]
    args += ["-vf", vf, *h264(18, "veryfast"),
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(dest)]
    long_render._run(args, on_time, check_cancel)


def render(ctx: TaskContext) -> None:
    """Le dérush en un seul .mp4 : chaque plage gardée est réencodée, puis tout est recollé."""
    ranges, fmt, dest = ctx.payload["ranges"], ctx.payload["format"], Path(ctx.payload["dest"])
    total = sum(r["end"] - r["start"] for r in ranges) or 1
    done = 0.0
    ctx.set_status("rendering")
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        parts = []
        for i, r in enumerate(ranges):
            part = Path(tmp) / f"part{i:04d}.mp4"

            def on_time(t: float, before: float = done, length: float = r["end"] - r["start"]) -> None:
                ctx.progress = (before + min(t, length)) / total * 0.97
                ctx.save()

            _render_part(r, part, fmt, on_time, ctx.check_cancel)
            parts.append(part)
            done += r["end"] - r["start"]
            ctx.progress = done / total * 0.97
            ctx.save()
            ctx.check_cancel()
        listing = Path(tmp) / "parts.txt"
        listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        partial = dest.with_suffix(".part.mp4")
        proc = subprocess.run([tool("ffmpeg"), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                               "-c", "copy", "-movflags", "+faststart", str(partial)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg : {proc.stderr.strip()[-300:]}")
        partial.replace(dest)


from . import asset_tasks, autoderush, beat_anim, kit_adapt, montage, montage_tasks, publish, render as long_render, roast, rush_search, sound_ideas, sound_place, storyboard, storyboard_chat, thumb_tasks, thumbs  # noqa: E402

TASKS = {
    # un type de job (et une file) par modèle d'image : les modèles tournent en parallèle
    **{f"project_thumb:{model}": Task(queue=f"fal:{model}", run=thumb_tasks.generate) for model in thumbs.MODELS},
    "project_images": Task(queue="images", run=asset_tasks.images),
    "project_captures": Task(queue="captures", run=asset_tasks.captures),
    "project_angles": Task(queue="scripts", run=angles),
    "project_thumb_ideas": Task(queue="thumb_ideas", run=thumb_ideas),
    "project_script": Task(queue="scripts", run=script),
    roast.KIND: Task(queue="roast", run=roast.run),
    "project_chat": Task(queue="chat", run=chat),
    "project_copy": Task(queue="io", run=copy),
    "project_render": Task(queue="render", run=render),
    autoderush.KIND: Task(queue="autoderush", run=autoderush.run),
    sound_ideas.KIND: Task(queue="sound_ideas", run=sound_ideas.run),
    sound_place.KIND: Task(queue="sound_ideas", run=sound_place.run),
    rush_search.KIND: Task(queue="search_index", run=rush_search.run),
    # les demandes à Daryl dans le chat du montage : une file par place, pour en traiter plusieurs à la fois
    **{kind: Task(queue=f"montage_{i}", run=montage_tasks.chat) for i, kind in enumerate(montage.TASK_KINDS)},
    storyboard.KIND: Task(queue="storyboard", run=storyboard.run),
    storyboard_chat.KIND: Task(queue="storyboard", run=storyboard_chat.run),
    # les animations des beats : une file par place, pour en créer plusieurs à la fois
    **{kind: Task(queue=f"beat_anim_{i}", run=beat_anim.run) for i, kind in enumerate(beat_anim.KINDS)},
    kit_adapt.KIND: Task(queue="kit", run=kit_adapt.run),
    "project_motion_render": Task(queue="render", run=montage_tasks.render_motion),
    # sa propre file : un rendu long ne bloque pas celui des motions
    long_render.KIND: Task(queue="long_render", run=long_render.run),
    publish.KIND: Task(queue="upload", run=publish.upload),
    "project_montage_media": Task(queue="media", run=montage_tasks.media),
    "project_titles": Task(queue="titles", run=titles),
}
